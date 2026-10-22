#!/bin/bash
# Easy installer: turns your own game dump into work/builds/macos-recomp/BDSP.app.
# Start it with a double click in the Finder or with ./install.command in a terminal. It checks the tools, asks for your
# files (drag them into the window), and then runs scripts/build_all.sh (stages tools, extract, recomp).
# Nothing is installed with sudo; nothing leaves your Mac. Safe to run again: finished stages are skipped.
# Messages are German when the system language is German, otherwise English.
cd "$(dirname "$0")" || exit 1
ROOT="$PWD"
case "${LC_ALL:-${LANG:-}}" in de*) L=de ;; *) L=en ;; esac
if [ -t 1 ]; then B=$'\033[1m'; G=$'\033[32m'; R=$'\033[31m'; Y=$'\033[33m'; N=$'\033[0m'; else B=; G=; R=; Y=; N=; fi

t() { if [ "$L" = de ]; then printf '%s' "$1"; else printf '%s' "$2"; fi; }   # t "deutsch" "english"
say() { printf '%s\n' "$(t "$1" "$2")"; }
ok() { printf '  %s✔%s %s\n' "$G" "$N" "$(t "$1" "$2")"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$(t "$1" "$2")"; }
bad() { printf '  %s✘%s %s\n' "$R" "$N" "$(t "$1" "$2")"; }
step() { printf '\n%s== %s ==%s\n' "$B" "$(t "$1" "$2")" "$N"; }
finish() { printf '\n'; [ -t 0 ] && { printf '%s' "$(t 'Enter drücken zum Schließen ' 'Press Enter to close ')"; read -r _; }; exit "${1:-0}"; }
die() { printf '\n%s%s%s\n' "$R" "$(t "$1" "$2")" "$N"; finish 1; }

# yes/no question, Enter = yes
yes() { local a; printf '%s [%s] ' "$(t "$1" "$2")" "$(t 'J/n' 'Y/n')"; read -r a || exit 1; case "$a" in n|N|nein|Nein|no|No) return 1 ;; *) return 0 ;; esac; }

# A path typed or dragged into the terminal: strip quotes, backslash escapes, blanks, file:// and ~
clean_path() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"; s="${s%"${s##*[![:space:]]}"}"
  case "$s" in \'*\') s="${s#\'}"; s="${s%\'}" ;; \"*\") s="${s#\"}"; s="${s%\"}" ;; esac
  s="$(printf '%s' "$s" | sed -e 's/\\\(.\)/\1/g')"
  case "$s" in "~/"*) s="$HOME/${s#"~/"}" ;; file://*) s="${s#file://}" ;; esac
  printf '%s' "$s"
}

printf '%s\n' "${B}BDSP · $(t 'Einrichtung aus deinem eigenen Spiel-Dump' 'Setup from your own game dump')${N}"
say "Dieses Skript baut aus deiner eigenen Pokémon-Brilliant-Diamond-Datei (.xci) eine fertige BDSP.app für diesen Mac." \
    "This script builds a ready-to-play BDSP.app for this Mac from your own Pokémon Brilliant Diamond file (.xci)."
say "Du brauchst: die .xci (optional das Update als .nsp) und die Schlüsseldatei prod.keys deiner eigenen Konsole." \
    "You need: the .xci (optionally the update as .nsp) and the prod.keys file from your own console."
say "Platz: etwa 60 GB frei. Dauer: rund eine Stunde (die Übersetzung des Spiels ist der längste Teil)." \
    "Space: about 60 GB free. Time: roughly an hour (translating the game is the longest part)."
say "Dateien und Schlüssel werden nur gelesen und bleiben auf diesem Mac. Es wird nichts mit sudo installiert." \
    "Files and keys are only read and stay on this Mac. Nothing is installed with sudo."

# ---------------------------------------------------------------- 1 tools
step "1/4 Werkzeuge prüfen" "1/4 Checking tools"
[ "$(uname -m)" = arm64 ] || die "Dieser Weg braucht einen Mac mit Apple Silicon (M1 oder neuer)." "This needs a Mac with Apple Silicon (M1 or newer)."
ok "Mac mit Apple Silicon" "Apple Silicon Mac"

export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
if xcodebuild -version >/dev/null 2>&1; then ok "Xcode: $(xcodebuild -version 2>/dev/null | head -n 1)" "Xcode: $(xcodebuild -version 2>/dev/null | head -n 1)"
else die "Xcode 26 oder neuer fehlt. Bitte aus dem App Store installieren, einmal öffnen (Lizenz akzeptieren) und dieses Skript erneut starten." \
         "Xcode 26 or newer is missing. Install it from the App Store, open it once (accept the license), then run this script again."; fi

# (brew is only appended to PATH: its shellenv would put Homebrew's python3 before the one the user chose)
case ":$PATH:" in *:/opt/homebrew/bin:*) ;; *) [ -x /opt/homebrew/bin/brew ] && PATH="$PATH:/opt/homebrew/bin" ;; esac
command -v brew >/dev/null 2>&1 || die "Homebrew fehlt. Installation: https://brew.sh (der Installer fragt selbst nach deinem Passwort). Danach dieses Skript erneut starten." \
                                         "Homebrew is missing. Install it from https://brew.sh (its installer asks for your password itself), then run this script again."
ok "Homebrew" "Homebrew"

MISSING=""
for p in llvm sdl3 ffmpeg pkg-config; do
  if brew list --formula "$p" >/dev/null 2>&1; then ok "brew: $p" "brew: $p"; else bad "brew: $p fehlt" "brew: $p missing"; MISSING="$MISSING $p"; fi
done
if [ -n "$MISSING" ]; then
  yes "Fehlende Pakete jetzt mit Homebrew installieren ($MISSING )?" "Install the missing packages with Homebrew now ($MISSING )?" || die "Ohne diese Pakete geht es nicht." "These packages are required."
  # shellcheck disable=SC2086
  brew install $MISSING || die "brew install ist fehlgeschlagen (Meldung oben)." "brew install failed (see the message above)."
fi
export PATH="$(brew --prefix llvm)/bin:$PATH"   # the recompiler needs Homebrew's clang first

if [ -d tools/pydeps/capstone ] && [ -d tools/pydeps/unicorn ]; then ok "Python: capstone, unicorn" "Python: capstone, unicorn"
else
  warn "Python-Pakete capstone und unicorn werden in tools/pydeps installiert." "Installing the Python packages capstone and unicorn into tools/pydeps."
  python3 -m pip install --target tools/pydeps capstone unicorn || die "pip ist fehlgeschlagen (Meldung oben)." "pip failed (see the message above)."
fi
if python3 -c 'from PIL import Image' >/dev/null 2>&1; then ok "Python: Pillow" "Python: Pillow"
else
  warn "Pillow (für die App-Icons) wird installiert." "Installing Pillow (for the app icons)."
  if ! python3 -m pip install Pillow >/dev/null 2>&1; then
    warn "Dieses Python ist von Homebrew verwaltet und erlaubt kein normales pip." "This Python is managed by Homebrew and refuses a plain pip install."
    yes "Pillow nur für deinen Benutzer installieren (pip --user)?" "Install Pillow for your user only (pip --user)?" \
      || die "Ohne Pillow geht es nicht: python3 -m pip install --user --break-system-packages Pillow" "Pillow is required: python3 -m pip install --user --break-system-packages Pillow"
    python3 -m pip install --user --break-system-packages Pillow || die "pip ist fehlgeschlagen (Meldung oben)." "pip failed (see the message above)."
  fi
fi

FREE=$(df -k "$ROOT" | awk 'NR==2 {print int($4 / 1048576)}')
MINFREE=60
if [ "$FREE" -ge "$MINFREE" ]; then ok "Platz: $FREE GB frei" "Space: $FREE GB free"
else
  warn "Nur $FREE GB frei, empfohlen sind $MINFREE GB." "Only $FREE GB free, $MINFREE GB recommended."
  yes "Trotzdem weitermachen?" "Continue anyway?" || die "Bitte Platz schaffen und erneut starten." "Please free some space and run again."
  MINFREE="$FREE"
fi

# ---------------------------------------------------------------- 2 files
step "2/4 Deine Dateien" "2/4 Your files"
ask_file() {   # ask_file <ext> <required 1|0> <de prompt> <en prompt>  -> sets ANSWER
  local ext="$1" req="$2" raw p
  while true; do
    printf '\n%s\n> ' "$(t "$3" "$4")"
    read -r raw || exit 1
    p="$(clean_path "$raw")"
    if [ -z "$p" ]; then
      [ "$req" = 0 ] && { ANSWER=""; return; }
      bad "Bitte eine Datei hineinziehen." "Please drag a file into the window."; continue
    fi
    if [ ! -f "$p" ]; then bad "Datei nicht gefunden: $p" "File not found: $p"; continue; fi
    case "$(printf '%s' "$p" | tr '[:upper:]' '[:lower:]')" in *."$ext") ;; *) bad "Das ist keine .$ext-Datei." "That is not a .$ext file."; continue ;; esac
    ANSWER="$p"; ok "$(basename "$p")" "$(basename "$p")"; return
  done
}
ask_file xci 1 "Ziehe jetzt deine SPIEL-Datei (.xci) in dieses Fenster und drücke Enter:" \
               "Drag your GAME file (.xci) into this window and press Enter:"
XCI="$ANSWER"
ask_file nsp 0 "Optional: das UPDATE (.nsp) hineinziehen, oder nur Enter zum Überspringen:" \
               "Optional: drag the UPDATE (.nsp) here, or just press Enter to skip:"
NSP="$ANSWER"

# keys: look at the usual places of other tools first (fixed paths, no searching), else ask
KEYS=""
for k in "$HOME/.switch/prod.keys" "$HOME/Library/Application Support/Ryujinx/system/prod.keys" \
         "$HOME/Library/Application Support/yuzu/keys/prod.keys" "$HOME/.local/share/yuzu/keys/prod.keys"; do
  if [ -f "$k" ]; then
    printf '\n'; say "Schlüsseldatei gefunden: $k" "Key file found: $k"
    yes "Diese Datei verwenden?" "Use this file?" && { KEYS="$k"; break; }
  fi
done
if [ -z "$KEYS" ]; then
  while true; do
    ask_file keys 1 "Ziehe jetzt deine Schlüsseldatei (prod.keys) hinein und drücke Enter:" \
                    "Drag your key file (prod.keys) into this window and press Enter:"
    KEYS="$ANSWER"; break
  done
fi
TITLE_KEYS="$(dirname "$KEYS")/title.keys"
[ -f "$TITLE_KEYS" ] || TITLE_KEYS=""
[ -n "$TITLE_KEYS" ] && ok "title.keys gefunden" "title.keys found"

# ---------------------------------------------------------------- 3 summary
step "3/4 Zusammenfassung" "3/4 Summary"
say "  Spiel:   $XCI" "  Game:    $XCI"
[ -n "$NSP" ] && say "  Update:  $NSP" "  Update:  $NSP"
say "  Schlüssel: $KEYS" "  Keys:    $KEYS"
say "  Ergebnis: $ROOT/work/builds/macos-recomp/BDSP.app" "  Result:  $ROOT/work/builds/macos-recomp/BDSP.app"
printf '\n'
yes "Jetzt starten? (Das Fenster danach offen lassen und den Mac nicht ausschalten.)" "Start now? (Keep this window open and do not shut down the Mac.)" || die "Abgebrochen. Es wurde nichts gebaut." "Cancelled. Nothing was built."

# ---------------------------------------------------------------- 4 build
step "4/4 Bauen" "4/4 Building"
say "Schritte: Werkzeug bauen, Spiel auslesen, Code übersetzen, App zusammensetzen. Das Log liegt unter work/logs/." \
    "Steps: build the tool, read the game, translate the code, assemble the app. Logs are in work/logs/."
ARGS=(--only tools,extract,recomp --target macos --xci "$XCI" --min-free-gb "$MINFREE")
[ -n "$NSP" ] && ARGS+=(--nsp "$NSP")
ARGS+=(--prod-keys "$KEYS")
[ -n "$TITLE_KEYS" ] && ARGS+=(--title-keys "$TITLE_KEYS")
scripts/build_all.sh "${ARGS[@]}"
RC=$?
if [ "$RC" -ne 0 ]; then
  printf '\n'
  bad "Der Bau ist mit Fehlercode $RC abgebrochen. Die Meldung steht oben, die Logs unter work/logs/." \
      "The build stopped with exit code $RC. The message is above, the logs are in work/logs/."
  say "Du kannst das Skript einfach erneut starten: fertige Schritte werden übersprungen." "You can simply run this script again: finished steps are skipped."
  finish "$RC"
fi

APP="$ROOT/work/builds/macos-recomp/BDSP.app"
[ -d "$APP" ] || die "Der Bau meldet Erfolg, aber $APP fehlt." "The build reports success but $APP is missing."
printf '\n%s%s%s\n' "$G" "$(t 'Fertig! Die App liegt hier:' 'Done! The app is here:')" "$N"
printf '  %s\n' "$APP"
say "Tipp: Mit BDSP_FPS=60 (oder 30/120) vor dem Start im Terminal stellst du die Bildrate ein; siehe docs/BUILD.md." \
    "Tip: set the frame rate with BDSP_FPS=60 (or 30/120) when starting from a terminal; see docs/BUILD.md."
if yes "BDSP jetzt starten?" "Start BDSP now?"; then open "$APP"; fi
finish 0
