#!/bin/bash
# Guided installer for Linux (x86-64 with Vulkan): from your own game dump to a built Vulkan/Qt runtime (work/recomp/bdsp_boot_vk_qt).
# Run it with ./install-linux.sh (--dry-run only shows what it would do). It detects your package manager (apt, dnf or pacman),
# installs missing development packages after you agree (the package manager asks for your administrator password via sudo),
# sets up a private Python environment, asks for your files (drag them into the terminal), and runs the build.
# Safe to run again: finished stages are skipped. The Linux port is work in progress and not playable yet (docs/BUILD.md, 6.4).
# Helpers and texts: scripts/install/ (common.sh, lang/<code>.sh). Test hooks: BDSP_INSTALL_OS_RELEASE=<file> (instead of
# /etc/os-release), BDSP_INSTALL_FAKE_OS=1 (skip the Linux/CPU checks), BDSP_INSTALL_FAKE_MISSING=pkg,python,venv,pip (common.sh).
cd "$(dirname "$0")" || exit 1
ROOT="$PWD"
# shellcheck source=scripts/install/common.sh
. "$ROOT/scripts/install/common.sh"
parse_install_args "$@"
STEP_TOTAL=6
banner
say lx_intro1; say lx_intro2; say intro_files; say lx_intro3

# ------------------------------------------------------------------ 1 system
step lx_st_system
if [ -z "${BDSP_INSTALL_FAKE_OS:-}" ]; then
  [ "$(uname -s)" = Linux ] || die lx_not_linux
  [ "$(uname -m)" = x86_64 ] || die lx_not_x86
fi
ok lx_cpu_ok

OSR="${BDSP_INSTALL_OS_RELEASE:-/etc/os-release}"
OS_IDS="$( ( . "$OSR" 2>/dev/null; echo "${ID:-} ${ID_LIKE:-}" ) )"
OS_NAME="$( ( . "$OSR" 2>/dev/null; echo "${PRETTY_NAME:-Linux}" ) )"
PM=""
case "$OS_IDS" in
  *debian*|*ubuntu*) PM=apt ;;
  *fedora*|*rhel*|*centos*) PM=dnf ;;
  *arch*) PM=pacman ;;
esac
if [ -n "$PM" ]; then ok lx_distro_ok "$OS_NAME" "$PM"; else warn lx_distro_unknown "$OS_NAME"; fi

# ------------------------------------------------------------------ 2 packages
step lx_st_pkgs
MISSING_PKGS=""; AUR_NOTE=0; MISSING_LABELS=""
add_pkgs() {
  local p
  for p in "$@"; do
    [ "$p" = "-" ] && continue
    case " $MISSING_PKGS " in *" $p "*) ;; *) MISSING_PKGS="$MISSING_PKGS $p" ;; esac
  done
}
# check <label> <test result 0=ok> <apt names> <dnf names> <pacman names>    ("-" = no package for that manager)
check() {
  local label="$1" good="$2" names=""
  fake_missing pkg && good=1
  if [ "$good" = 0 ]; then ok item_ok "$label"; return 0; fi
  bad item_missing "$label"
  MISSING_LABELS="$MISSING_LABELS $label"
  case "$PM" in apt) names="$3" ;; dnf) names="$4" ;; pacman) names="$5" ;; esac
  # shellcheck disable=SC2086
  add_pkgs $names
  if [ "$names" = "-" ] && [ "$PM" = pacman ] && [ "$label" = "Vulkan Memory Allocator" ]; then AUR_NOTE=1; fi
  return 0
}
t_cmds() { local c; for c in "$@"; do command -v "$c" >/dev/null 2>&1 || return 1; done; }
t_pc() { command -v pkg-config >/dev/null 2>&1 && pkg-config --exists "$@"; }
t_vma() {
  command -v "${CXX:-clang++}" >/dev/null 2>&1 || return 1
  printf '#if __has_include(<vma/vk_mem_alloc.h>)\n#include <vma/vk_mem_alloc.h>\n#else\n#include <vk_mem_alloc.h>\n#endif\n' \
    | "${CXX:-clang++}" -x c++ -std=c++17 -fsyntax-only $(pkg-config --cflags vulkan 2>/dev/null) - >/dev/null 2>&1
}
t_qtwayland() {
  [ -f /usr/lib/qt6/plugins/platforms/libqwayland-generic.so ] || [ -f /usr/lib64/qt6/plugins/platforms/libqwayland-generic.so ] \
    || [ -f /usr/lib/x86_64-linux-gnu/qt6/plugins/platforms/libqwayland-generic.so ]
}
check_packages() {
  MISSING_PKGS=""; AUR_NOTE=0; MISSING_LABELS=""
  t_cmds clang clang++;                  check "clang" $? "clang" "clang" "clang"
  t_cmds make cc git;                    check "make, cc, git" $? "build-essential git" "make gcc gcc-c++ git" "base-devel git"
  t_cmds cmake;                          check "cmake" $? "cmake" "cmake" "cmake"
  t_cmds pkg-config;                     check "pkg-config" $? "pkg-config" "pkgconf-pkg-config" "pkgconf"
  [ -x /usr/bin/time ];                  check "GNU time" $? "time" "time" "time"
  t_pc Qt6Widgets;                       check "Qt 6 Widgets" $? "qt6-base-dev" "qt6-qtbase-devel" "qt6-base"
  t_pc vulkan;                           check "Vulkan" $? "libvulkan-dev" "vulkan-headers vulkan-loader-devel" "vulkan-headers vulkan-icd-loader"
  t_pc sdl3;                             check "SDL3" $? "libsdl3-dev" "SDL3-devel" "sdl3"
  { t_pc shaderc_shared || t_pc shaderc; }; check "shaderc" $? "libshaderc-dev" "libshaderc-devel" "shaderc"
  t_vma;                                 check "Vulkan Memory Allocator" $? "libvulkan-memory-allocator-dev" "VulkanMemoryAllocator-devel" "-"
  t_pc libavcodec libavformat libavutil; check "FFmpeg" $? "libavcodec-dev libavformat-dev libavutil-dev" \
                                           "libavcodec-free-devel libavformat-free-devel libavutil-free-devel" "ffmpeg"
  python_ok;                             check "Python 3" $? "python3" "python3" "python"
  python3 -c 'import venv, ensurepip' >/dev/null 2>&1; check "Python venv" $? "python3-venv" "-" "-"
  if [ "${XDG_SESSION_TYPE:-}" = wayland ]; then t_qtwayland; check "Qt Wayland" $? "qt6-wayland" "qt6-qtwayland" "qt6-wayland"; fi
}
# Runs a command as administrator: directly as root, else through sudo (it asks for the password itself).
as_root() {
  if [ "$(id -u)" = 0 ]; then run "$@"
  elif command -v sudo >/dev/null 2>&1; then run sudo "$@"
  else die lx_need_sudo "$*"; fi
}
install_pkgs() {
  # shellcheck disable=SC2086
  case "$PM" in
    apt) as_root apt update && as_root apt install -y $MISSING_PKGS ;;
    dnf) as_root dnf install -y $MISSING_PKGS ;;
    pacman) as_root pacman -S --needed --noconfirm $MISSING_PKGS ;;
  esac
}
check_packages
if [ -n "$MISSING_LABELS" ] && [ -n "$PM" ] && [ -n "${MISSING_PKGS# }" ]; then
  printf '\n'
  say lx_pkgs_plan "$PM" "$MISSING_PKGS"
  say lx_sudo_note "$PM"
  if [ "$PM" = dnf ]; then say lx_fedora_note; fi
  ask_yn lx_pkgs_ask || die lx_pkgs_required
  install_pkgs || die lx_install_failed
  if [ "$INSTALL_DRY" = 0 ]; then printf '\n'; say lx_recheck; check_packages; fi
fi
if [ "$INSTALL_DRY" = 0 ] && [ -n "$MISSING_LABELS" ]; then
  if [ "$AUR_NOTE" = 1 ]; then say lx_aur; fi
  die lx_still_missing "$MISSING_LABELS"
fi

# ------------------------------------------------------------------ 3 Python
step st_python
if python_ok; then ok py_ok "$(python3 --version 2>&1 | cut -d' ' -f2)"; elif [ "$INSTALL_DRY" = 0 ]; then die lx_py_missing; fi
use_venv || die venv_failed
for pair in lz4:lz4 PIL:Pillow; do
  venv_pip "${pair%%:*}" "${pair##*:}" || die pip_failed
done
venv_native_unicorn || die pip_failed

# ------------------------------------------------------------------ 4 final check
step st_final
check_space 60
DEPS_CMD='source scripts/recomp/linux/deps.sh && linux_require_runtime && linux_require_qt'
if bash -c "$DEPS_CMD" >/dev/null 2>&1; then ok lx_deps_ok
else
  bad lx_deps_bad
  bash -c "$DEPS_CMD" 2>&1 | sed 's/^/    /'
  if [ "$INSTALL_DRY" = 0 ]; then die lx_deps_fix; fi
fi

# ------------------------------------------------------------------ 5 files
step st_files
ask_game_files "$HOME/.switch/prod.keys" "$HOME/.local/share/yuzu/keys/prod.keys" "$HOME/.config/Ryujinx/system/prod.keys"
build_input_args
confirm_build "" lx_build_ask

# ------------------------------------------------------------------ 6 build
step st_build
stage() {   # stage <label key> <command...>
  local key="$1"; shift
  printf '\n%s▶ %s%s\n' "$B" "$(msg "$key")" "$N"
  run "$@"
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    printf '\n'; bad lx_stage_failed "$(msg "$key")" "$rc"; say rerun_hint
    finish "$rc"
  fi
}
stage lx_s1 scripts/build_all.sh --only tools,extract "${INPUT_ARGS[@]}" --min-free-gb "$MINFREE"
stage lx_s2 bash scripts/recomp/linux/local/build_all.sh
stage lx_s3 env IMG=work/recomp/img_gfx HLE_LIST=scripts/recomp/rt-bdsp/hle_nvn.txt bash scripts/recomp/rt-bdsp/mkimages.sh
stage lx_s4 bash scripts/recomp/linux/local/vk_build.sh --qt

if [ "$INSTALL_DRY" = 1 ]; then finish 0; fi
printf '\n%s%s%s\n  work/recomp/bdsp_boot_vk_qt\n' "$G" "$(msg lx_done)" "$N"
START=(bash scripts/recomp/linux/local/vk_qt.sh "XDG_RUNTIME_DIR=/run/user/$(id -u)")
if [ -n "${WAYLAND_DISPLAY:-}" ]; then START+=("WAYLAND_DISPLAY=$WAYLAND_DISPLAY" QT_QPA_PLATFORM=wayland)
elif [ -n "${DISPLAY:-}" ]; then START+=("DISPLAY=$DISPLAY" QT_QPA_PLATFORM=xcb); fi
say lx_start_with "${START[*]}"
if ask_yn start_ask; then "${START[@]}"; fi
finish 0
