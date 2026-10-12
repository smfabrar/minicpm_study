#!/usr/bin/env bash
# Build the installed study website from the current source checkout.
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
    printf '%s\n' 'Usage: bash update_frontend.sh [runtime-root]' \
        'Default: /workspace/minicpm-study-install/runtime'
    exit 0
fi
[[ $# -le 1 ]] || { printf '%s\n' 'Expected one runtime-root argument' >&2; exit 1; }
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
runtime_root="${1:-/workspace/minicpm-study-install/runtime}"
if [[ -x "$runtime_root/../node/bin/node" ]]; then
    export PATH="$runtime_root/../node/bin:$PATH"
fi
command -v npm >/dev/null || { printf '%s\n' 'Node 22.12+ and npm are required' >&2; exit 1; }
frontend="$script_dir/frontend"
if [[ -f "$frontend/package-lock.json" ]]; then
    npm --prefix "$frontend" ci
else
    npm --prefix "$frontend" install
fi
npm --prefix "$frontend" test
npm --prefix "$frontend" run build
printf '%s\n' 'Study frontend built. Reload the browser to load the new Settings form.'
