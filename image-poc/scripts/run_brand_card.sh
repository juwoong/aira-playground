#!/usr/bin/env bash
# Run the cardnews brand-card command with repo-local defaults.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "[ERROR] uv command not found. Install uv or adjust the script." >&2
  exit 1
fi

uv run cardnews brand-card "$@"
