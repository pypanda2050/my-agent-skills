#!/usr/bin/env bash
# Link every skill directory in this repo into ~/.claude/skills.
# Safe to re-run: skips skills that are already correctly linked.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="${HOME}/.claude/skills"

mkdir -p "$SKILLS_DIR"

linked=0
skipped=0

for skill_path in "$REPO_DIR"/*/; do
  skill_name="$(basename "$skill_path")"

  # Skip non-skill entries (scripts, dotfiles, etc.)
  [[ -f "$skill_path/SKILL.md" ]] || continue

  target="$SKILLS_DIR/$skill_name"

  if [[ -L "$target" && "$(readlink "$target")" == "$skill_path" ]]; then
    echo "  already linked: $skill_name"
    ((skipped++)) || true
  else
    # Remove stale real directory or wrong symlink before relinking
    [[ -e "$target" || -L "$target" ]] && rm -rf "$target"
    ln -s "$skill_path" "$target"
    echo "  linked: $skill_name -> $target"
    ((linked++)) || true
  fi
done

echo ""
echo "Done. Linked: $linked, already up-to-date: $skipped"
