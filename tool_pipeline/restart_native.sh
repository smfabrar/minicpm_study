#!/usr/bin/env bash
# Restart the installed native backend, gateway and worker on the GPU server.
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
    printf '%s\n' 'Usage: bash restart_native.sh [runtime-root]' \
        'Default: /workspace/minicpm-study-install/runtime'
    exit 0
fi
[[ $# -le 1 ]] || { printf '%s\n' 'Expected one runtime-root argument' >&2; exit 1; }
runtime_root="${1:-/workspace/minicpm-study-install/runtime}"
[[ -d "$runtime_root" ]] || { printf 'Missing runtime: %s\n' "$runtime_root" >&2; exit 1; }
runtime_root="$(cd -- "$runtime_root" && pwd -P)"
launcher="$runtime_root/bin/start_native.sh"
python="$runtime_root/venv/bin/python"
[[ -x "$launcher" && -x "$python" ]] || {
    printf 'Missing executable launcher or Python under %s\n' "$runtime_root" >&2
    exit 1
}
mkdir -p "$runtime_root/logs"
exec 9>"$runtime_root/logs/native-restart.lock"
flock -n 9 || { printf '%s\n' 'Another native restart is running' >&2; exit 1; }

# Match this installation's paths, including orphaned native services.
"$python" - "$runtime_root" <<'PY'
import sys
import time
from pathlib import Path

import psutil


def is_active(process):
    try:
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def wait_stopped(processes, timeout):
    deadline = time.monotonic() + timeout
    while True:
        processes = [process for process in processes if is_active(process)]
        if not processes or time.monotonic() >= deadline:
            return processes
        time.sleep(0.1)


root = Path(sys.argv[1])
backend = root / "sources/llama.cpp-omni/build/bin/llama-omni-server"
demo = root / "sources/MiniCPM-o-Demo"
owned = {}
launchers = set()
for process in psutil.process_iter(["cmdline", "cwd"]):
    try:
        args = process.info["cmdline"] or []
        if not args:
            continue
        is_launcher = any(Path(arg).name == "launch_native.py" for arg in args)
        if is_launcher:
            if "--logs" not in args:
                continue
            logs = Path(args[args.index("--logs") + 1]).absolute()
            if logs.parent != root / "logs":
                continue
            launchers.add(process.pid)
        is_backend = Path(args[0]).absolute() == backend
        is_demo = process.info["cwd"] == str(demo) and any(
            arg in {"gateway.py", "worker.py", str(demo / "gateway.py"), str(demo / "worker.py")}
            for arg in args[1:]
        )
        if is_launcher or is_backend or is_demo:
            owned[process.pid] = process
            for child in process.children(recursive=True):
                owned[child.pid] = child
    except (psutil.NoSuchProcess, psutil.AccessDenied, IndexError):
        continue

processes = sorted(owned.values(), key=lambda process: process.pid in launchers)
print(f"Stopping {len(processes)} native processes", flush=True)
for process in processes:
    try:
        process.terminate()
    except psutil.NoSuchProcess:
        pass
alive = wait_stopped(processes, timeout=15)
for process in alive:
    try:
        process.kill()
    except psutil.NoSuchProcess:
        pass
alive = wait_stopped(alive, timeout=5)
if alive:
    raise RuntimeError(f"Native processes did not stop: {[process.pid for process in alive]}")
PY

log="$runtime_root/logs/native-service.log"
if [[ -f "$log" ]]; then
    mv -- "$log" "$log.previous"
fi
previous_manifests=("$runtime_root"/logs/native-*/manifest.json)
is_previous_manifest() {
    local previous
    for previous in "${previous_manifests[@]}"; do
        [[ "$previous" == "$1" ]] && return 0
    done
    return 1
}
nohup "$launcher" >"$log" 2>&1 </dev/null 9>&- &
native_pid=$!
printf '%s\n' "$native_pid" >"$runtime_root/logs/native.pid"
printf 'Starting native stack (launcher PID %s)\n' "$native_pid"
for ((attempt = 0; attempt < 120; attempt++)); do
    if ! kill -0 "$native_pid" 2>/dev/null; then
        printf 'Native launcher exited. Log: %s\n' "$log" >&2
        tail -n 60 "$log" >&2
        exit 1
    fi
    for manifest in "$runtime_root"/logs/native-*-"$native_pid"/manifest.json; do
        if [[ -s "$manifest" ]] && ! is_previous_manifest "$manifest"; then
            printf 'Native services started. Log: %s\n' "$log"
            printf 'Session/model initialization still needs a study run.\n'
            exit 0
        fi
    done
    sleep 1
done
printf 'Startup is still pending for PID %s. Check %s\n' "$native_pid" "$log" >&2
exit 1
