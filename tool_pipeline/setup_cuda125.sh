#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
setup_python="${SPEECH_SETUP_PYTHON:-}"
if [[ -z "$setup_python" ]]; then
    for candidate in python3.12 python3.11 /usr/bin/python3 python3; do
        if command -v "$candidate" >/dev/null && "$candidate" -c \
            'import sys; sys.exit(not ((3, 11) <= sys.version_info[:2] < (3, 13)))'; then
            setup_python="$candidate"
            break
        fi
    done
fi
[[ -n "$setup_python" ]] || { printf '%s\n' 'Python 3.11 or 3.12 is required' >&2; exit 1; }
exec "$setup_python" "$script_dir/scripts/setup_cuda125.py" "$@"
