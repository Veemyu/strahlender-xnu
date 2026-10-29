// Real Qt actions, optionally linked to actual SDL/input/HID; no game or hardware.
#include "../app/linux/qt_ui.cpp"
#include <cassert>

static int current_mode = 1, reinit_failure, store_failure, calls, stores, fail_on_call;
static QString saved_path;
extern "C" {
volatile int g_bdsp_paused = 0, g_bdsp_fps = 60;
void vk_host_attach_instance(void *) {}
void vk_host_set_size(int, int) {}
void vk_host_surface_ready(unsigned long long) {}
#ifndef QT_LIFECYCLE_PROBE
int vk_host_shutdown(void) { return 1; }
#endif
void bdsp_set_fps(int value) { g_bdsp_fps = value; }
#ifndef QT_INPUT_PROBE
void input_handle_event(const void *) {}
int swkbd_ui_active(void) { return 0; }
void swkbd_ui_key(int) {}
void swkbd_ui_text(const char *) {}
void swkbd_ui_touch(int, float, float) {}
#else
uint64_t qt_input_guest_buttons(void);
void qt_input_keyboard_active(int);
const char *qt_input_text(void);
int qt_input_text_key(void);
#endif
int bdsp_joycon_mode(void) { return current_mode; }
int pad_sdl_mode_main(void) { return current_mode; }
int pad_sdl_init_main(int value) {
    calls++;
    if (calls == fail_on_call) { current_mode = -1; return 0; }
    if (reinit_failure) return 0;
    current_mode = value;
    return 1;
}
void pad_sdl_focus_main(int) {}
void pad_sdl_poll_main(void) {}
void pad_sdl_shutdown_main(void) {}
bool bdsp_joycon_store(const char *path, int value) {
    stores++;
    saved_path = QString::fromUtf8(path);
    assert(value == current_mode);
    return !store_failure;
}
}

static void dismiss_error() {
    QTimer::singleShot(0, [] {
        auto *dialog = qobject_cast<QMessageBox *>(QApplication::activeModalWidget());
        assert(dialog);
        dialog->accept();
    });
}

#ifdef QT_INPUT_PROBE
static void pump_release() {
    QEventLoop loop;
    QTimer::singleShot(40, &loop, &QEventLoop::quit);
    loop.exec();
}

static void verify_keyboard(QApplication &app, Host &host) {
    KeyForwarder filter(&host);
    app.installEventFilter(&filter);
    host.show();
    host.activateWindow();
    QCoreApplication::processEvents();
    assert(QApplication::activeWindow() == &host);
    auto key = [&](QEvent::Type type, int code, bool repeat = false,
                   Qt::KeyboardModifiers modifiers = Qt::NoModifier, const QString &text = {}) {
        QKeyEvent event(type, code, modifiers, text, repeat);
        QCoreApplication::sendEvent(host.windowHandle(), &event);
    };
    auto buttons = [] { return qt_input_guest_buttons(); };
    assert(buttons() == 0);
    const struct { int key, button; } mappings[] = {
        {Qt::Key_Return, PB_A}, {Qt::Key_Enter, PB_A}, {Qt::Key_Space, PB_A}, {Qt::Key_K, PB_A},
        {Qt::Key_Backspace, PB_B}, {Qt::Key_J, PB_B}, {Qt::Key_X, PB_X}, {Qt::Key_Y, PB_Y},
        {Qt::Key_Q, PB_L}, {Qt::Key_E, PB_R}, {Qt::Key_P, PB_PLUS}, {Qt::Key_O, PB_MINUS},
        {Qt::Key_Left, PB_LEFT}, {Qt::Key_A, PB_LEFT}, {Qt::Key_Right, PB_RIGHT}, {Qt::Key_D, PB_RIGHT},
        {Qt::Key_Up, PB_UP}, {Qt::Key_W, PB_UP}, {Qt::Key_Down, PB_DOWN}, {Qt::Key_S, PB_DOWN},
    };
    for (const auto &mapping : mappings) {
        key(QEvent::KeyPress, mapping.key);
        assert(buttons() == (1ull << mapping.button));
        key(QEvent::KeyRelease, mapping.key);
        pump_release();
        assert(buttons() == 0);
    }
    key(QEvent::KeyPress, Qt::Key_Return);
    assert(buttons() == (1ull << PB_A));
    key(QEvent::KeyPress, Qt::Key_Up);
    assert(buttons() == ((1ull << PB_A) | (1ull << PB_UP)));
    key(QEvent::KeyRelease, Qt::Key_Up, true);
    key(QEvent::KeyPress, Qt::Key_Up, true);
    assert(buttons() == ((1ull << PB_A) | (1ull << PB_UP)));
    key(QEvent::KeyRelease, Qt::Key_Up);
    key(QEvent::KeyPress, Qt::Key_Up);
    pump_release();
    assert(buttons() == ((1ull << PB_A) | (1ull << PB_UP)));
    key(QEvent::KeyRelease, Qt::Key_Up);
    key(QEvent::KeyRelease, Qt::Key_Return);
    pump_release();
    assert(buttons() == 0);
    for (auto modifier : {Qt::ControlModifier, Qt::AltModifier, Qt::MetaModifier})
        key(QEvent::KeyPress, Qt::Key_K, false, modifier);
    key(QEvent::KeyPress, Qt::Key_F10);
    assert(buttons() == 0);
    key(QEvent::KeyPress, Qt::Key_K);
    assert(buttons() == (1ull << PB_A));
    QEvent deactivate(QEvent::ApplicationDeactivate);
    QCoreApplication::sendEvent(&app, &deactivate);
    assert(buttons() == 0);
    key(QEvent::KeyPress, Qt::Key_K);
    assert(buttons() == (1ull << PB_A)); // held/timer bookkeeping reset as well.
    key(QEvent::KeyRelease, Qt::Key_K);
    QEvent lost(QEvent::FocusOut);
    QCoreApplication::sendEvent(host.windowHandle(), &lost);
    assert(buttons() == 0);
    pump_release();
    assert(buttons() == 0);
    key(QEvent::KeyPress, Qt::Key_K);
    QEvent window_deactivate(QEvent::WindowDeactivate);
    QCoreApplication::sendEvent(host.windowHandle(), &window_deactivate);
    assert(buttons() == 0);
    QMenu popup;
    popup.addAction(QStringLiteral("Fixture-only inert action"));
    popup.popup(QPoint(0, 0));
    QCoreApplication::processEvents();
    assert(QApplication::activePopupWidget());
    key(QEvent::KeyPress, Qt::Key_K);
    assert(buttons() == 0);
    popup.close();
    host.activateWindow();
    QCoreApplication::processEvents();
    key(QEvent::KeyPress, Qt::Key_K);
    qt_input_keyboard_active(1);
    key(QEvent::KeyRelease, Qt::Key_K);
    pump_release();
    qt_input_keyboard_active(0);
    assert(buttons() == 0); // release while a prompt was open reached the keyboard source.
    qt_input_keyboard_active(1);
    const QString unicode = QString::fromUtf8("\xe6\x97\xa5\xe6\x9c\xac");
    key(QEvent::KeyPress, Qt::Key_unknown, false, Qt::NoModifier, unicode);
    assert(QString::fromUtf8(qt_input_text()) == unicode && buttons() == 0);
    key(QEvent::KeyPress, Qt::Key_Backspace);
    assert(qt_input_text_key() == SWKBD_KEY_BACKSPACE && buttons() == 0);
    QWidget other;
    other.show();
    other.activateWindow();
    QCoreApplication::processEvents();
    assert(QApplication::activeWindow() == &other);
    qt_input_keyboard_active(1);
    key(QEvent::KeyPress, Qt::Key_unknown, false, Qt::NoModifier, unicode);
    assert(!*qt_input_text() && buttons() == 0);
    qt_input_keyboard_active(0);
    key(QEvent::KeyPress, Qt::Key_J);
    assert(buttons() == 0);
    other.hide();
    host.activateWindow();
    QCoreApplication::processEvents();
    assert(QApplication::activeWindow() == &host);
    qt_input_keyboard_active(0);
    key(QEvent::KeyPress, Qt::Key_J);
    assert(buttons() == (1ull << PB_B));
    key(QEvent::KeyRelease, Qt::Key_J);
    pump_release();
    assert(buttons() == 0);
    app.removeEventFilter(&filter);
    host.hide();
    puts("Real Qt KeyForwarder -> SDL -> input mixer -> registered guest HID passed.");
}
#endif

#ifdef QT_LIFECYCLE_PROBE
#include "qt_close_lifecycle_test.h"
#endif

int main(int argc, char **argv) {
    QApplication app(argc, argv);
    qputenv("BDSP_LANG", "en");
#ifdef QT_LIFECYCLE_PROBE
    Host host;
    verify_close_lifecycle(host);
    return 0;
#elif defined(QT_INPUT_PROBE)
    Host host;
    verify_keyboard(app, host);
    return 0;
#else
    const QString iconRoot = QCoreApplication::applicationDirPath() + "/icons/windows";
    assert(QDir().mkpath(iconRoot));
    QImage iconImage(32, 32, QImage::Format_RGB32);
    iconImage.fill(Qt::blue);
    assert(iconImage.save(iconRoot + "/test.png"));
    QFile iconMetadata(iconRoot + "/icons.json");
    assert(iconMetadata.open(QIODevice::WriteOnly));
    iconMetadata.write(R"({"schema":1,"default":"en-US","variants":[{"id":"en-US","label":"English","image":"test.png"},{"id":"de","label":"Deutsch","image":"test.png"}]})");
    iconMetadata.close();
    qunsetenv("BDSP_ICON_DIR");
    QSettings::setDefaultFormat(QSettings::IniFormat);
    QSettings::setPath(QSettings::IniFormat, QSettings::UserScope,
                       QCoreApplication::applicationDirPath() + "/prefs");
    QStandardPaths::setTestModeEnabled(true);
    qunsetenv("BDSP_JOYCONS");
    const QString destination = QDir(QStandardPaths::writableLocation(
        QStandardPaths::GenericDataLocation)).filePath(QStringLiteral("StrahlenderXnu/controller-mode.txt"));
    const QString folder = QFileInfo(destination).absolutePath();
    const bool folder_existed = QDir(folder).exists();
    qputenv("BDSP_CONTROLLER_CONFIG", destination.toUtf8());
    Host host;
    assert(bdsp::iconsDirectory() == iconRoot);
    assert(!app.windowIcon().isNull() && !host.windowIcon().isNull());
    QWindow taskbarWindow;
    assert(!taskbarWindow.icon().isNull());
    QAction *germanIcon = nullptr;
    for (QAction *action : host.findChildren<QAction *>())
        if (action->text().startsWith("Deutsch")) germanIcon = action;
    assert(germanIcon);
    germanIcon->trigger();
    QSettings iconSettings("dev.local", "xnubdsp");
    assert(iconSettings.value("bdsp_app_icon").toString() == "de");
    QAction *single = nullptr, *pair = nullptr;
    for (QAction *action : host.findChildren<QAction *>()) {
        if (action->text() == QStringLiteral("Individual Joy-Cons (mini mode)")) single = action;
        if (action->text() == QStringLiteral("Paired Joy-Cons")) pair = action;
    }
    assert(single && pair && !single->isEnabled() && !pair->isEnabled());
    host.controllersReady();
    assert(single->isEnabled() && pair->isChecked());
    single->trigger();
    assert(current_mode == 0 && single->isChecked() && stores == 1 && calls == 1);
    assert(saved_path == destination);
    single->trigger();
    assert(stores == 1 && calls == 1);
    store_failure = 1;
    dismiss_error();
    pair->trigger();
    assert(current_mode == 0 && single->isChecked() && stores == 2 && calls == 3);
    store_failure = 0;
    reinit_failure = 1;
    dismiss_error();
    pair->trigger();
    assert(current_mode == 0 && single->isChecked() && stores == 2 && calls == 4);
    reinit_failure = 0;
    pair->trigger();
    assert(current_mode == 1 && pair->isChecked() && stores == 3);
    store_failure = 1;
    fail_on_call = calls + 2;
    dismiss_error();
    single->trigger();
    assert(current_mode == -1 && !single->isEnabled() && !pair->isEnabled());
    store_failure = 0;
    fail_on_call = 0;
    current_mode = 1;
    host.controllersReady();
    assert(pair->isEnabled() && pair->isChecked());
    qputenv("BDSP_JOYCONS", "single");
    host.controllersReady();
    assert(!single->isEnabled() && !pair->isEnabled());
    qunsetenv("BDSP_JOYCONS");
    qputenv("BDSP_CONTROLLER_CONFIG", "isolated-test/controller-mode.txt");
    host.controllersReady();
    assert(!single->isEnabled() && !pair->isEnabled());
    if (!folder_existed) assert(QDir().rmdir(folder));
    puts("Real Qt controller menu selection, persistence rollback and override gates passed.");
    return 0;
#endif
}
