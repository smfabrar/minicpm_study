#!/usr/bin/env bash
# Apply the repository's Python dependencies to an existing runtime installation.
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
    printf '%s\n' 'Usage: bash update_runtime.sh [runtime-root]' \
        'Default: /workspace/minicpm-study-install/runtime'
    exit 0
fi
[[ $# -le 1 ]] || { printf '%s\n' 'Expected one runtime-root argument' >&2; exit 1; }
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
runtime_root="${1:-/workspace/minicpm-study-install/runtime}"
runtime_python="$runtime_root/venv/bin/python"
[[ -x "$runtime_python" && -f "$runtime_root/activate.sh" ]] || {
    printf 'Missing runtime installation: %s\n' "$runtime_root" >&2
    exit 1
}
source "$runtime_root/activate.sh"

"$runtime_python" -m pip install --no-cache-dir --only-binary=av \
    -c "$script_dir/scripts/constraints-cuda125.txt" \
    -e "$script_dir/../speech_contracts" -e "$script_dir[models]"
"$runtime_python" -m pip check
"$runtime_python" "$script_dir/scripts/gpu_setup_support.py" verify-audio
"$runtime_python" -m pip freeze >"$runtime_root/requirements-resolved.txt"
printf '%s\n' 'Runtime dependencies updated and audio decoding verified. Restart the runtime service before starting a new study run; see docs/SETUP.md.'
