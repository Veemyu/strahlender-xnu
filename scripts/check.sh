#!/usr/bin/env bash
# Local gate before every push (the same checks the CI runs, in minutes instead of a 25 minute round trip):
#   scripts/check.sh          fast: repo check, rustfmt, clippy, Rust and release tests, runtime compile checks
#   scripts/check.sh --full   additionally the whole Python test suite
# scripts/install_hooks.sh installs it as the pre-push hook. Own code.
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
python3 -m unittest scripts.tests.test_installer_release scripts.tests.test_generate_sbom 2>&1 | tail -3

if [ "$(uname)" = Darwin ] && xcrun --sdk iphoneos --show-sdk-path >/dev/null 2>&1; then
  step "runtime compile check: iPhone/iPad (model A-low, the iPad build)"
  MODEL=a ORG=0x400000000 BDSP_SYNTAX_ONLY=1 bash scripts/recomp/ios/build_rt32.sh ios
else
  step "runtime compile check skipped (needs macOS with Xcode and the iPhoneOS SDK)"
fi

if [ "$FULL" = 1 ]; then
  step "Python test suite"
  python3 -m unittest discover -s scripts/tests 2>&1 | tail -4
fi
printf '\nAll checks passed.\n'
