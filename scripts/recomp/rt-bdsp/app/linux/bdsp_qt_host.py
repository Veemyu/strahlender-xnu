#!/usr/bin/env python3
"""Qt-Hülle für BDSP unter Linux: Menüleiste wie die Mac-App (rt-bdsp/app/app_ui.m), der Vulkan-Canvas als Kind-Fenster darunter.

Der Spielprozess (bdsp_boot_vk) läuft mit BDSP_EMBED=1 und SDL_VIDEODRIVER=x11: er legt ein randloses X11-Fenster an, meldet dessen Kennung
("[embed] xid=N") und nimmt Befehle auf stdin ("fps 30|60|120", "pause 0|1"). Das Fenster wird hier mit QWindow.fromWinId eingebettet.
Nur Linux; der Mac-Pfad (app_ui.m) bleibt unberührt. Abhängigkeit: PySide6 (Qt 6) mit xcb-Plugin, unter Wayland also Xwayland.

Aufruf: bdsp_qt_host.py [--game PFAD] [-- Argumente des Spiels]
Umgebung: BDSP_LANG=de|en (Menüsprache, sonst Systemsprache), BDSP_QT_SCRIPT="Sekunde:aktion,..." (Testläufe: fps30, fps60, fps120, size1920x1080,
grab, pause, fullscreen, hud, quit), BDSP_FPS/BDSP_WINDOW wie beim Spiel.
"""
import glob
import os
import shutil
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
if "XAUTHORITY" not in os.environ:  # Xwayland der Sitzung (GNOME legt die Datei im Laufzeitordner an)
    cands = sorted(glob.glob(os.path.join(os.environ.get("XDG_RUNTIME_DIR", ""), "*xauth*")))
    if cands:
        os.environ["XAUTHORITY"] = cands[0]

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence, QWindow  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox, QWidget  # noqa: E402

SIZES = [(960, 540), (1280, 720), (1920, 1080), (2560, 1440)]
FPS = (30, 60, 120)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bdsp_l10n  # noqa: E402

# Menütexte aus lproj/<Ort>.lproj/Localizable.strings (Schlüssel = deutsche Mac-Texte); LANG/LC_ALL, BDSP_LANG überschreibt (z. B. en_GB), Rückfall en
tr = bdsp_l10n.Translator(os.environ.get("BDSP_LANG") or None)


class Stage(QWidget):
    """Schwarze Fläche unter der Menüleiste: der Canvas bleibt 16:9, zentriert und wird nie gestreckt (Rest schwarz)."""

    ASPECT = 16 / 9

    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = None
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), Qt.black)
        self.setPalette(pal)
        self.setMinimumSize(320, 180)

    def set_canvas(self, w):
        self.canvas = w
        w.setParent(self)
        w.show()
        self.layout_canvas()

    def canvas_rect(self):
        W, H = self.width(), self.height()  # logische Pixel; Qt rechnet mit devicePixelRatio in Geräte-Pixel des X11-Fensters um
        w = min(W, int(H * self.ASPECT))
        h = int(w / self.ASPECT)
        return (W - w) // 2, (H - h) // 2, w, h

    def layout_canvas(self):
        if self.canvas is not None:
            x, y, w, h = self.canvas_rect()
            self.canvas.setGeometry(x, y, w, h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.layout_canvas()


class Host(QMainWindow):
    def __init__(self, game, game_args):
        super().__init__()
        self.game, self.game_args = game, game_args
        self.proc = None
        self.container = None
        self.stage = Stage(self)
        self.setCentralWidget(self.stage)
        self.paused = False
        self.restarting = False
        self.fps = int(os.environ.get("BDSP_FPS", "60"))
        self.setWindowTitle("BDSP")
        self.hud_conf = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or os.path.expanduser("~"), "bdsp-mangohud.conf")
        self.hud_on = os.environ.get("BDSP_MANGOHUD", "0") == "1"  # Standard aus; im Menü (Ansicht > Debug) im Lauf umschaltbar
        self.write_hud_conf(self.hud_on)
        self.build_menus()
        self.hud_act.setChecked(self.hud_on)
        self.start_game()

    # ---------------------------------------------------------------- Menüs
    def act(self, menu, title, slot, key=None, checkable=False, group=None):
        a = QAction(title, self)
        if key:
            a.setShortcut(QKeySequence(key))
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        if group:
            group.addAction(a)
        menu.addAction(a)
        return a

    def build_menus(self):
        bar = self.menuBar()
        m = bar.addMenu(tr("Datei"))  # Inhalt der Mac-Menüs "Spiel" und "BDSP" (Spielstand, Pause, Neustart, Beenden)
        self.act(m, tr("Spielstand-Ordner öffnen"), self.open_save, "Ctrl+O")
        self.act(m, tr("Spielstand importieren …"), self.import_save, "Ctrl+I")
        m.addSeparator()
        self.pause_act = self.act(m, tr("Pause"), self.toggle_pause, "Ctrl+P", checkable=True)
        self.act(m, tr("Neustart"), self.restart_game, "Ctrl+R")
        self.act(m, tr("Spiel zurücksetzen …"), self.reset_save, "Ctrl+Shift+R")
        m.addSeparator()
        self.act(m, tr("BDSP beenden"), self.close, "Ctrl+Q")
        m = bar.addMenu(tr("Ansicht"))
        self.full_act = self.act(m, tr("Vollbild"), self.toggle_fullscreen, "Ctrl+F", checkable=True)
        self.view_menu = m
        fm = self.fps_menu = m.addMenu(tr("Bildrate"))
        grp = QActionGroup(self)
        grp.setExclusive(True)
        self.fps_acts = {}
        for f in FPS:
            a = self.act(fm, "%d fps" % f, lambda _=False, f=f: self.set_fps(f), checkable=True, group=grp)
            a.setChecked(f == self.fps)
            self.fps_acts[f] = a
        m.addSeparator()
        for i, (w, h) in enumerate(SIZES):
            self.act(m, tr("Fenstergröße %d × %d") % (w, h), lambda _=False, w=w, h=h: self.set_size(w, h), "Ctrl+%d" % (i + 1))
        m.addSeparator()
        dm = self.debug_menu = m.addMenu(tr("Debug"))
        self.hud_act = self.act(dm, tr("MangoHud anzeigen"), self.toggle_hud, checkable=True)
        self.hud_act.setEnabled(shutil.which("mangohud") is not None)
        m = bar.addMenu(tr("Fenster"))
        self.act(m, tr("Minimieren"), self.showMinimized, "Ctrl+M")
        m = bar.addMenu(tr("Hilfe"))
        self.act(m, tr("Tastenbelegung …"), self.show_keys)
        self.act(m, tr("Cache-Ordner öffnen (Shader, Bilder)"), self.open_cache)
        self.act(m, tr("Log-Ordner öffnen"), self.open_logs)

    # ---------------------------------------------------------------- Spielprozess
    def start_game(self):
        env = QProcessEnvironment.systemEnvironment()
        env.insert("SDL_VIDEODRIVER", "x11")
        env.insert("BDSP_EMBED", "1")
        env.insert("BDSP_FPS", str(self.fps))
        if shutil.which("mangohud"):
            env.insert("BDSP_MANGOHUD", "1")
            env.insert("MANGOHUD_CONFIGFILE", self.hud_conf)
        self.proc = QProcess(self)
        self.proc.setProcessEnvironment(env)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyRead.connect(self.on_output)
        self.proc.finished.connect(self.on_finished)
        self.buf = b""
        self.proc.start(self.game, self.game_args)

    def on_output(self):
        self.buf += bytes(self.proc.readAll())
        *lines, self.buf = self.buf.split(b"\n")
        for raw in lines:
            line = raw.decode("utf-8", "replace")
            print(line, flush=True)
            if line.startswith("[embed] xid=") and self.container is None:
                self.embed(int(line.split("=")[1]))

    def embed(self, xid):
        win = QWindow.fromWinId(xid)
        self.container = QWidget.createWindowContainer(win, self.stage)
        self.container.setFocusPolicy(Qt.StrongFocus)
        self.stage.set_canvas(self.container)
        self.set_size(*SIZES[1])
        self.container.setFocus()
        print("[qt] eingebettet xid=%d" % xid, flush=True)

    def on_finished(self, code, _status):
        print("[qt] Spiel beendet, Code %d" % code, flush=True)
        if not self.restarting:
            QApplication.quit()

    def send(self, cmd):
        if self.proc and self.proc.state() == QProcess.Running:
            self.proc.write((cmd + "\n").encode())

    # ---------------------------------------------------------------- Aktionen
    def set_fps(self, f):
        self.fps = f
        self.fps_acts[f].setChecked(True)
        self.send("fps %d" % f)
        print("[qt] Bildrate %d" % f, flush=True)

    def set_size(self, w, h):
        if self.isFullScreen():
            self.showNormal()
            self.full_act.setChecked(False)
        if self.container is None:
            return
        # Fenstergröße = gewünschte Canvas-Größe (logische Pixel) + Rahmen aus Menüleiste/Rändern; devicePixelRatio (KDE/HiDPI) rechnet Qt um
        self.resize(w + self.width() - self.stage.width(), h + self.height() - self.stage.height())
        QTimer.singleShot(300, self.report_canvas)

    def report_canvas(self):
        if self.container is None:
            return
        r = self.devicePixelRatioF()
        print("[qt] Canvas %dx%d logisch, %dx%d Pixel (devicePixelRatio %.2f), Stage %dx%d, Fenster %dx%d" % (
            self.container.width(), self.container.height(), round(self.container.width() * r), round(self.container.height() * r), r,
            self.stage.width(), self.stage.height(), self.width(), self.height()), flush=True)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        self.full_act.setChecked(self.isFullScreen())

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_act.setChecked(self.paused)
        self.send("pause %d" % self.paused)

    def write_hud_conf(self, shown):
        ratio = QApplication.primaryScreen().devicePixelRatio()  # MangoHud zeichnet in Gerätepixeln des Canvas: Schrift mit der Skalierung (z. B. 170 %) vergrößern
        with open(self.hud_conf, "w") as f:
            f.write("fps\nframetime\nframe_timing=1\ncpu_stats\ngpu_stats\nfont_size=%d\nposition=top-left\n" % round(20 * ratio))
            if not shown:
                f.write("no_display\n")

    def toggle_hud(self):
        self.write_hud_conf(self.hud_act.isChecked())  # MangoHud lädt die Konfigurationsdatei bei Änderung neu

    def restart_game(self):
        self.restarting = True
        self.proc.kill()
        self.proc.waitForFinished(3000)
        if self.container is not None:
            self.stage.canvas = None
            self.container.setParent(None)
            self.container.deleteLater()
            self.container = None
        self.restarting = False
        self.start_game()

    def open_save(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(os.environ.get("BDSP_SAVE", "work/recomp/save"))))

    def open_cache(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath("work/recomp/cache" if os.path.isdir("work/recomp/cache") else ".")))

    def save_dir(self):
        return os.path.abspath(os.path.join(os.environ.get("BDSP_SAVE", "work/recomp/save"), "save_1"))

    def backup_save(self, kind):  # wie app_save.c: der aktuelle Stand wandert vor jeder Änderung nach <Speicher>/backups/<Art>-<Zeit>
        sd = self.save_dir()
        files = [f for f in ("SaveData.bin", "Backup.bin") if os.path.isfile(os.path.join(sd, f))]
        if files:
            bd = os.path.join(os.path.dirname(sd), "backups", "%s-%s" % (kind, time.strftime("%Y%m%d-%H%M%S")))
            os.makedirs(bd, exist_ok=True)
            for f in files:
                shutil.copy2(os.path.join(sd, f), bd)

    def import_save(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Spielstand importieren …").rstrip(" …"), "", "SaveData.bin (SaveData.bin);;*")
        if not path:
            return
        src = os.path.dirname(path)
        self.backup_save("import")
        sd = self.save_dir()
        os.makedirs(sd, exist_ok=True)
        for f in ("SaveData.bin", "Backup.bin"):
            if os.path.isfile(os.path.join(src, f)):
                shutil.copy2(os.path.join(src, f), os.path.join(sd, f))
        self.restart_game()

    def reset_save(self):
        if QMessageBox.question(self, tr("Spiel zurücksetzen"), tr("RESET_CONFIRM")) != QMessageBox.Yes:
            return
        self.backup_save("reset")
        for f in ("SaveData.bin", "Backup.bin"):
            try:
                os.remove(os.path.join(self.save_dir(), f))
            except OSError:
                pass
        self.restart_game()

    def open_logs(self):
        d = "work/recomp/logs"
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(d if os.path.isdir(d) else ".")))

    def show_keys(self):
        QMessageBox.information(self, tr("Tastenbelegung"), tr("KEYS_HELP"))

    def closeEvent(self, e):
        self.restarting = True
        if self.proc and self.proc.state() == QProcess.Running:
            self.proc.kill()
            self.proc.waitForFinished(2000)
        e.accept()

    # ---------------------------------------------------------------- Testskript
    def run_script(self, spec):
        for tok in spec.split(","):
            t, _, action = tok.partition(":")
            QTimer.singleShot(int(float(t) * 1000), lambda a=action.strip(): self.do_test(a))

    def do_test(self, a):
        print("[qt] Test: %s" % a, flush=True)
        if a.startswith("fps"):
            self.set_fps(int(a[3:]))
        elif a.startswith("size"):
            w, h = a[4:].split("x")
            self.set_size(int(w), int(h))
        elif a.startswith("win"):  # Testfenster mit freiem Seitenverhältnis: der Canvas muss 16:9 bleiben
            w, h = a[3:].split("x")
            self.resize(int(w), int(h))
            QTimer.singleShot(300, self.report_canvas)
        elif a == "pause":
            self.toggle_pause()
        elif a == "fullscreen":
            self.toggle_fullscreen()
        elif a == "hud":
            self.hud_act.setChecked(not self.hud_act.isChecked())
            self.toggle_hud()
        elif a == "dumpmenus":  # Menütexte ins Log (Prüfung der Lokalisierung)
            def walk(menu, indent):
                for x in menu.actions():
                    if x.isSeparator():
                        continue
                    print("[menu] %s%s%s" % ("  " * indent, x.text(), ("   [%s]" % x.shortcut().toString()) if x.shortcut().toString() else ""), flush=True)
                    if x.menu():
                        walk(x.menu(), indent + 1)
            print("[menu] Sprache: %s" % (tr.locale or "(keine, Rückfall en)"), flush=True)
            walk(self.menuBar(), 0)
        elif a in ("menufps", "menudebug"):  # Menü aufklappen (Prüfung der Struktur im Abzug)
            sub = self.fps_menu if a == "menufps" else self.debug_menu
            self.view_menu.popup(self.mapToGlobal(self.menuBar().pos()) + self.menuBar().actionGeometry(self.view_menu.menuAction()).bottomLeft())
            self.view_menu.setActiveAction(sub.menuAction())
        elif a == "menuclose":
            self.view_menu.close()
        elif a == "spectacle":  # Wayland-Abzug des aktiven Fensters (KDE): Xwayland-Inhalt der Vulkan-Fläche ist per X11 nicht lesbar
            env = QProcessEnvironment.systemEnvironment()
            rt = os.environ.get("XDG_RUNTIME_DIR", "")
            env.insert("DBUS_SESSION_BUS_ADDRESS", "unix:path=%s/bus" % rt)
            env.insert("WAYLAND_DISPLAY", os.environ.get("BDSP_WAYLAND_DISPLAY", "wayland-0"))
            env.remove("QT_QPA_PLATFORM")
            p = QProcess(self)
            p.setProcessEnvironment(env)
            os.makedirs("work/recomp/shots", exist_ok=True)
            p.start("spectacle", ["-b", "-n", "-a", "-o", os.path.abspath("work/recomp/shots/qt_spectacle.png")])
        elif a == "grab":
            os.makedirs("work/recomp/shots", exist_ok=True)
            self.grab().save("work/recomp/shots/qt_window.png")
            scr = QApplication.primaryScreen()  # Bildschirm-Abzug der X11-Fenster (zeigt Vulkan-Canvas samt Overlay, falls Xwayland ihn liefert)
            scr.grabWindow(self.winId()).save("work/recomp/shots/qt_screen_window.png")
            if self.container is not None:
                scr.grabWindow(self.container.winId()).save("work/recomp/shots/qt_screen_canvas.png")
            self.report_canvas()
        elif a == "quit":
            self.close()


def main():
    argv = sys.argv[1:]
    game = "work/recomp/bdsp_boot_vk"
    if argv[:1] == ["--game"]:
        game, argv = argv[1], argv[2:]
    if argv[:1] == ["--"]:
        argv = argv[1:]
    app = QApplication(sys.argv[:1])
    host = Host(game, argv)
    host.resize(1280, 760)
    host.show()
    if os.environ.get("BDSP_QT_SCRIPT"):
        host.run_script(os.environ["BDSP_QT_SCRIPT"])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
