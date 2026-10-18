#!/usr/bin/env bash
# Installiert den Pre-Commit-Hook, der scripts/repo_check.py --staged ausführt.
# Eigener Code. Der Hook liegt lokal in .git/hooks und wird nicht getrackt.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$ROOT/.git/hooks/pre-commit"
cat > "$HOOK" <<'EOF'
#!/usr/bin/env bash
# Blockiert Commits mit Spieldaten, Schlüsseln oder Dumps (scripts/repo_check.py).
exec python3 "$(git rev-parse --show-toplevel)/scripts/repo_check.py" --staged
EOF
chmod +x "$HOOK"
echo "Hook installiert: $HOOK"
