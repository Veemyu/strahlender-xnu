#include <atomic>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <thread>
extern "C" {
#include "../swkbd_keepalive.h"
#include "../host_shutdown.h"
}

static std::mutex lifecycle_lock;
static std::condition_variable lifecycle_cv;
static bool entered, release_present, returned, shutdown_started;
static int idle_calls, shutdown_calls;
static std::atomic<unsigned> presents{0};
static const char *negative;
extern "C" int swkbd_ui_visible(void) { return 1; }
extern "C" unsigned swkbd_ui_revision(void) { return 1; }
extern "C" int swkbd_ui_animating(void) { return 1; }
static uint64_t lifecycle_clock() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}
static uint64_t no_guest_present() { return 0; }
static void blocked_present() {
    if (!host_surface_enter()) return;
    std::unique_lock<std::mutex> guard(lifecycle_lock);
    presents++;
    entered = true;
    lifecycle_cv.notify_all();
    assert(lifecycle_cv.wait_for(guard, std::chrono::seconds(3), [] { return release_present; }));
    returned = true;
    guard.unlock();
    host_surface_leave();
}
static int gpu_idle() {
    idle_calls++;
    if (negative && !strcmp(negative, "gpu")) {
        std::unique_lock<std::mutex> guard(lifecycle_lock);
        lifecycle_cv.wait_for(guard, std::chrono::seconds(3), [] { return false; });
        return 0;
    }
    return 1;
}
extern "C" int vk_host_shutdown(void) {
    shutdown_calls++;
    {
        std::lock_guard<std::mutex> guard(lifecycle_lock);
        shutdown_started = true;
    }
    lifecycle_cv.notify_all();
    return host_surface_shutdown(gpu_idle, negative ? 100 : 2000);
}
class SurfaceObserver : public QObject {
public:
    bool destroyed = false;
    bool eventFilter(QObject *, QEvent *event) override {
        if (event->type() == QEvent::PlatformSurface &&
            static_cast<QPlatformSurfaceEvent *>(event)->surfaceEventType() ==
                QPlatformSurfaceEvent::SurfaceAboutToBeDestroyed) {
            std::lock_guard<std::mutex> guard(lifecycle_lock);
            assert(returned && idle_calls == 1 && !host_surface_enter());
            destroyed = true;
        }
        return false;
    }
};
static void verify_close_lifecycle(Host &host) {
    negative = std::getenv("BDSP_SHUTDOWN_NEGATIVE");
    auto *window = new RenderWindow;
    window->setSurfaceType(QSurface::RasterSurface); // No Vulkan driver in this native ordering test.
    host.setCentralWidget(QWidget::createWindowContainer(window));
    host.show();
    QCoreApplication::processEvents();
    assert(window->handle());
    SurfaceShutdownFilter surfaceShutdown(window);
    QCoreApplication::instance()->installEventFilter(&surfaceShutdown);
    surfaceShutdown.arm();
    SurfaceObserver observer;
    window->installEventFilter(&observer);
    static const SwkbdKeepalive callbacks = {lifecycle_clock, no_guest_present, blocked_present};
    swkbd_keepalive_wake(&callbacks);
    {
        std::unique_lock<std::mutex> guard(lifecycle_lock);
        assert(lifecycle_cv.wait_for(guard, std::chrono::seconds(3), [] { return entered; }));
    }
    if (negative && !strcmp(negative, "drain")) assert(host_surface_enter());
    std::thread release([] {
        std::unique_lock<std::mutex> guard(lifecycle_lock);
        assert(lifecycle_cv.wait_for(guard, std::chrono::seconds(3), [] { return shutdown_started; }));
        guard.unlock();
        // Wait until admission has actually closed; no sleeps as an ordering proxy.
        auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(1);
        while (host_surface_enter()) {
            host_surface_leave();
            assert(std::chrono::steady_clock::now() < deadline);
            std::this_thread::yield();
        }
        if (negative && !strcmp(negative, "keepalive")) return;
        guard.lock();
        release_present = true;
        guard.unlock();
        lifecycle_cv.notify_all();
    });
    bool surface_only = std::getenv("BDSP_SHUTDOWN_SURFACE_ONLY");
    if (surface_only) window->destroy(); // Must drain before ANY object-level surface cleanup filter.
    assert(host.close()); // Real close handler must drain/join BEFORE returning accepted.
    release.join();
    assert(!negative);
    assert(!host.isVisible());
    assert(returned && idle_calls == 1 && presents == 1);
    assert(vk_host_shutdown()); // Idempotent; no repeated idle callback.
    swkbd_keepalive_wake(&callbacks); // Terminal: no worker resurrection.
    assert(!host_surface_enter());
    if (!surface_only) window->destroy();
    assert(observer.destroyed && idle_calls == 1 && shutdown_calls >= 3 && presents == 1);
    window->removeEventFilter(&observer);
    QCoreApplication::instance()->removeEventFilter(&surfaceShutdown);
    puts("Lifecycle shutdown passed: drained, joined, no future wake, idempotent before surface destruction.");
}
