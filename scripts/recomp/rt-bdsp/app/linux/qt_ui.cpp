// In-process Qt host (Linux/Vulkan), with menus matching the Mac app (rt-bdsp/app/app_ui.m).
// Qt owns a QWindow with QSurface::VulkanSurface embedded in a window container, supporting X11 and native Wayland.
// device.c host API: vk_host_attach_instance() receives Qt's VkInstance; vk_host_set_size() publishes pixel dimensions;
// vk_host_surface_ready() initializes the device, swapchain, and runtime. device.c calls bdsp_qt_ui_run() on the main thread
// through a weak symbol linked only in Qt builds (rt-bdsp/build.sh, BDSP_QT=1).
// Environment: BDSP_LANG, BDSP_LPROJ, BDSP_MANGOHUD=1 (initial overlay), BDSP_FPS, BDSP_SAVE, BDSP_QT_SCRIPT.
// Script actions: fps30 fps60 fps120 size1920x1080 win1000x900 pause fullscreen hud grab spectacle dumpmenus quit.
#include <SDL3/SDL.h>

#include <QAction>
#include <QActionGroup>
#include <QApplication>
#include "bdsp_icons.h"
#include "bdsp_theme.h"
#include <QCloseEvent>
#include <QCoreApplication>
#include <QDateTime>
#include <QDesktopServices>
#include <QDir>
#include <QFile>
#include <QFileDialog>
#include <QFileInfo>
#include <QKeyEvent>
#include <QKeySequence>
#include <QMainWindow>
#include <QMenu>
#include <QMenuBar>
#include <QMouseEvent>
#include <QMessageBox>
#include <QPalette>
#include <QProcess>
#include <QProcessEnvironment>
#include <QResizeEvent>
#include <QSet>
#include <QScreen>
#include <QStandardPaths>
#include <QTimer>
#include <QUrl>
#include <QVulkanInstance>
#include <QVersionNumber>
#include <QWidget>
#include <QWindow>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <unistd.h>
#include <vector>

#include "bdsp_l10n.h"

extern "C" {
void vk_host_attach_instance(void *vk_instance);
void vk_host_set_size(int w, int h);
void vk_host_surface_ready(unsigned long long surface);
void bdsp_set_fps(int fps);
extern volatile int g_bdsp_paused;
extern volatile int g_bdsp_fps;
void input_handle_event(const void *ev);
int bdsp_qt_ui_run(void);
}

namespace {

const int kSizes[4][2] = {{960, 540}, {1280, 720}, {1920, 1080}, {2560, 1440}};
const int kFps[3] = {30, 60, 120};

void out(const QString &line) {
    std::fputs(line.toUtf8().constData(), stdout);
    std::fputc('\n', stdout);
    std::fflush(stdout);
}

QString lprojDir() {
    const QString env = qEnvironmentVariable("BDSP_LPROJ");
    if (!env.isEmpty()) return env;
    const QString next = QCoreApplication::applicationDirPath() + QStringLiteral("/lproj");
    if (QFileInfo(next).isDir()) return next;
#ifdef BDSP_LPROJ_DIR
    return QStringLiteral(BDSP_LPROJ_DIR);
#else
    return QStringLiteral("lproj");
#endif
}

QString fillSize(QString s, int w, int h) {
    for (int v : {w, h}) {
        const int i = s.indexOf(QStringLiteral("%d"));
        if (i >= 0) s.replace(i, 2, QString::number(v));
    }
    return s;
}

// On-screen keyboard (swkbd_ui.c in the runtime, same process): while it is open, typed text, editing keys and the left mouse button go to it.
extern "C" {
#include "../../swkbd_ui.h"
}

// Qt key -> SDL scancode used by nvn_glue.c (input_handle_event).
SDL_Scancode scancodeFor(int key) {
    switch (key) {
    case Qt::Key_Return: case Qt::Key_Enter: return SDL_SCANCODE_RETURN;
    case Qt::Key_Space: return SDL_SCANCODE_SPACE;
    case Qt::Key_Backspace: return SDL_SCANCODE_BACKSPACE;
    case Qt::Key_Left: return SDL_SCANCODE_LEFT;
    case Qt::Key_Right: return SDL_SCANCODE_RIGHT;
    case Qt::Key_Up: return SDL_SCANCODE_UP;
    case Qt::Key_Down: return SDL_SCANCODE_DOWN;
    case Qt::Key_A: return SDL_SCANCODE_A;
    case Qt::Key_D: return SDL_SCANCODE_D;
    case Qt::Key_E: return SDL_SCANCODE_E;
    case Qt::Key_J: return SDL_SCANCODE_J;
    case Qt::Key_K: return SDL_SCANCODE_K;
    case Qt::Key_O: return SDL_SCANCODE_O;
    case Qt::Key_P: return SDL_SCANCODE_P;
    case Qt::Key_Q: return SDL_SCANCODE_Q;
    case Qt::Key_S: return SDL_SCANCODE_S;
    case Qt::Key_W: return SDL_SCANCODE_W;
    case Qt::Key_X: return SDL_SCANCODE_X;
    case Qt::Key_Y: return SDL_SCANCODE_Y;
    default: return SDL_SCANCODE_UNKNOWN;
    }
}

// Qt creates the Vulkan surface; the game renders through the runtime swapchain. Keys become SDL input events.
class RenderWindow : public QWindow {
public:
    RenderWindow() { setSurfaceType(QSurface::VulkanSurface); }

protected:
    void resizeEvent(QResizeEvent *) override { publishSize(); }
    // The on-screen keyboard takes the left mouse button while it is open (position relative to the window, like the Mac and SDL versions).
    void mousePressEvent(QMouseEvent *e) override { keyboardTouch(1, e); }
    void mouseReleaseEvent(QMouseEvent *e) override { keyboardTouch(0, e); }

    void keyboardTouch(int down, QMouseEvent *e) {
        if (swkbd_ui_active() && e->button() == Qt::LeftButton && width() > 0 && height() > 0)
            swkbd_ui_touch(down, float(e->position().x() / width()), float(e->position().y() / height()));
    }

public:
    void publishSize() {  // Surface pixels: logical dimensions times devicePixelRatio.
        const double r = devicePixelRatio();
        vk_host_set_size(qRound(width() * r), qRound(height() * r));
    }
};

// Application-wide keyboard filter forwards to nvn_glue.c input_handle_event regardless of focused child.
// The main window must be active with no popup/dialog. Ctrl/Alt/Meta shortcuts remain menu shortcuts.
class KeyForwarder : public QObject {
public:
    explicit KeyForwarder(QWidget *host) : host_(host) {}
    bool eventFilter(QObject *obj, QEvent *ev) override {
        if (ev->type() != QEvent::KeyPress && ev->type() != QEvent::KeyRelease) return false;
        if (!obj->isWindowType()) return false;  // Events pass through windows/widgets repeatedly; count only the window level.
        QKeyEvent *e = static_cast<QKeyEvent *>(ev);
        if (swkbd_ui_active()) {  // the on-screen keyboard is open: the keys type into it, the game sees none
            if (ev->type() == QEvent::KeyPress && !(e->modifiers() & (Qt::ControlModifier | Qt::AltModifier | Qt::MetaModifier))) {
                switch (e->key()) {
                case Qt::Key_Backspace: swkbd_ui_key(SWKBD_KEY_BACKSPACE); break;
                case Qt::Key_Delete: swkbd_ui_key(SWKBD_KEY_DELETE); break;
                case Qt::Key_Left: swkbd_ui_key(SWKBD_KEY_LEFT); break;
                case Qt::Key_Right: swkbd_ui_key(SWKBD_KEY_RIGHT); break;
                case Qt::Key_Home: swkbd_ui_key(SWKBD_KEY_HOME); break;
                case Qt::Key_End: swkbd_ui_key(SWKBD_KEY_END); break;
                case Qt::Key_Return: case Qt::Key_Enter: swkbd_ui_key(SWKBD_KEY_ENTER); break;
                case Qt::Key_Escape: swkbd_ui_key(SWKBD_KEY_ESCAPE); break;
                default: {
                    const QString t = e->text();
                    if (!t.isEmpty() && t.at(0).isPrint()) swkbd_ui_text(t.toUtf8().constData());
                }
                }
            }
            return true;
        }
        const bool down = ev->type() == QEvent::KeyPress;
        if (down && ((e->modifiers() & (Qt::ControlModifier | Qt::AltModifier | Qt::MetaModifier)) ||
                     QApplication::activeWindow() != host_ || QApplication::activePopupWidget()))
            return false;  // Always forward releases to avoid stuck keys.
        handle(e->key(), down, e->isAutoRepeat());
        return false;
    }

    // Wayland repeats may arrive as immediate release/press pairs. Measurements showed held-state flicker
    // when a second key was pressed. Briefly defer releases; a matching press during that interval
    // is a repeat and leaves the held state unchanged.
    void handle(int key, bool down, bool autoRepeat) {
        static int trace = -1;
        if (trace < 0) trace = qEnvironmentVariableIsSet("BDSP_TRACE_INPUT");
        if (trace) out(QStringLiteral("[qt] Key %1 %2%3").arg(key).arg(down ? QStringLiteral("down") : QStringLiteral("up"),
                                                                   autoRepeat ? QStringLiteral(" (repeat)") : QString()));
        if (autoRepeat) return;
        if (scancodeFor(key) == SDL_SCANCODE_UNKNOWN) return;
        QTimer *&t = pending_[key];
        if (down) {
            if (t && t->isActive()) { t->stop(); return; }  // Repeat: discard pending release and keep key held.
            if (held_.contains(key)) return;
            held_.insert(key);
            send(key, true);
        } else {
            if (!held_.contains(key)) return;
            if (!t) {
                t = new QTimer(this);
                t->setSingleShot(true);
                connect(t, &QTimer::timeout, this, [this, key] { held_.remove(key); send(key, false); });
            }
            t->start(kReleaseDelayMs);
        }
    }

private:
    static constexpr int kReleaseDelayMs = 20;
    static void send(int key, bool down) {
        SDL_Event ev;
        SDL_zero(ev);
        ev.type = down ? SDL_EVENT_KEY_DOWN : SDL_EVENT_KEY_UP;
        ev.key.scancode = scancodeFor(key);
        ev.key.down = down;
        input_handle_event(&ev);
    }
    QWidget *host_;
    QHash<int, QTimer *> pending_;
    QSet<int> held_;
};

// Black area below menus: centered, unstretched 16:9 canvas with letterboxing. Dimensions are logical pixels.
class Stage : public QWidget {
public:
    explicit Stage(QWidget *parent) : QWidget(parent) {
        setAutoFillBackground(true);
        QPalette pal = palette();
        pal.setColor(backgroundRole(), Qt::black);
        setPalette(pal);
        setMinimumSize(320, 180);
    }
    void setCanvas(QWidget *w) {
        canvas = w;
        w->setParent(this);
        w->show();
        layoutCanvas();
    }

protected:
    void resizeEvent(QResizeEvent *e) override {
        QWidget::resizeEvent(e);
        layoutCanvas();
    }

private:
    void layoutCanvas() {
        if (!canvas) return;
        const int W = width(), H = height();
        const int w = qMin(W, H * 16 / 9);
        const int h = w * 9 / 16;
        canvas->setGeometry((W - w) / 2, (H - h) / 2, w, h);
    }
    QWidget *canvas = nullptr;
};

class Host : public QMainWindow {
public:
    Host() : tr_(bdsp::Translator(localeName(), lprojDir())) {
        stage_ = new Stage(this);
        setCentralWidget(stage_);
        setWindowTitle(QStringLiteral("BDSP"));
        fps_ = g_fpsNow();
        hudOn_ = qEnvironmentVariable("BDSP_MANGOHUD") == QLatin1String("1");
        buildMenus();
        bdsp::installIconMenu(menuBar(), this);
        hudAct_->setChecked(hudOn_);
    }

    static QString hudConfPath() {
        const QString rt = qEnvironmentVariable("XDG_RUNTIME_DIR");
        return (rt.isEmpty() ? QDir::homePath() : rt) + QStringLiteral("/bdsp-mangohud.conf");
    }
    static void writeHudConf(bool shown) {  // MangoHud reloads changed configuration, allowing toggles without restarting.
        const double ratio = QApplication::primaryScreen() ? QApplication::primaryScreen()->devicePixelRatio() : 1.0;
        QFile f(hudConfPath());
        if (!f.open(QIODevice::WriteOnly | QIODevice::Truncate)) return;
        QString s = QStringLiteral("fps\nframetime\nframe_timing=1\ncpu_stats\ngpu_stats\nfont_size=%1\nposition=top-left\n").arg(qRound(20 * ratio));
        if (!shown) s += QStringLiteral("no_display\n");
        f.write(s.toUtf8());
    }

    void embed(RenderWindow *rw) {
        rw_ = rw;
        container_ = QWidget::createWindowContainer(rw, stage_);
        container_->setFocusPolicy(Qt::StrongFocus);
        stage_->setCanvas(container_);
        container_->setFocus();
    }
    void applyDefaultSize() { setSize(kSizes[1][0], kSizes[1][1]); }  // After show(), stage dimensions correctly exclude window decorations.

    void runScript(const QString &spec) {
        for (const QString &tok : spec.split(QLatin1Char(','), Qt::SkipEmptyParts)) {
            const int colon = tok.indexOf(QLatin1Char(':'));
            if (colon < 0) continue;
            const int ms = int(tok.left(colon).toDouble() * 1000);
            const QString action = tok.mid(colon + 1).trimmed();
            QTimer::singleShot(ms, this, [this, action] { doTest(action); });
        }
    }

protected:
    void closeEvent(QCloseEvent *e) override {
        e->accept();
        std::fflush(nullptr);
        _exit(0);  // Match SDL window-close exit: runtime threads are live, so skip teardown.
    }

private:
    static int g_fpsNow() { return g_bdsp_fps; }
    static QString localeName() {
        const QString o = qEnvironmentVariable("BDSP_LANG");
        return o.isEmpty() ? bdsp::systemLocale() : o;
    }

    QAction *act(QMenu *menu, const QString &title, std::function<void()> slot, const char *key = nullptr, bool checkable = false,
                 QActionGroup *group = nullptr) {
        QAction *a = new QAction(title, this);
        if (key) a->setShortcut(QKeySequence(QString::fromLatin1(key)));
        a->setCheckable(checkable);
        connect(a, &QAction::triggered, this, [slot](bool) { slot(); });
        if (group) group->addAction(a);
        menu->addAction(a);
        return a;
    }

    void buildMenus() {  // Match the menu structure and localization keys in bdsp_qt_host.cpp / app_ui.m.
        QMenuBar *bar = menuBar();
        QMenu *m = bar->addMenu(tr_("File"));
        act(m, tr_("Open Save Folder"), [this] { openSave(); }, "Ctrl+O");
        act(m, tr_("Import Save …"), [this] { importSave(); }, "Ctrl+I");
        m->addSeparator();
        pauseAct_ = act(m, tr_("Pause"), [this] { togglePause(); }, "Ctrl+P", true);
        act(m, tr_("Restart"), [this] { restartGame(); }, "Ctrl+R");
        act(m, tr_("Reset Game …"), [this] { resetSave(); }, "Ctrl+Shift+R");
        m->addSeparator();
        act(m, tr_("Quit BDSP"), [this] { close(); }, "Ctrl+Q");

        m = viewMenu_ = bar->addMenu(tr_("View"));
        fullAct_ = act(m, tr_("Full Screen"), [this] { toggleFullscreen(); }, "Ctrl+F", true);
        fpsMenu_ = m->addMenu(tr_("Frame Rate"));
        QActionGroup *grp = new QActionGroup(this);
        grp->setExclusive(true);
        for (int f : kFps) {
            QAction *a = act(fpsMenu_, QStringLiteral("%1 fps").arg(f), [this, f] { setFps(f); }, nullptr, true, grp);
            a->setChecked(f == fps_);
            fpsActs_.insert(f, a);
        }
        m->addSeparator();
        for (int i = 0; i < 4; i++) {
            const int w = kSizes[i][0], h = kSizes[i][1];
            const QByteArray key = "Ctrl+" + QByteArray::number(i + 1);
            act(m, fillSize(tr_("Window Size %d × %d"), w, h), [this, w, h] { setSize(w, h); }, key.constData());
        }
        m->addSeparator();
        debugMenu_ = m->addMenu(tr_("Debug"));
        hudAct_ = act(debugMenu_, tr_("Show MangoHud"), [this] { writeHudConf(hudAct_->isChecked()); }, nullptr, true);
        hudAct_->setEnabled(!QStandardPaths::findExecutable(QStringLiteral("mangohud")).isEmpty());

        m = bar->addMenu(tr_("Window"));
        act(m, tr_("Minimize"), [this] { showMinimized(); }, "Ctrl+M");

        m = bar->addMenu(tr_("Help"));
        act(m, tr_("Key Bindings …"), [this] { QMessageBox::information(this, tr_("Key Bindings"), tr_("KEYS_HELP")); });
        act(m, tr_("Open Cache Folder (Shaders, Images)"), [this] { openDir("work/recomp/cache"); });
        act(m, tr_("Open Log Folder"), [this] { openDir("work/recomp/logs"); });
    }

    // ---------------------------------------------------------------- Actions (same hooks as SDL function keys)
    void setFps(int f) {
        fps_ = f;
        if (fpsActs_.contains(f)) fpsActs_[f]->setChecked(true);
        bdsp_set_fps(f);
        out(QStringLiteral("[qt] Frame rate %1").arg(f));
    }

    void setSize(int w, int h) {  // Requested logical canvas size; window adds menus/decorations.
        if (isFullScreen()) {
            showNormal();
            fullAct_->setChecked(false);
        }
        resize(w + width() - stage_->width(), h + height() - stage_->height());
        QTimer::singleShot(300, this, [this] { reportCanvas(); });
    }

    void reportCanvas() {
        if (!container_) return;
        const double r = devicePixelRatioF();
        out(QStringLiteral("[qt] Canvas %1x%2 logical, %3x%4 pixels (devicePixelRatio %5), stage %6x%7, window %8x%9, platform %10")
                .arg(container_->width()).arg(container_->height()).arg(qRound(container_->width() * r)).arg(qRound(container_->height() * r))
                .arg(r, 0, 'f', 2).arg(stage_->width()).arg(stage_->height()).arg(width()).arg(height()).arg(QGuiApplication::platformName()));
    }

    void toggleFullscreen() {
        if (isFullScreen()) showNormal(); else showFullScreen();
        fullAct_->setChecked(isFullScreen());
    }

    void togglePause() {
        paused_ = !paused_;
        pauseAct_->setChecked(paused_);
        g_bdsp_paused = paused_ ? 1 : 0;
    }

    void restartGame() {  // Restart the process; the Qt host has no in-process runtime restart.
        QFile f(QStringLiteral("/proc/self/cmdline"));
        if (!f.open(QIODevice::ReadOnly)) return;
        const QList<QByteArray> parts = f.readAll().split('\0');
        QList<QByteArray> args;
        for (const QByteArray &p : parts) if (!p.isEmpty()) args << p;
        if (args.isEmpty()) return;
        std::vector<char *> argv;
        for (QByteArray &a : args) argv.push_back(a.data());
        argv.push_back(nullptr);
        std::fflush(nullptr);
        execv("/proc/self/exe", argv.data());
    }

    QString saveDir() const {
        const QString base = qEnvironmentVariable("BDSP_SAVE");
        return QDir(base.isEmpty() ? QStringLiteral("work/recomp/save") : base).absoluteFilePath(QStringLiteral("save_1"));
    }

    void backupSave(const QString &kind) {
        const QDir sd(saveDir());
        QStringList files;
        for (const QString &n : {QStringLiteral("SaveData.bin"), QStringLiteral("Backup.bin")})
            if (sd.exists(n)) files << n;
        if (files.isEmpty()) return;
        QDir bd(QDir::cleanPath(sd.absoluteFilePath(QStringLiteral("../backups/%1-%2"))
                                    .arg(kind, QDateTime::currentDateTime().toString(QStringLiteral("yyyyMMdd-HHmmss")))));
        QDir().mkpath(bd.absolutePath());
        for (const QString &n : files) QFile::copy(sd.filePath(n), bd.filePath(n));
    }

    void importSave() {
        QString title = tr_("Import Save …");
        title.remove(QStringLiteral(" …"));
        const QString path = QFileDialog::getOpenFileName(this, title, QString(), QStringLiteral("SaveData.bin (SaveData.bin);;*"));
        if (path.isEmpty()) return;
        const QDir src = QFileInfo(path).absoluteDir();
        backupSave(QStringLiteral("import"));
        QDir().mkpath(saveDir());
        for (const QString &n : {QStringLiteral("SaveData.bin"), QStringLiteral("Backup.bin")}) {
            if (!src.exists(n)) continue;
            QFile::remove(QDir(saveDir()).filePath(n));
            QFile::copy(src.filePath(n), QDir(saveDir()).filePath(n));
        }
        restartGame();
    }

    void resetSave() {
        if (QMessageBox::question(this, tr_("Reset Game"), tr_("RESET_CONFIRM")) != QMessageBox::Yes) return;
        backupSave(QStringLiteral("reset"));
        for (const QString &n : {QStringLiteral("SaveData.bin"), QStringLiteral("Backup.bin")}) QFile::remove(QDir(saveDir()).filePath(n));
        restartGame();
    }

    void openDir(const char *d) {
        const QFileInfo fi(QString::fromLatin1(d));
        QDesktopServices::openUrl(QUrl::fromLocalFile(fi.isDir() ? fi.absoluteFilePath() : QDir::currentPath()));
    }
    void openSave() { QDesktopServices::openUrl(QUrl::fromLocalFile(QDir::cleanPath(saveDir() + QStringLiteral("/..")))); }

    // ---------------------------------------------------------------- Test script
    void dumpMenu(QMenu *menu, int indent) {
        for (QAction *x : menu->actions()) {
            if (x->isSeparator()) continue;
            const QString sc = x->shortcut().toString();
            out(QStringLiteral("[menu] %1%2%3").arg(QString(indent * 2, QLatin1Char(' ')), x->text(), sc.isEmpty() ? QString() : QStringLiteral("   [%1]").arg(sc)));
            if (x->menu()) dumpMenu(x->menu(), indent + 1);
        }
    }

    void doTest(const QString &a) {
        out(QStringLiteral("[qt] Test: %1").arg(a));
        if (a.startsWith(QStringLiteral("fps"))) {
            setFps(a.mid(3).toInt());
        } else if (a.startsWith(QStringLiteral("size"))) {
            const QStringList p = a.mid(4).split(QLatin1Char('x'));
            if (p.size() == 2) setSize(p[0].toInt(), p[1].toInt());
        } else if (a.startsWith(QStringLiteral("win"))) {
            const QStringList p = a.mid(3).split(QLatin1Char('x'));
            if (p.size() == 2) resize(p[0].toInt(), p[1].toInt());
            QTimer::singleShot(300, this, [this] { reportCanvas(); });
        } else if (a == QLatin1String("pause")) {
            togglePause();
        } else if (a == QLatin1String("fullscreen")) {
            toggleFullscreen();
        } else if (a == QLatin1String("hud")) {
            hudAct_->setChecked(!hudAct_->isChecked());
            writeHudConf(hudAct_->isChecked());
        } else if (a == QLatin1String("grab")) {
            QDir().mkpath(QStringLiteral("work/recomp/shots"));
            grab().save(QStringLiteral("work/recomp/shots/qt_window.png"));
            reportCanvas();
        } else if (a == QLatin1String("dumpmenus")) {
            out(QStringLiteral("[menu] Language: %1").arg(tr_.locale().isEmpty() ? QStringLiteral("(none, fallback en)") : tr_.locale()));
            for (QAction *x : menuBar()->actions()) {
                out(QStringLiteral("[menu] %1").arg(x->text()));
                if (x->menu()) dumpMenu(x->menu(), 1);
            }
        } else if (a == QLatin1String("spectacle")) {  // KDE Wayland capture of the active window.
            QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
            env.insert(QStringLiteral("DBUS_SESSION_BUS_ADDRESS"), QStringLiteral("unix:path=%1/bus").arg(qEnvironmentVariable("XDG_RUNTIME_DIR")));
            const QString wl = qEnvironmentVariable("BDSP_WAYLAND_DISPLAY");
            env.insert(QStringLiteral("WAYLAND_DISPLAY"), wl.isEmpty() ? QStringLiteral("wayland-0") : wl);
            env.remove(QStringLiteral("QT_QPA_PLATFORM"));
            QDir().mkpath(QStringLiteral("work/recomp/shots"));
            QProcess *p = new QProcess(this);
            p->setProcessEnvironment(env);
            p->start(QStringLiteral("spectacle"),
                     {QStringLiteral("-b"), QStringLiteral("-n"), QStringLiteral("-a"), QStringLiteral("-o"),
                      QFileInfo(QStringLiteral("work/recomp/shots/qt_spectacle.png")).absoluteFilePath()});
        } else if (a == QLatin1String("keystorm")) {  // Test: hold Left/Up, repeat Up with release/press pairs, then genuinely release.
            QWindow *w = windowHandle();
            auto send = [w](QEvent::Type t, int k) { QKeyEvent ev(t, k, Qt::NoModifier); QCoreApplication::sendEvent(w, &ev); };
            send(QEvent::KeyPress, Qt::Key_Left);
            send(QEvent::KeyPress, Qt::Key_Up);
            for (int i = 0; i < 8; i++)
                QTimer::singleShot(100 + i * 40, this, [send] { send(QEvent::KeyRelease, Qt::Key_Up); send(QEvent::KeyPress, Qt::Key_Up); });
            QTimer::singleShot(600, this, [send] { send(QEvent::KeyRelease, Qt::Key_Up); send(QEvent::KeyRelease, Qt::Key_Left); });
        } else if (a.startsWith(QStringLiteral("key"))) {  // Synthetic Return through the same filter as real keys; hold for 0.4 seconds.
            QKeyEvent dn(QEvent::KeyPress, Qt::Key_Return, Qt::NoModifier);
            QCoreApplication::sendEvent(windowHandle(), &dn);
            QTimer::singleShot(400, this, [this] {
                QKeyEvent up(QEvent::KeyRelease, Qt::Key_Return, Qt::NoModifier);
                QCoreApplication::sendEvent(windowHandle(), &up);
            });
        } else if (a == QLatin1String("quit")) {
            close();
        }
    }

    bdsp::Translator tr_;
    Stage *stage_ = nullptr;
    QWidget *container_ = nullptr;
    RenderWindow *rw_ = nullptr;
    QAction *pauseAct_ = nullptr, *fullAct_ = nullptr, *hudAct_ = nullptr;
    QMenu *viewMenu_ = nullptr, *fpsMenu_ = nullptr, *debugMenu_ = nullptr;
    QHash<int, QAction *> fpsActs_;
    int fps_ = 60;
    bool paused_ = false, hudOn_ = false;
};

}  // namespace

int bdsp_qt_ui_run(void) {
    static int argc = 1;
    static char arg0[] = "bdsp";
    static char *argv[] = {arg0, nullptr};
    if (qEnvironmentVariableIsEmpty("XAUTHORITY") && !qEnvironmentVariableIsEmpty("DISPLAY")) {  // Session X11/Xwayland authority file in the runtime directory.
        const QDir rt(qEnvironmentVariable("XDG_RUNTIME_DIR"));
        const QStringList c = rt.entryList({QStringLiteral("*xauth*")}, QDir::Files, QDir::Name);
        if (!c.isEmpty()) qputenv("XAUTHORITY", rt.filePath(c.first()).toUtf8());
    }
    QApplication app(argc, argv);
    bdsp::installTheme();
    const QString platform = QGuiApplication::platformName();
    out(QStringLiteral("[qt] Platform: %1").arg(platform));

    // Configure the implicit MangoHud Vulkan layer before vkCreateInstance; hidden by default, toggled by menu.
    if (!QStandardPaths::findExecutable(QStringLiteral("mangohud")).isEmpty()) {
        Host::writeHudConf(qEnvironmentVariable("BDSP_MANGOHUD") == QLatin1String("1"));
        qputenv("MANGOHUD", "1");
        qputenv("MANGOHUD_CONFIGFILE", Host::hudConfPath().toUtf8());
    }
    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");

    QVulkanInstance qvi;  // Qt creates the instance and chooses platform surface extensions; device.c receives only VkInstance.
    qvi.setApiVersion(QVersionNumber(1, 3));
    QByteArrayList exts = {"VK_KHR_surface"};
    if (platform == QLatin1String("wayland")) exts << "VK_KHR_wayland_surface";
    else if (platform == QLatin1String("xcb")) exts << "VK_KHR_xcb_surface";
    // WINDOWS (prepared, not built/tested): platform "windows" needs VK_KHR_win32_surface.
    // QVulkanInstance::surfaceForWindow supplies the surface; device.c still sees only VkSurfaceKHR and pixel size.
    else if (platform == QLatin1String("windows")) exts << "VK_KHR_win32_surface";
    if (qEnvironmentVariableIsSet("BDSP_VK_VALIDATION")) exts << "VK_EXT_debug_utils";
    qvi.setExtensions(exts);
    if (!qvi.create()) {
        std::fprintf(stderr, "FATAL: QVulkanInstance::create failed (platform %s)\n", platform.toUtf8().constData());
        return 1;
    }
    vk_host_attach_instance(qvi.vkInstance());

    Host host;
    KeyForwarder keys(&host);
    app.installEventFilter(&keys);
    RenderWindow rw;
    rw.setVulkanInstance(&qvi);
    host.resize(1280, 760);
    host.embed(&rw);
    host.show();
    for (int i = 0; i < 20; i++) QCoreApplication::processEvents(QEventLoop::AllEvents, 10);
    host.applyDefaultSize();
    for (int i = 0; i < 300 && !rw.handle(); i++) {  // Wait for Qt to create the platform window for the surface.
        QCoreApplication::processEvents(QEventLoop::AllEvents, 10);
        if (i == 100) rw.create();
    }
    VkSurfaceKHR surface = QVulkanInstance::surfaceForWindow(&rw);
    if (!surface) {
        std::fprintf(stderr, "FATAL: Qt window supplied no VkSurfaceKHR (platform %s)\n", platform.toUtf8().constData());
        return 1;
    }
    rw.publishSize();
    out(QStringLiteral("[qt] Vulkan surface ready, pixels %1x%2").arg(qRound(rw.width() * rw.devicePixelRatio())).arg(qRound(rw.height() * rw.devicePixelRatio())));
    vk_host_surface_ready(reinterpret_cast<unsigned long long>(surface));
    const QString script = qEnvironmentVariable("BDSP_QT_SCRIPT");
    if (!script.isEmpty()) host.runScript(script);
    app.exec();
    std::fflush(nullptr);
    _exit(0);
}
