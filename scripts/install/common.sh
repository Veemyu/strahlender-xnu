#!/bin/bash
# Shared helpers of the guided installers (install.command for macOS, install-linux.sh for Linux). Sourced, never run alone.
# bash 3.2 compatible (the macOS system bash): no associative arrays, no ${var,,}, no mapfile.
# The caller sets ROOT (repository root) and may set INSTALL_DRY=1 (--dry-run: show what would be installed or run, change nothing).
#
# Texts live in scripts/install/lang/<code>.sh as M_<key>='printf format'. English (en.sh) is complete and is the fallback for
# every key a translation lacks. Language: BDSP_LANG=<de|en|es|pt>, else the system language (LC_ALL / LANG), else English.
# To add a language: copy en.sh to <code>.sh, translate the values, add the code to the case below and to ask_yn.
#
# Test hooks (harmless otherwise):
#   BDSP_INSTALL_FAKE_MISSING=pkg,python,venv,pip,brew   report these checks as failed even if they pass
INSTALL_DRY="${INSTALL_DRY:-0}"
case "${BDSP_LANG:-${LC_ALL:-${LANG:-en}}}" in de*) L=de ;; es*) L=es ;; pt*) L=pt ;; *) L=en ;; esac
# shellcheck source=/dev/null
. "$ROOT/scripts/install/lang/en.sh"
if [ "$L" != en ]; then . "$ROOT/scripts/install/lang/$L.sh"; fi
if [ -t 1 ]; then B=$'\033[1m'; G=$'\033[32m'; R=$'\033[31m'; Y=$'\033[33m'; N=$'\033[0m'; else B=; G=; R=; Y=; N=; fi

# msg <key> [printf args...]: the text of a key (the key itself if it is unknown)
msg() { local key="$1" k="M_$1" f; f="${!k:-$key}"; shift; printf -- "$f" "$@"; }
say() { msg "$@"; printf '\n'; }
ok() { printf '  %s✔%s %s\n' "$G" "$N" "$(msg "$@")"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$(msg "$@")"; }
bad() { printf '  %s✘%s %s\n' "$R" "$N" "$(msg "$@")"; }
dry() { printf '  %s[dry-run]%s %s\n' "$Y" "$N" "$*"; }
STEP_TOTAL=6; STEP_N=0
step() { STEP_N=$((STEP_N + 1)); printf '\n%s== %s/%s  %s ==%s\n' "$B" "$STEP_N" "$STEP_TOTAL" "$(msg "$1")" "$N"; }
finish() {
  local _x
  printf '\n'
  if [ -t 0 ] && [ "$INSTALL_DRY" = 0 ]; then printf '%s ' "$(msg press_enter_close)"; read -r _x; fi
  exit "${1:-0}"
}
die() { printf '\n%s%s%s\n' "$R" "$(msg "$@")" "$N"; finish 1; }

fake_missing() { case ",${BDSP_INSTALL_FAKE_MISSING:-}," in *",$1,"*) return 0 ;; esac; return 1; }

# Runs a command, or only shows it with --dry-run (returns success then).
run() {
  if [ "$INSTALL_DRY" = 1 ]; then dry "$*"; return 0; fi
  "$@"
}

# ask_yn <key> [args...]: yes/no question, Enter = yes. With --dry-run it shows the question and answers yes.
ask_yn() {
  local a
  if [ "$INSTALL_DRY" = 1 ]; then dry "$(msg "$@") -> $(msg yes_word)"; return 0; fi
  printf '%s [%s] ' "$(msg "$@")" "$(msg yes_no)"
  read -r a || exit 1
  case "$a" in n|N|nein|Nein|no|No|não|Não|nao|Nao) return 1 ;; *) return 0 ;; esac
}

# A path typed or dragged into the terminal: strip quotes, backslash escapes, blanks, file:// and a leading ~
clean_path() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"; s="${s%"${s##*[![:space:]]}"}"
  case "$s" in \'*\') s="${s#\'}"; s="${s%\'}" ;; \"*\") s="${s#\"}"; s="${s%\"}" ;; esac
  s="$(printf '%s' "$s" | sed -e 's/\\\(.\)/\1/g')"
  case "$s" in "~/"*) s="$HOME/${s#"~/"}" ;; file://*) s="${s#file://}" ;; esac
  printf '%s' "$s"
}

# ask_file <extension> <required 1|0> <prompt key>   -> sets ANSWER (empty if optional and skipped)
ask_file() {
  local ext="$1" req="$2" key="$3" raw p
  if [ "$INSTALL_DRY" = 1 ]; then
    if [ "$req" = 1 ]; then ANSWER="<$ext>"; else ANSWER=""; fi
    dry "$(msg "$key")"; return
  fi
  while true; do
    printf '\n%s\n> ' "$(msg "$key")"
    read -r raw || exit 1
    p="$(clean_path "$raw")"
    if [ -z "$p" ]; then
      if [ "$req" = 0 ]; then ANSWER=""; return; fi
      bad file_drag_required; continue
    fi
    if [ ! -f "$p" ]; then bad file_not_found "$p"; continue; fi
    case "$(printf '%s' "$p" | tr '[:upper:]' '[:lower:]')" in *."$ext") ;; *) bad file_wrong_ext "$ext"; continue ;; esac
    ANSWER="$p"; printf '  %s✔%s %s\n' "$G" "$N" "$(basename "$p")"; return
  done
}

# Asks for the three inputs (XCI, optional NSP, prod.keys). The key file locations given as arguments (fixed, well-known paths,
# no searching) are offered first. Sets XCI NSP KEYS TITLE_KEYS.
ask_game_files() {
  local k
  ask_file xci 1 ask_xci
  XCI="$ANSWER"
  ask_file nsp 0 ask_nsp
  NSP="$ANSWER"
  KEYS=""
  for k in "$@"; do
    [ -f "$k" ] || continue
    printf '\n'; say key_found "$k"
    if ask_yn key_use; then KEYS="$k"; break; fi
  done
  if [ -z "$KEYS" ]; then ask_file keys 1 ask_keys; KEYS="$ANSWER"; fi
  TITLE_KEYS=""
  if [ "$INSTALL_DRY" = 0 ] && [ -f "$(dirname "$KEYS")/title.keys" ]; then
    TITLE_KEYS="$(dirname "$KEYS")/title.keys"; ok title_keys_found
  fi
}

# Arguments of scripts/build_all.sh for the inputs -> array INPUT_ARGS
build_input_args() {
  INPUT_ARGS=(--xci "$XCI")
  if [ -n "$NSP" ]; then INPUT_ARGS+=(--nsp "$NSP"); fi
  INPUT_ARGS+=(--prod-keys "$KEYS")
  if [ -n "$TITLE_KEYS" ]; then INPUT_ARGS+=(--title-keys "$TITLE_KEYS"); fi
}

# The summary of the inputs, then the "build now?" question (key given by the caller)
confirm_build() {
  printf '\n'
  say sum_game "$XCI"
  if [ -n "$NSP" ]; then say sum_update "$NSP"; fi
  say sum_keys "$KEYS"
  [ -n "$1" ] && say sum_result "$1"
  printf '\n'
  ask_yn "$2" || die cancelled
}

# python3 present and >= 3.9?
python_ok() {
  fake_missing python && return 1
  command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1
}

# Own virtual environment work/venv: pip installs there need no administrator rights and never touch the system Python
# (Homebrew and many Linux distributions refuse a plain "pip install"). Puts it first on PATH, so every script run from
# here on (build_all.sh, the Linux build scripts) uses it.
use_venv() {
  local v="$ROOT/work/venv"
  if [ ! -x "$v/bin/python3" ] || fake_missing venv; then
    say venv_creating
    run python3 -m venv "$v" || return 1
  fi
  if [ "$INSTALL_DRY" = 0 ]; then PATH="$v/bin:$PATH"; export PATH; fi
}

# venv_pip <import name> <pip name>: install a package into the venv unless it imports already
venv_pip() {
  local mod="$1" pkg="$2"
  if ! fake_missing pip && python3 -c "import $mod" >/dev/null 2>&1; then ok pip_ok "$pkg"; return 0; fi
  warn pip_missing "$pkg"
  run python3 -m pip install --quiet --disable-pip-version-check "$pkg" || return 1
}

free_gb() { df -k "$1" | awk 'NR==2 {print int($4 / 1048576)}'; }

# Free space check against the recommended minimum. Sets MINFREE (what to pass to build_all.sh --min-free-gb).
check_space() {
  local free
  free="$(free_gb "$ROOT")"; MINFREE="${1:-60}"
  if [ "$free" -ge "$MINFREE" ]; then ok space_ok "$free"; return; fi
  warn space_low "$free" "$MINFREE"
  ask_yn continue_anyway || die free_space_die
  MINFREE="$free"
}

parse_install_args() {
  local a
  for a in "$@"; do
    case "$a" in
      --dry-run) INSTALL_DRY=1 ;;
      -h|--help) say usage "$0"; exit 0 ;;
      *) printf 'Unknown option: %s\n' "$a" >&2; exit 2 ;;
    esac
  done
}

banner() {
  printf '%s\n' "${B}$(msg title)${N}"
  [ "$INSTALL_DRY" = 1 ] && printf '%s\n' "${Y}$(msg dry_banner)${N}"
  return 0
}
