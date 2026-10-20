// Qt-Hülle für BDSP unter Linux (C++/Qt6 Widgets): Menüleiste wie die Mac-App (rt-bdsp/app/app_ui.m), der Vulkan-Canvas als Kind-Fenster darunter.
// Portierung der früheren Python-Fassung (gleiches Verhalten, im Lauf gegen sie geprüft). Der Spielprozess (bdsp_boot_vk) läuft mit BDSP_EMBED=1 und SDL_VIDEODRIVER=x11: er legt ein
// randloses X11-Fenster an, meldet dessen Kennung ("[embed] xid=N") und nimmt Befehle auf stdin ("fps 30|60|120", "pause 0|1") an. Das Fenster wird
// mit QWindow::fromWinId eingebettet (nur öffentliche Qt-API). Nur Linux; der Mac-Pfad (app_ui.m) bleibt unberührt.
//
// Aufruf: bdsp_qt_host [--game PFAD] [-- Argumente des Spiels]
// Umgebung: BDSP_LANG=de_DE|en_GB|... (überschreibt LC_ALL/LC_MESSAGES/LANG), BDSP_LPROJ=<Ordner> (Übersetzungen), BDSP_MANGOHUD=1 (Overlay beim Start an),
//           BDSP_QT_SCRIPT="Sekunde:aktion,..." (Testläufe: fps30 fps60 fps120 size1920x1080 win1000x900 pause fullscreen hud grab spectacle dumpmenus
//           menufps menudebug menuclose quit), BDSP_FPS, BDSP_SAVE.
#include <QAction>
#include <QActionGroup>
#include <QApplication>
#include <QCloseEvent>
#include <QCoreApplication>
#include <QDateTime>
#include <QDesktopServices>
#include <QDir>
#include <QFile>
#include <QFileDialog>
#include <QFileInfo>
#include <QKeySequence>
#include <QMainWindow>
#include <QMenu>
#include <QMenuBar>
#include <QMessageBox>
#include <QPalette>
#include <QProcess>
#include <QProcessEnvironment>
#include <QResizeEvent>
#include <QScreen>
#include <QStandardPaths>
#include <QTimer>
#include <QUrl>
#include <QWidget>
#include <QWindow>
#include <cstdio>
#include <cstdlib>
#include <functional>

#include "bdsp_l10n.h"

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

QString fillSize(QString s, int w, int h) {  // "%d × %d" wie die Mac-Texte
    for (int v : {w, h}) {
        const int i = s.indexOf(QStringLiteral("%d"));
        if (i >= 0) s.replace(i, 2, QString::number(v));
    }
    return s;
}

// Schwarze Fläche unter der Menüleiste: der Canvas bleibt 16:9, zentriert und wird nie gestreckt (Rest schwarz). Maße in logischen Pixeln;
// Qt rechnet mit devicePixelRatio (z. B. 1,7 bei 170 %) in die Pixel des X11-Fensters um.
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
    void clearCanvas() { canvas = nullptr; }

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
    Host(const QString &game, const QStringList &gameArgs)
        : game_(game), gameArgs_(gameArgs), tr_(bdsp::Translator(localeName(), lprojDir())) {
        stage_ = new Stage(this);
        setCentralWidget(stage_);
        setWindowTitle(QStringLiteral("BDSP"));
        fps_ = qEnvironmentVariableIntValue("BDSP_FPS");
        if (fps_ != 30 && fps_ != 120) fps_ = 60;
        const QString rt = qEnvironmentVariable("XDG_RUNTIME_DIR");
        hudConf_ = (rt.isEmpty() ? QDir::homePath() : rt) + QStringLiteral("/bdsp-mangohud.conf");
        hudOn_ = qEnvironmentVariable("BDSP_MANGOHUD") == QLatin1String("1");  // Standard aus; im Menü (Ansicht > Debug) im Lauf umschaltbar
        writeHudConf(hudOn_);
        buildMenus();
        hudAct_->setChecked(hudOn_);
        startGame();
    }

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
        restarting_ = true;
        if (proc_ && proc_->state() == QProcess::Running) {
            proc_->kill();
            proc_->waitForFinished(2000);
        }
        e->accept();
    }

private:
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

    // Struktur und Texte nach app_ui.m; Inhalt der Mac-Menüs "Spiel" und "BDSP" steht im Menü Datei (Bearbeiten gibt es am Mac nicht)
    void buildMenus() {
        QMenuBar *bar = menuBar();
        QMenu *m = bar->addMenu(tr_("Datei"));
        act(m, tr_("Spielstand-Ordner öffnen"), [this] { openSave(); }, "Ctrl+O");
        act(m, tr_("Spielstand importieren …"), [this] { importSave(); }, "Ctrl+I");
        m->addSeparator();
        pauseAct_ = act(m, tr_("Pause"), [this] { togglePause(); }, "Ctrl+P", true);
        act(m, tr_("Neustart"), [this] { restartGame(); }, "Ctrl+R");
        act(m, tr_("Spiel zurücksetzen …"), [this] { resetSave(); }, "Ctrl+Shift+R");
        m->addSeparator();
        act(m, tr_("BDSP beenden"), [this] { close(); }, "Ctrl+Q");

        m = viewMenu_ = bar->addMenu(tr_("Ansicht"));
        fullAct_ = act(m, tr_("Vollbild"), [this] { toggleFullscreen(); }, "Ctrl+F", true);
        fpsMenu_ = m->addMenu(tr_("Bildrate"));
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
            act(m, fillSize(tr_("Fenstergröße %d × %d"), w, h), [this, w, h] { setSize(w, h); }, key.constData());
        }
        m->addSeparator();
        debugMenu_ = m->addMenu(tr_("Debug"));
        hudAct_ = act(debugMenu_, tr_("MangoHud anzeigen"), [this] { toggleHud(); }, nullptr, true);
        hudAct_->setEnabled(!QStandardPaths::findExecutable(QStringLiteral("mangohud")).isEmpty());

        m = bar->addMenu(tr_("Fenster"));
        act(m, tr_("Minimieren"), [this] { showMinimized(); }, "Ctrl+M");

        m = bar->addMenu(tr_("Hilfe"));
        act(m, tr_("Tastenbelegung …"), [this] { showKeys(); });
        act(m, tr_("Cache-Ordner öffnen (Shader, Bilder)"), [this] { openCache(); });
        act(m, tr_("Log-Ordner öffnen"), [this] { openLogs(); });
    }

    // ---------------------------------------------------------------- Spielprozess
    void startGame() {
        QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
        env.insert(QStringLiteral("SDL_VIDEODRIVER"), QStringLiteral("x11"));
        env.insert(QStringLiteral("BDSP_EMBED"), QStringLiteral("1"));
        env.insert(QStringLiteral("BDSP_FPS"), QString::number(fps_));
        if (!QStandardPaths::findExecutable(QStringLiteral("mangohud")).isEmpty()) {
            env.insert(QStringLiteral("BDSP_MANGOHUD"), QStringLiteral("1"));
            env.insert(QStringLiteral("MANGOHUD_CONFIGFILE"), hudConf_);
        }
        proc_ = new QProcess(this);
        proc_->setProcessEnvironment(env);
        proc_->setProcessChannelMode(QProcess::MergedChannels);
        connect(proc_, &QProcess::readyRead, this, [this] { onOutput(); });
        connect(proc_, QOverload<int, QProcess::ExitStatus>::of(&QProcess::finished), this, [this](int code, QProcess::ExitStatus) {
            out(QStringLiteral("[qt] Spiel beendet, Code %1").arg(code));
            if (!restarting_) QApplication::quit();
        });
        buf_.clear();
        proc_->start(game_, gameArgs_);
    }

    void onOutput() {
        buf_ += proc_->readAll();
        int nl;
        while ((nl = buf_.indexOf('\n')) >= 0) {
            const QString line = QString::fromUtf8(buf_.left(nl));
            buf_.remove(0, nl + 1);
            out(line);
            if (line.startsWith(QStringLiteral("[embed] xid=")) && !container_) embed(line.mid(12).toULongLong());
        }
    }

    void embed(WId xid) {
        QWindow *win = QWindow::fromWinId(xid);
        container_ = QWidget::createWindowContainer(win, stage_);
        container_->setFocusPolicy(Qt::StrongFocus);
        stage_->setCanvas(container_);
        setSize(kSizes[1][0], kSizes[1][1]);
        container_->setFocus();
        out(QStringLiteral("[qt] eingebettet xid=%1").arg(qulonglong(xid)));
    }

    void send(const QString &cmd) {
        if (proc_ && proc_->state() == QProcess::Running) proc_->write((cmd + QLatin1Char('\n')).toUtf8());
    }

    // ---------------------------------------------------------------- Aktionen
    void setFps(int f) {
        fps_ = f;
        if (fpsActs_.contains(f)) fpsActs_[f]->setChecked(true);
        send(QStringLiteral("fps %1").arg(f));
        out(QStringLiteral("[qt] Bildrate %1").arg(f));
    }

    void setSize(int w, int h) {  // gewünschte Canvas-Größe in logischen Pixeln; Fenster = Canvas + Menüleiste/Ränder
        if (isFullScreen()) {
            showNormal();
            fullAct_->setChecked(false);
        }
        if (!container_) return;
        resize(w + width() - stage_->width(), h + height() - stage_->height());
        QTimer::singleShot(300, this, [this] { reportCanvas(); });
    }

    void reportCanvas() {
        if (!container_) return;
        const double r = devicePixelRatioF();
        out(QStringLiteral("[qt] Canvas %1x%2 logisch, %3x%4 Pixel (devicePixelRatio %5), Stage %6x%7, Fenster %8x%9")
                .arg(container_->width()).arg(container_->height()).arg(qRound(container_->width() * r)).arg(qRound(container_->height() * r))
                .arg(r, 0, 'f', 2).arg(stage_->width()).arg(stage_->height()).arg(width()).arg(height()));
    }

    void toggleFullscreen() {
        if (isFullScreen()) showNormal(); else showFullScreen();
        fullAct_->setChecked(isFullScreen());
    }

    void togglePause() {
        paused_ = !paused_;
        pauseAct_->setChecked(paused_);
        send(QStringLiteral("pause %1").arg(paused_ ? 1 : 0));
    }

    void writeHudConf(bool shown) {  // MangoHud lädt die Konfigurationsdatei bei Änderung neu: Umschalten im Lauf ohne Neustart
        const double ratio = QApplication::primaryScreen() ? QApplication::primaryScreen()->devicePixelRatio() : 1.0;  // Schrift mit der Skalierung
        QFile f(hudConf_);
        if (!f.open(QIODevice::WriteOnly | QIODevice::Truncate)) return;
        QString s = QStringLiteral("fps\nframetime\nframe_timing=1\ncpu_stats\ngpu_stats\nfont_size=%1\nposition=top-left\n").arg(qRound(20 * ratio));
        if (!shown) s += QStringLiteral("no_display\n");
        f.write(s.toUtf8());
    }

    void toggleHud() { writeHudConf(hudAct_->isChecked()); }

    void restartGame() {
        restarting_ = true;
        proc_->kill();
        proc_->waitForFinished(3000);
        proc_->deleteLater();
        if (container_) {
            stage_->clearCanvas();
            container_->setParent(nullptr);
            container_->deleteLater();
            container_ = nullptr;
        }
        restarting_ = false;
        startGame();
    }

    QString saveDir() const {
        const QString base = qEnvironmentVariable("BDSP_SAVE");
        return QDir(base.isEmpty() ? QStringLiteral("work/recomp/save") : base).absoluteFilePath(QStringLiteral("save_1"));
    }

    void backupSave(const QString &kind) {  // wie app_save.c: der aktuelle Stand wandert vor jeder Änderung nach <Speicher>/backups/<Art>-<Zeit>
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
        QString title = tr_("Spielstand importieren …");
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
        if (QMessageBox::question(this, tr_("Spiel zurücksetzen"), tr_("RESET_CONFIRM")) != QMessageBox::Yes) return;
        backupSave(QStringLiteral("reset"));
        for (const QString &n : {QStringLiteral("SaveData.bin"), QStringLiteral("Backup.bin")}) QFile::remove(QDir(saveDir()).filePath(n));
        restartGame();
    }

    static QString dirOrHere(const char *d) { return QFileInfo(QString::fromLatin1(d)).isDir() ? QFileInfo(QString::fromLatin1(d)).absoluteFilePath() : QDir::currentPath(); }
    void openSave() { QDesktopServices::openUrl(QUrl::fromLocalFile(QDir::cleanPath(saveDir() + QStringLiteral("/..")))); }
    void openCache() { QDesktopServices::openUrl(QUrl::fromLocalFile(dirOrHere("work/recomp/cache"))); }
    void openLogs() { QDesktopServices::openUrl(QUrl::fromLocalFile(dirOrHere("work/recomp/logs"))); }
    void showKeys() { QMessageBox::information(this, tr_("Tastenbelegung"), tr_("KEYS_HELP")); }

    // ---------------------------------------------------------------- Testskript
    void dumpMenu(QMenu *menu, int indent) {
        for (QAction *x : menu->actions()) {
            if (x->isSeparator()) continue;
            const QString sc = x->shortcut().toString();
            out(QStringLiteral("[menu] %1%2%3").arg(QString(indent * 2, QLatin1Char(' ')), x->text(), sc.isEmpty() ? QString() : QStringLiteral("   [%1]").arg(sc)));
            if (x->menu()) dumpMenu(x->menu(), indent + 1);
        }
    }

    void popupView(QMenu *sub) {
        QAction *va = viewMenu_->menuAction();
        viewMenu_->popup(mapToGlobal(menuBar()->pos()) + menuBar()->actionGeometry(va).bottomLeft());
        viewMenu_->setActiveAction(sub->menuAction());
    }

    void doTest(const QString &a) {
        out(QStringLiteral("[qt] Test: %1").arg(a));
        if (a.startsWith(QStringLiteral("fps"))) {
            setFps(a.mid(3).toInt());
        } else if (a.startsWith(QStringLiteral("size"))) {
            const QStringList p = a.mid(4).split(QLatin1Char('x'));
            if (p.size() == 2) setSize(p[0].toInt(), p[1].toInt());
        } else if (a.startsWith(QStringLiteral("win"))) {  // freies Seitenverhältnis des Fensters: der Canvas muss 16:9 bleiben
            const QStringList p = a.mid(3).split(QLatin1Char('x'));
            if (p.size() == 2) resize(p[0].toInt(), p[1].toInt());
            QTimer::singleShot(300, this, [this] { reportCanvas(); });
        } else if (a == QLatin1String("pause")) {
            togglePause();
        } else if (a == QLatin1String("fullscreen")) {
            toggleFullscreen();
        } else if (a == QLatin1String("hud")) {
            hudAct_->setChecked(!hudAct_->isChecked());
            toggleHud();
        } else if (a == QLatin1String("grab")) {
            QDir().mkpath(QStringLiteral("work/recomp/shots"));
            grab().save(QStringLiteral("work/recomp/shots/qt_window.png"));
            reportCanvas();
        } else if (a == QLatin1String("dumpmenus")) {
            out(QStringLiteral("[menu] Sprache: %1").arg(tr_.locale().isEmpty() ? QStringLiteral("(keine, Rückfall en)") : tr_.locale()));
            for (QAction *x : menuBar()->actions()) {
                out(QStringLiteral("[menu] %1").arg(x->text()));
                if (x->menu()) dumpMenu(x->menu(), 1);
            }
        } else if (a == QLatin1String("menufps")) {
            popupView(fpsMenu_);
        } else if (a == QLatin1String("menudebug")) {
            popupView(debugMenu_);
        } else if (a == QLatin1String("menuclose")) {
            viewMenu_->close();
        } else if (a == QLatin1String("spectacle")) {  // Wayland-Abzug des aktiven Fensters (KDE): Xwayland-Inhalt der Vulkan-Fläche ist per X11 nicht lesbar
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
        } else if (a == QLatin1String("quit")) {
            close();
        }
    }

    QString game_;
    QStringList gameArgs_;
    bdsp::Translator tr_;
    Stage *stage_ = nullptr;
    QWidget *container_ = nullptr;
    QProcess *proc_ = nullptr;
    QByteArray buf_;
    QAction *pauseAct_ = nullptr, *fullAct_ = nullptr, *hudAct_ = nullptr;
    QMenu *viewMenu_ = nullptr, *fpsMenu_ = nullptr, *debugMenu_ = nullptr;
    QHash<int, QAction *> fpsActs_;
    QString hudConf_;
    int fps_ = 60;
    bool paused_ = false, restarting_ = false, hudOn_ = false;
};

}  // namespace

int main(int argc, char **argv) {
    if (qEnvironmentVariableIsEmpty("QT_QPA_PLATFORM")) qputenv("QT_QPA_PLATFORM", "xcb");  // Einbettung eines X11-Fensters: xcb (unter Wayland Xwayland)
    if (qEnvironmentVariableIsEmpty("XAUTHORITY")) {  // Xwayland der Sitzung: KDE/GNOME legen die Datei im Laufzeitordner an
        const QDir rt(qEnvironmentVariable("XDG_RUNTIME_DIR"));
        const QStringList c = rt.entryList({QStringLiteral("*xauth*")}, QDir::Files, QDir::Name);
        if (!c.isEmpty()) qputenv("XAUTHORITY", rt.filePath(c.first()).toUtf8());
    }
    QApplication app(argc, argv);
    QStringList args = app.arguments().mid(1);
    QString game = QStringLiteral("work/recomp/bdsp_boot_vk");
    if (args.value(0) == QLatin1String("--game") && args.size() >= 2) {
        game = args[1];
        args = args.mid(2);
    }
    if (args.value(0) == QLatin1String("--")) args.removeFirst();
    Host host(game, args);
    host.resize(1280, 760);
    host.show();
    const QString script = qEnvironmentVariable("BDSP_QT_SCRIPT");
    if (!script.isEmpty()) host.runScript(script);
    return app.exec();
}
