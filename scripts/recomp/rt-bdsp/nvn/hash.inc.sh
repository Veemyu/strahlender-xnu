# SHA-256-Werkzeug: shasum -a 256, sonst sha256sum (Ausgabe gleich: "hash  datei"). Per source einbinden, dann sha256 aufrufen.
if command -v shasum > /dev/null 2>&1; then sha256() { shasum -a 256 "$@"; }; else sha256() { sha256sum "$@"; }; fi
