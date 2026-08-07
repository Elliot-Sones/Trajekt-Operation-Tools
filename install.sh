#!/usr/bin/env bash
# Link this stack's skills + MCP config into ONE target project.
# Usage: ./install.sh [/path/to/project]   (defaults to current dir)
set -euo pipefail
STACK="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-$PWD}"
mkdir -p "$TARGET/.claude/skills"
for s in "$STACK"/skills/*/; do [ -d "$s" ] && ln -sfn "$s" "$TARGET/.claude/skills/$(basename "$s")" && echo "linked skill: $(basename "$s")"; done
if [ -f "$TARGET/.mcp.json" ]; then
  echo "NOTE: $TARGET/.mcp.json already exists — merge servers from $STACK/mcp/.mcp.json by hand."
else
  cp "$STACK/mcp/.mcp.json" "$TARGET/.mcp.json"
  echo "copied .mcp.json -> $TARGET (approve servers on next Claude Code launch)"
fi
echo "Now set env vars in $TARGET/.env from $STACK/.env.example"
