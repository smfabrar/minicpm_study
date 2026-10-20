#!/usr/bin/env bash
set -euo pipefail
folder="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$folder/internal/control.sh" restart "$@"
