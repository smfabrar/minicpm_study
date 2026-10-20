#!/usr/bin/env bash
# Paste this entire file into Vast's On-start Script field (SSH launch mode).
set -euo pipefail
prefix="${SPEECH_INSTALL_PREFIX:-/workspace/minicpm-study-install}"
mkdir -p "$prefix/logs"
# Detach provisioning so a long native build does not hold up the SSH startup hook.
nohup bash >> "$prefix/logs/vast-startup.log" 2>&1 <<'BOOT' &
set -euo pipefail
prefix="${SPEECH_INSTALL_PREFIX:-/workspace/minicpm-study-install}"
ref="${SPEECH_STUDY_REF:-9cf8e9b62293f1e556d3e446e9fa67c09b8451ff}"
run="$prefix/runtime"
exec 9>"$prefix/logs/vast-startup.lock"
flock -n 9 || { echo 'Another startup is already running.'; exit 0; }
trap 'printf "Startup failed at line %s. See this log before retrying.\n" "$LINENO" >&2' ERR
printf '\nMiniCPM Study startup: %s\n' "$(date -u +%FT%TZ)"
if [[ -f "$run/setup-manifest.json" && -x "$run/bin/start_native.sh" && -x "$run/bin/start_runtime.sh" && -x "$run/bin/start_study.sh" ]]; then
    bash "$prefix/minicpm_study/installation/start.sh" "$run"
else
    export DEBIAN_FRONTEND=noninteractive
    if ! command -v curl >/dev/null || [[ ! -f /etc/ssl/certs/ca-certificates.crt ]]; then
        apt-get update
        apt-get install -y curl ca-certificates
    fi
    installer="$prefix/install-download.sh"
    curl --fail --location --retry 3 \
        "https://raw.githubusercontent.com/smfabrar/minicpm_study/$ref/installation/install.sh" \
        --output "$installer.part"
    mv "$installer.part" "$installer"
    bash "$installer" --prefix "$prefix" --ref "$ref" \
        --cuda-home /usr/local/cuda-12.5 --jobs "${SPEECH_BUILD_JOBS:-2}"
fi
printf 'MiniCPM Study ready. Forward laptop port 8080 to server port 8765.\n'
BOOT
printf 'Startup runs in the background. Log: %s/logs/vast-startup.log\n' "$prefix"
