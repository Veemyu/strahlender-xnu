#!/usr/bin/env bash
# Local gate before every push (the same checks the CI runs, in minutes instead of a 25 minute round trip):
#   scripts/check.sh          fast: repo check, rustfmt, clippy, Rust and release tests, runtime compile checks
#   scripts/check.sh --full   additionally the whole Python test suite
# scripts/install_hooks.sh installs it as the pre-push hook. Own code.
# In a git worktree the installer would be compiled into a fresh installer/target (about 10 GB); share one build folder instead:
#   CARGO_TARGET_DIR=$HOME/.cache/bdsp-cargo-target scripts/check.sh      (cargo uses it for both crates; the first run compiles, later runs reuse it)
# A worktree has no tools/pydeps (gitignored), so with --full the native generator tests report "Unicorn 2.1.4 ... required"; point them at the main checkout:
#   TOOLS_DIR=<main checkout>/tools scripts/check.sh --full
set -euo pipefail
cd "$(dirname "$0")/.."
FULL=0; [ "${1:-}" = "--full" ] && FULL=1
step() { printf '\n== %s\n' "$*"; }

step "repo check (no game data, keys or dumps)"
python3 scripts/repo_check.py

# Same flags as .github/workflows (installer-ci.yml, tests.yml): the installer is linted as a binary, the extract tool with all targets.
for crate in installer installer/extract; do
  step "$crate: rustfmt, clippy, tests"
  manifest="$crate/Cargo.toml"; targets=""; [ "$crate" = installer/extract ] && targets="--all-targets"
  cargo fmt --manifest-path "$manifest" -- --check
  cargo clippy --locked --manifest-path "$manifest" $targets -- -D warnings 2>&1 | tail -3
  cargo test --locked --manifest-path "$manifest" -q 2>&1 | grep -E "^test result|FAILED|^error" | sort | uniq -c | head -5
done

step "release scripts and SBOM tests"
python3 -m unittest scripts.tests.test_installer_release scripts.tests.test_generate_sbom scripts.tests.test_shader_bootstrap scripts.tests.test_installer_driver scripts.tests.test_diagnostics scripts.tests.test_pathlimits 2>&1 | tail -3
step "shader translator tests (C and CLI)"
make -s -C shader_translator test 2>&1 | grep -E "^(OK|FAILED|Ran)" 

step "window title helper test (C)"
bash scripts/recomp/runtime/test/run_window_title_test.sh

if [ "$(uname)" = Darwin ] && xcrun --sdk iphoneos --show-sdk-path >/dev/null 2>&1; then
  step "runtime compile check: iPhone/iPad (model A-low, the iPad build)"
  BDSP_SYNTAX_ONLY=1 bash scripts/recomp/ios/build_rt32.sh ios
else
  step "runtime compile check skipped (needs macOS with Xcode and the iPhoneOS SDK)"
fi

if [ "$FULL" = 1 ]; then
  step "Python test suite"
  python3 -m unittest discover -s scripts/tests 2>&1 | tail -4
fi
printf '\nAll checks passed.\n'
