
#!/bin/bash
# Setup script for Linux/macOS — symlinks hooks into ~/.hermes/hooks/
# Usage: ./hooks/setup.sh

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS_TARGET="$HOME/.hermes/hooks"

echo "Setting up Hermes hooks from $REPO_DIR/hooks/"

mkdir -p "$HOOKS_TARGET"

for hook in "$REPO_DIR/hooks"/*/; do
    name="$(basename "$hook")"
    link="$HOOKS_TARGET/$name"

    if [ -L "$link" ]; then
        rm "$link"
    elif [ -e "$link" ]; then
        echo "  ! $link already exists and is not a symlink — skipping"
        continue
    fi

    ln -s "$hook" "$link"
    echo "  ✓ Linked $name → $hook"
done

echo ""
echo "Done. Restart Hermes gateway for hooks to take effect."
