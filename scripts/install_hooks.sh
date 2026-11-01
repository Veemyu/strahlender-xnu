#!/usr/bin/env bash
# Installs two local hooks: pre-commit runs scripts/repo_check.py --staged, pre-push runs scripts/check.sh (fmt, clippy, tests, compile checks).
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
PUSH="$ROOT/.git/hooks/pre-push"
cat > "$PUSH" <<'EOF'
#!/usr/bin/env bash
# Blocks a push when the local gate fails (scripts/check.sh). Skip once with: git push --no-verify
exec "$(git rev-parse --show-toplevel)/scripts/check.sh"
EOF
chmod +x "$PUSH"
echo "Hook installed: $PUSH"
