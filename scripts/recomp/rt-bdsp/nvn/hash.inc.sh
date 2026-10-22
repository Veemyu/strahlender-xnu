# SHA-256 tool: shasum -a 256, otherwise sha256sum (same output: "hash  file"). Source it, then call sha256.
if command -v shasum > /dev/null 2>&1; then sha256() { shasum -a 256 "$@"; }; else sha256() { sha256sum "$@"; }; fi
