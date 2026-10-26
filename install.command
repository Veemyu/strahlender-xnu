#!/bin/bash
# Guided installer for macOS: turns your own game dump into work/builds/macos-recomp/BDSP.app.
# Start it with a double click in the Finder, or ./install.command in a terminal (--dry-run only shows what it would do).
# It checks Xcode, Homebrew and its packages, Python and the Python packages (offering to install what is missing), asks for
# your files (drag them into the window), then runs scripts/build_all.sh (stages tools, extract, recomp).
# Safe to run again: finished stages are skipped. Helpers and texts: scripts/install/ (common.sh, lang/<code>.sh).
cd "$(dirname "$0")" || exit 1
ROOT="$PWD"
# shellcheck source=scripts/install/common.sh
. "$ROOT/scripts/install/common.sh"
parse_install_args "$@"
STEP_TOTAL=6
banner
say mac_intro1; say intro_files; say mac_intro3

# ------------------------------------------------------------------ 1 Mac and Xcode
step st_mac
[ "$(uname -m)" = arm64 ] || die mac_need_arm
ok mac_arm_ok
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
if xcodebuild -version >/dev/null 2>&1; then ok mac_xcode_ok "$(xcodebuild -version 2>/dev/null | head -n 1)"
else die mac_xcode_missing; fi
if xcode-select -p >/dev/null 2>&1; then ok clt_ok
else
  warn clt_missing
  run xcode-select --install
  if [ "$INSTALL_DRY" = 0 ]; then
    printf '%s ' "$(msg clt_wait)"; read -r _
    xcode-select -p >/dev/null 2>&1 || die clt_still
  fi
fi

# ------------------------------------------------------------------ 2 Homebrew
step st_brew
# (brew is only appended to PATH: its shellenv would put Homebrew's python3 before the one the user chose)
find_brew() {
  fake_missing brew && return 1
  command -v brew >/dev/null 2>&1 && return 0
  if [ -x /opt/homebrew/bin/brew ]; then PATH="$PATH:/opt/homebrew/bin"; export PATH; return 0; fi
  return 1
}
install_homebrew() {
  local url="https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"
  if [ "$INSTALL_DRY" = 1 ]; then dry "/bin/bash -c \"\$(curl -fsSL $url)\""; return 0; fi
  command -v curl >/dev/null 2>&1 || die brew_curl
  /bin/bash -c "$(curl -fsSL "$url")"
}
if find_brew; then ok brew_ok
else
  bad brew_missing
  say brew_why1; say brew_why2
  ask_yn brew_ask || die brew_required
  install_homebrew || die brew_failed
  if [ "$INSTALL_DRY" = 0 ]; then find_brew || die brew_notfound; fi
  ok brew_ok
fi

# ------------------------------------------------------------------ 3 Homebrew packages
step st_pkgs
brew_has() { fake_missing pkg && return 1; command -v brew >/dev/null 2>&1 && brew list --formula "$1" >/dev/null 2>&1; }
MISSING=""
for p in llvm sdl3 ffmpeg pkg-config; do
  if brew_has "$p"; then ok pkg_ok "$p"; else bad pkg_missing "$p"; MISSING="$MISSING $p"; fi
done
if [ -n "$MISSING" ]; then
  say pkg_plan "$MISSING"
  ask_yn pkg_ask || die pkg_required
  # shellcheck disable=SC2086
  run brew install $MISSING || die pkg_failed
fi
if command -v brew >/dev/null 2>&1 && brew_has llvm; then PATH="$(brew --prefix llvm)/bin:$PATH"; export PATH; fi   # the recompiler needs Homebrew's clang first

# ------------------------------------------------------------------ 4 Python
step st_python
if python_ok; then ok py_ok "$(python3 --version 2>&1 | cut -d' ' -f2)"
else
  bad py_missing
  ask_yn py_ask || die py_required
  run brew install python || die py_brew_failed
  if [ "$INSTALL_DRY" = 0 ]; then
    PATH="$(brew --prefix python)/bin:$PATH"; export PATH
    python_ok || die py_notfound
  fi
fi
use_venv || die venv_failed
for pair in lz4:lz4 unicorn:unicorn==2.1.4 PIL:Pillow; do
  venv_pip "${pair%%:*}" "${pair##*:}" || die pip_failed
done
check_space 60
printf '\n'; say gate_start
GATE_LOG="$(mktemp "${TMPDIR:-/tmp}/bdsp-preflight.XXXXXX")"
if scripts/build_all.sh preflight --only tools,extract,recomp --target macos --min-free-gb "$MINFREE" >"$GATE_LOG" 2>&1; then
  ok gate_ok
else
  cat "$GATE_LOG"
  if [ "$INSTALL_DRY" = 0 ]; then rm -f "$GATE_LOG"; die gate_fail; fi
fi
rm -f "$GATE_LOG"

# ------------------------------------------------------------------ 5 files
step st_files
ask_game_files "$HOME/.switch/prod.keys" "$HOME/Library/Application Support/Ryujinx/system/prod.keys" \
               "$HOME/Library/Application Support/yuzu/keys/prod.keys" "$HOME/.local/share/yuzu/keys/prod.keys"
build_input_args
APP="$ROOT/work/builds/macos-recomp/BDSP.app"
confirm_build "$APP" mac_build_ask

# ------------------------------------------------------------------ 6 build
step st_build
say mac_build_steps
run scripts/build_all.sh --only tools,extract,recomp --target macos "${INPUT_ARGS[@]}" --min-free-gb "$MINFREE"
RC=$?
if [ "$RC" -ne 0 ]; then
  printf '\n'; bad build_failed "$RC"; say rerun_hint
  finish "$RC"
fi
if [ "$INSTALL_DRY" = 1 ]; then finish 0; fi
[ -d "$APP" ] || die app_missing "$APP"
printf '\n%s%s%s\n  %s\n' "$G" "$(msg done_app)" "$N" "$APP"
say tip_fps
if ask_yn start_ask; then open "$APP"; fi
finish 0
