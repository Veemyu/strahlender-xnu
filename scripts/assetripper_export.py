#!/usr/bin/env python3
"""Automatisiert den AssetRipper-1.1.8-Export (Unity-Projekt) per HTTP-API.

Eigener Code, nur Python-Standardbibliothek. Die Endpunkte stammen aus dem
AssetRipper-Quellcode (Tag 1.1.8, WebApplicationLauncher.cs / SettingsPage):
  POST /Settings/Update   Formular: Dropdown-Werte + Checkbox-Schluessel
  POST /LoadFolder        Formular: Path=<Ordner mit exefs/ und romfs/Data>
  POST /Export/UnityProject  Formular: Path=<Ausgabeordner>

Wichtig:
- Der Export-Endpunkt LOESCHT den Zielordner rekursiv und legt ihn neu an.
  Deshalb muss das Ziel leer sein oder fehlen und innerhalb von work/ liegen.
- Checkboxen gelten nur, wenn ihr Schluessel im Formular steht; alle anderen
  werden von AssetRipper auf false gesetzt.
- Fehler werden von AssetRipper per Redirect auf "/" verschluckt, daher wird
  der Erfolg anhand des Konsolen-Logs und des Ausgabeordners geprueft.
- Start NICHT, solange Ghidra (PID 4461) laeuft; das Skript prueft das.

Aufruf (Beispiel):
  python3 scripts/assetripper_export.py --dry-run     # nur Plan anzeigen
  python3 scripts/assetripper_export.py               # echter Export
"""

import argparse
import http.client
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Gewuenschte Einstellungen (Namen aus SettingsPage.g.cs / Enum-Definitionen)
SETTINGS_FORM = [
    ("ScriptContentLevel", "Level2"),
    ("ScriptExportMode", "Hybrid"),
    ("ScriptLanguageVersion", "AutoSafe"),  # "Automatic - Safe"
    ("SpriteExportMode", "Texture2D"),      # "Texture"
    ("IgnoreStreamingAssets", ""),          # Checkbox "Skip StreamingAssets" an
]

# Zeilen, die das Konsolen-Log nach dem Laden enthalten muss
EXPECTED_LOG_LINES = [
    "ScriptContentLevel: Level2",
    "StreamingAssetsMode: Ignore",
    "ScriptExportMode: Hybrid",
    "ScriptLanguageVersion: AutoSafe",
    "SpriteExportMode: Texture2D",
]


def ghidra_running(pid):
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def post_form(port, path, fields, timeout):
    body = urllib.parse.urlencode(fields)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("POST", path, body, {"Content-Type": "application/x-www-form-urlencoded"})
        resp = conn.getresponse()
        resp.read()
        return resp.status
    finally:
        conn.close()


def wait_for_server(port, proc, seconds=60):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"AssetRipper wurde vorzeitig beendet (Code {proc.returncode}).")
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            conn.request("GET", "/")
            conn.getresponse().read()
            conn.close()
            return
        except OSError:
            time.sleep(1)
    raise SystemExit("AssetRipper-Webserver antwortet nicht.")


def read_log(path):
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return ""


def tail(text, n=25):
    return "\n".join(text.splitlines()[-n:])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ripper", default=str(REPO / "tools/AssetRipper-1.1.8/AssetRipper.GUI.Free"))
    ap.add_argument("--input", default=str(REPO / "work"), help="Ordner mit exefs/ und romfs/Data")
    ap.add_argument("--out", default=str(REPO / "work/ripper/out"), help="Zielordner (wird von AssetRipper geleert)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--ghidra-pid", type=int, default=4461)
    ap.add_argument("--min-free-gb", type=float, default=5.0)
    ap.add_argument("--dry-run", action="store_true", help="nur pruefen und Plan ausgeben")
    args = ap.parse_args()

    ripper = Path(args.ripper)
    inp = Path(args.input).resolve()
    out = Path(args.out).resolve()
    work = (REPO / "work").resolve()
    log_dir = work / "ripper"
    console_log = log_dir / "assetripper.console.log"
    app_log = log_dir / "assetripper.log"

    if not ripper.is_file():
        sys.exit(f"AssetRipper nicht gefunden: {ripper}")
    for sub in ("exefs/main", "romfs/Data/Managed/Metadata/global-metadata.dat"):
        if not (inp / sub).is_file():
            sys.exit(f"Eingabe unvollstaendig, fehlt: {inp / sub}")
    if work not in out.parents:
        sys.exit(f"Ausgabeordner muss unter {work} liegen (AssetRipper loescht ihn rekursiv).")
    if out.exists() and any(out.iterdir()):
        sys.exit(f"Ausgabeordner ist nicht leer: {out} (AssetRipper wuerde ihn loeschen).")
    free_gb = shutil.disk_usage(work).free / 1e9
    if free_gb < args.min_free_gb:
        sys.exit(f"Zu wenig freier Platz: {free_gb:.1f} GB < {args.min_free_gb} GB.")
    if ghidra_running(args.ghidra_pid):
        sys.exit(f"Ghidra (PID {args.ghidra_pid}) laeuft noch. Erst beenden, dann Export starten.")

    cmd = [str(ripper), "--port", str(args.port), "--launch-browser", "false",
           "--log", "true", "--log-path", str(app_log)]
    print("Plan:")
    print("  Start:      ", " ".join(cmd))
    print("  Einstellung:", SETTINGS_FORM)
    print("  Laden:      ", inp)
    print("  Export nach:", out / "ExportedProject")
    if args.dry_run:
        print("Dry-Run: nichts gestartet.")
        return

    log_dir.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)  # Export-Endpunkt verlangt existierenden Ordner

    with open(console_log, "w") as logf:
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT)
        try:
            wait_for_server(args.port, proc)
            print("Server bereit, setze Einstellungen ...")
            post_form(args.port, "/Settings/Update", SETTINGS_FORM, 60)

            print("Lade Eingabe (kann dauern) ...")
            post_form(args.port, "/LoadFolder", [("Path", str(inp))], 6 * 3600)
            text = read_log(console_log)
            missing = [l for l in EXPECTED_LOG_LINES if l not in text]
            if missing:
                sys.exit(f"Einstellungen laut Log nicht uebernommen: {missing}\n{tail(text)}")
            if "Finished reading files" not in text or "Finished processing assets" not in text:
                sys.exit(f"Laden/Verarbeiten nicht abgeschlossen:\n{tail(text)}")

            print("Exportiere Unity-Projekt (kann dauern) ...")
            post_form(args.port, "/Export/UnityProject", [("Path", str(out))], 6 * 3600)
            text = read_log(console_log)
            assets = out / "ExportedProject" / "Assets"
            if "Finished post-export" not in text or not assets.is_dir():
                sys.exit(f"Export fehlgeschlagen oder unvollstaendig:\n{tail(text)}")
            print(f"Fertig: {assets}")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()
