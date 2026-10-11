#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
setup_python="${SPEECH_SETUP_PYTHON:-python3.11}"
exec "$setup_python" "$script_dir/scripts/setup_cuda125.py" "$@"
