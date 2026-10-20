#!/usr/bin/env bash
# Same options as install.sh. Copy first because the update replaces this checkout.
set -euo pipefail
folder="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
installer="$(mktemp "${TMPDIR:-/tmp}/minicpm-install.XXXXXX")"
trap 'rm -f "$installer"' EXIT
cp "$folder/install.sh" "$installer"
bash "$installer" "$@"
