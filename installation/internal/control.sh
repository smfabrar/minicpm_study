#!/usr/bin/env bash
set -euo pipefail
action="$1"
shift
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    printf 'Usage: bash installation/%s.sh [runtime-directory] [all|native|runtime|study]\n' "$action"
    printf 'Default directory: /workspace/minicpm-study-install/runtime\n'
    exit 0
fi
(($# <= 2)) || { echo 'Too many arguments. Use --help.' >&2; exit 1; }
root="${1:-/workspace/minicpm-study-install/runtime}"
python="$root/venv/bin/python"
[[ -x "$python" ]] || { printf 'Missing runtime Python: %s. Run installation/install.sh first.\n' "$python" >&2; exit 1; }
internal="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$python" "$internal/services.py" "$action" --root "$root" --service "${2:-all}"
