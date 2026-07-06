#!/bin/bash
# Periodic safety-net commit for DATA TOOL. Commits any pending changes
# (tracked edits + new untracked files) so nothing can be lost to an
# accidental `git clean`, crash, or deletion. Runs via launchd (see
# ~/Library/LaunchAgents/com.datatool.gitautosave.plist).
set -euo pipefail

cd "/Users/sid/Desktop/DATA TOOL"

# Nothing to do if the tree is clean.
if git diff --quiet && git diff --cached --quiet && [ -z "$(git status --porcelain)" ]; then
  exit 0
fi

git add -A
git commit -m "autosave: $(date '+%Y-%m-%d %H:%M:%S')" --quiet
