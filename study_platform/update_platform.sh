#!/usr/bin/env bash
# Update the study backend and build its website in an existing installation.
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
    printf '%s\n' 'Usage: bash update_platform.sh [runtime-root]' \
        'Default: /workspace/minicpm-study-install/runtime'
    exit 0
fi
[[ $# -le 1 ]] || { printf '%s\n' 'Expected one runtime-root argument' >&2; exit 1; }
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
runtime_root="${1:-/workspace/minicpm-study-install/runtime}"
study_python="$runtime_root/study-venv/bin/python"
[[ -x "$study_python" ]] || { printf 'Missing study environment: %s\n' "$study_python" >&2; exit 1; }
"$study_python" -m pip install --no-cache-dir -e "$script_dir/../speech_contracts" -e "$script_dir"
"$study_python" -m pip check
bash "$script_dir/update_frontend.sh" "$runtime_root"
printf '%s\n' 'Study backend and website updated. Restart the study service to load backend changes.'
