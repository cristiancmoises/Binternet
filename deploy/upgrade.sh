#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
    echo 'Python 3 is required. On Debian: apt-get update && apt-get install -y python3' >&2
    exit 1
fi
exec python3 "$project_dir/deploy/upgrade.py" upgrade "$@"
