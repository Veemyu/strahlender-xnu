#!/usr/bin/env bash
# Installs the pre-commit hook that runs scripts/repo_check.py --staged.
# Own code. The hook lives locally in .git/hooks and is not tracked.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$ROOT/.git/hooks/pre-commit"
cat > "$HOOK" <<'EOF'
#!/usr/bin/env bash
# Blocks commits with game data, keys or dumps (scripts/repo_check.py).
exec python3 "$(git rev-parse --show-toplevel)/scripts/repo_check.py" --staged
EOF
chmod +x "$HOOK"
echo "Hook installed: $HOOK"
