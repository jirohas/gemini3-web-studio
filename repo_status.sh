#!/usr/bin/env bash
set -euo pipefail

# Quick helper to show repo status for sanity checks

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Error: not inside a git repository" >&2
  exit 1
fi

echo "=== Branch and status ==="
git status -sb

echo

echo "=== Recent commits (last 5) ==="
git log --oneline -5
