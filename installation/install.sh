#!/usr/bin/env bash
# Downloadable entry point. Run with bash; no existing project checkout is required.
set -euo pipefail
trap 'printf "Installation stopped at line %s. Fix the error above and rerun.\n" "$LINENO" >&2' ERR

install_root="/workspace/minicpm-study-install"
study_ref="${SPEECH_STUDY_REF:-main}"
study_repository="${SPEECH_STUDY_REPOSITORY:-https://github.com/smfabrar/minicpm_study.git}"
reference_repository="https://github.com/smfabrar/minicpm_tool.git"
reference_ref="f3e7cdc08cdf49c50414f405f31fc0eee9bca105"
with_platform=true
skip_models=false
dry_run=false
start_services=true
build_jobs=2
cuda_home="/usr/local/cuda-12.5"
minimum_free_gib="${SPEECH_INSTALL_MIN_FREE_GIB:-}"

usage() {
    cat <<'HELP'
Usage: bash installation/install.sh [options]

Install the MiniCPM study website and GPU pipeline on Linux x86_64.
Recommended Vast image: nvidia/cuda:12.5.1-devel-ubuntu24.04 (SSH launch mode).
An NVIDIA driver and a complete CUDA 12.5 toolkit must already be installed.
This script does not install CUDA, drivers, or Conda. PyTorch uses a project venv.

  --prefix PATH       Installation directory (default: /workspace/minicpm-study-install)
  --ref REF           Study branch/tag/commit (default: main)
  --cuda-home PATH    Existing CUDA 12.5 toolkit (default: /usr/local/cuda-12.5)
  --jobs N            Native build parallelism (default: 2)
  --runtime-only      Omit website and Node installation
  --skip-models       Install/build first without downloading model weights
  --no-start          Install without starting services
  --dry-run           Describe steps without downloads or changes
  --help              Show this help

SPEECH_STUDY_REPOSITORY can override the Git clone URL for a private repository.
SPEECH_SETUP_PYTHON can select an existing Python 3.11/3.12 interpreter.
SPEECH_INSTALL_MIN_FREE_GIB overrides the free-space floor (30 GiB fresh, 10 GiB without models, 5 GiB on an existing installation).
HELP
}

die() { printf '%s\n' "$*" >&2; exit 1; }

while (($#)); do
    case "$1" in
        --prefix|--ref|--cuda-home|--jobs)
            (($# >= 2)) || die "$1 requires a value"
            case "$1" in
                --prefix) install_root="$2" ;;
                --ref) study_ref="$2" ;;
                --cuda-home) cuda_home="$2" ;;
                --jobs) build_jobs="$2" ;;
            esac
            shift 2 ;;
        --runtime-only) with_platform=false; shift ;;
        --skip-models) skip_models=true; shift ;;
        --no-start) start_services=false; shift ;;
        --dry-run) dry_run=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done
[[ "$build_jobs" =~ ^[1-9][0-9]*$ ]] || die '--jobs must be a positive integer'
[[ -n "$install_root" && -n "$study_ref" && "$study_ref" != -* ]] || die 'Invalid prefix or ref'
if [[ -z "$minimum_free_gib" ]]; then
    minimum_free_gib=30
    "$skip_models" && minimum_free_gib=10
    [[ ! -f "$install_root/runtime/setup-manifest.json" ]] || minimum_free_gib=5
fi
[[ "$minimum_free_gib" =~ ^[1-9][0-9]{0,3}$ ]] \
    || die 'SPEECH_INSTALL_MIN_FREE_GIB must be an integer between 1 and 9999'

if "$dry_run"; then
    printf 'Dry run: no changes. Installation root: %s\n' "$install_root"
    printf '%s\n' \
        '1. Check Linux x86_64, the existing NVIDIA driver and complete CUDA 12.5 toolkit.' \
        "   Selected toolkit: $cuda_home (no automatic toolkit installation)." \
        "   Check at least $minimum_free_gib GiB free on the installation filesystem." \
        '2. Install apt build/audio/download prerequisites.' \
        "3. Download study ref $study_ref and the pinned minicpm_tool reference." \
        '4. Select Python 3.11/3.12 with venv support; fail if unavailable.' \
        '5. Validate the selected toolkit again using the repository checker.'
    "$with_platform" && printf '%s\n' '6. Reuse Node 22.12+, or download a checksum-verified Node 22 build.'
    printf '7. Run package setup; website=%s, download models=%s, build jobs=%s.\n' \
        "$with_platform" "$([[ "$skip_models" == true ]] && printf false || printf true)" "$build_jobs"
    printf "8. Start services after a full install unless --no-start is set.\n"
    exit 0
fi

[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || die 'Requires Linux x86_64'
space_probe="$install_root"
while [[ ! -e "$space_probe" ]]; do space_probe="$(dirname -- "$space_probe")"; done
available_kib="$(df -Pk -- "$space_probe" | awk 'NR == 2 {print $4}')"
[[ "$available_kib" =~ ^[0-9]+$ ]] || die "Cannot check disk space for $install_root"
printf 'Installation filesystem: %s GiB free; requested floor: %s GiB\n' \
    "$((available_kib / 1024 / 1024))" "$minimum_free_gib"
((available_kib >= minimum_free_gib * 1024 * 1024)) \
    || die "Not enough disk space for $install_root. Enlarge this volume or select a larger --prefix filesystem."
command -v nvidia-smi >/dev/null || die 'An NVIDIA driver and nvidia-smi must already be available'
nvidia-smi
driver_versions="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader)"
[[ -n "$driver_versions" ]] || die 'No NVIDIA GPU driver was reported'
while IFS= read -r driver_version; do
    [[ "$driver_version" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]] \
        || die "Cannot read NVIDIA driver version: $driver_version"
    awk -F. '{exit !($1 > 555 || ($1 == 555 && ($2 > 42 || ($2 == 42 && $3 >= 2))))}' \
        <<< "$driver_version" || die "Driver $driver_version is below the required 555.42.02"
done <<< "$driver_versions"

# Validate before apt or downloads; Python setup repeats this after checkout.
[[ -x "$cuda_home/bin/nvcc" ]] || die "Missing $cuda_home/bin/nvcc. Select nvidia/cuda:12.5.1-devel-ubuntu24.04 or pass --cuda-home for a complete CUDA 12.5 toolkit."
cuda_version="$("$cuda_home/bin/nvcc" --version)"
grep -Eq 'release 12\.5[,[:space:]]' <<< "$cuda_version" \
    || die "Selected toolkit must be CUDA 12.5: $cuda_home. Driver and PyTorch CUDA versions do not select the compiler."
for required_file in cuda_runtime.h cuda.h cublas_v2.h libcudart.so libcublas.so; do
    found=false
    for directory in targets/x86_64-linux/include include targets/x86_64-linux/lib lib64 lib; do
        if [[ -f "$cuda_home/$directory/$required_file" ]]; then found=true; break; fi
    done
    "$found" || die "Incomplete CUDA toolkit: $cuda_home is missing $required_file. Use the CUDA 12.5 devel image; base/runtime images are insufficient."
done
cuda_home="$(cd -- "$cuda_home" && pwd)"
printf 'Selected CUDA toolkit: %s\n%s\n' "$cuda_home" "$cuda_version"
command -v apt-get >/dev/null || die 'This installer supports Ubuntu/Debian with apt-get'
sudo_command=()
if ((EUID != 0)); then
    command -v sudo >/dev/null || die 'Run as root or provide sudo for system prerequisites'
    sudo_command=(sudo)
fi
"${sudo_command[@]}" apt-get update
"${sudo_command[@]}" apt-get install -y \
    git curl ca-certificates bzip2 xz-utils tar build-essential gcc-12 g++-12 \
    ninja-build pkg-config espeak-ng libsndfile1 python3 python3-venv python3-dev
mkdir -p "$install_root"
install_root="$(cd -- "$install_root" && pwd)"
mkdir -p "$install_root/cache" "$install_root/bin" "$install_root/tmp"
export TMPDIR="$install_root/tmp"
export PIP_NO_CACHE_DIR=1

download() {
    curl --fail --location --retry 3 --output "$2.part" "$1"
    mv -- "$2.part" "$2"
}

checkout() {
    local directory="$1" repository="$2" ref="$3"
    if [[ ! -d "$directory/.git" ]]; then
        if [[ -e "$directory" ]]; then
            [[ -d "$directory" && -z "$(ls -A -- "$directory")" ]] \
                || die "Refusing to replace existing directory: $directory"
        fi
        git init "$directory"
    fi
    local origin
    origin="$(git -C "$directory" remote get-url origin 2>/dev/null || true)"
    if [[ -z "$origin" ]]; then
        [[ -z "$(git -C "$directory" status --porcelain)" ]] || die "Uninitialized checkout contains files: $directory"
        git -C "$directory" remote add origin "$repository"
    else
        [[ "$origin" == "$repository" ]] || die "Unexpected repository in $directory"
    fi
    git -C "$directory" diff --quiet && git -C "$directory" diff --cached --quiet \
        || die "Save tracked local changes before reinstalling: $directory"
    git -C "$directory" fetch --depth 1 origin "$ref"
    git -C "$directory" checkout --detach FETCH_HEAD
}

find_python() {
    local candidate
    local -a candidates
    if [[ -n "${SPEECH_SETUP_PYTHON:-}" ]]; then
        candidates=("$SPEECH_SETUP_PYTHON")
    else
        candidates=(python3.12 python3.11 /usr/bin/python3 python3)
    fi
    for candidate in "${candidates[@]}"; do
        if command -v "$candidate" >/dev/null && "$candidate" -c \
            'import ensurepip, sys, venv; sys.exit(not ((3, 11) <= sys.version_info[:2] < (3, 13)))' \
            >/dev/null 2>&1; then
            setup_python="$(command -v "$candidate")"
            return
        fi
    done
    die 'Python 3.11/3.12 with venv/ensurepip is required. Use the recommended Ubuntu 24.04 image or set SPEECH_SETUP_PYTHON to a supported interpreter.'
}

prepare_node() {
    if [[ -x "$install_root/node/bin/node" ]]; then
        export PATH="$install_root/node/bin:$PATH"
    fi
    if command -v node >/dev/null && command -v npm >/dev/null && node -e \
        'const [major,minor]=process.versions.node.split(".").map(Number); process.exit(major>22 || (major===22 && minor>=12) ? 0 : 1)'; then
        return
    fi
    download 'https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt' "$install_root/cache/node-checksums.txt"
    local archive checksum version
    archive="$(awk '$2 ~ /^node-v22\.[0-9]+\.[0-9]+-linux-x64.tar.xz$/ {print $2; exit}' "$install_root/cache/node-checksums.txt")"
    [[ -n "$archive" ]] || die 'Cannot find the Node 22 Linux x64 release'
    checksum="$(awk -v name="$archive" '$2 == name {print $1}' "$install_root/cache/node-checksums.txt")"
    version="${archive#node-}"
    version="${version%-linux-x64.tar.xz}"
    download "https://nodejs.org/dist/$version/$archive" "$install_root/cache/$archive"
    printf '%s  %s\n' "$checksum" "$install_root/cache/$archive" | sha256sum --check -
    mkdir -p "$install_root/node"
    tar -xJf "$install_root/cache/$archive" --strip-components=1 -C "$install_root/node"
    export PATH="$install_root/node/bin:$PATH"
}

services_stopped=false
control="$install_root/minicpm_study/installation/internal/services.py"
if [[ -x "$install_root/runtime/venv/bin/python" && -f "$control" ]]; then
    "$install_root/runtime/venv/bin/python" "$control" stop --root "$install_root/runtime"
    services_stopped=true
fi
checkout "$install_root/minicpm_study" "$study_repository" "$study_ref"
checkout "$install_root/minicpm_tool" "$reference_repository" "$reference_ref"
git -C "$install_root/minicpm_study" rev-parse HEAD > "$install_root/study-revision.txt"
find_python
# bitsandbytes imports Triton, which builds a C extension against this Python.
header_check="$install_root/minicpm_study/installation/internal/gpu_setup_support.py"
header_python="$setup_python"
if [[ -x "$install_root/runtime/venv/bin/python" ]]; then
    header_python="$install_root/runtime/venv/bin/python"
fi
if ! "$header_python" "$header_check" verify-python-headers; then
    development_package="$("$header_python" -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}-dev")')"
    "${sudo_command[@]}" apt-get install -y "$development_package"
    "$header_python" "$header_check" verify-python-headers
fi
if ! "$services_stopped" && [[ -x "$install_root/runtime/venv/bin/python" && -x "$install_root/runtime/bin/start_runtime.sh" ]]; then
    "$install_root/runtime/venv/bin/python" "$control" stop --root "$install_root/runtime"
fi
"$setup_python" "$install_root/minicpm_study/installation/internal/cuda_toolkit.py" check "$cuda_home"
"$with_platform" && prepare_node

setup_arguments=(--root "$install_root/runtime" --reference "$install_root/minicpm_tool" \
    --cuda-home "$cuda_home" --jobs "$build_jobs")
"$with_platform" && setup_arguments+=(--with-platform)
"$skip_models" && setup_arguments+=(--skip-models)
"$setup_python" "$install_root/minicpm_study/installation/internal/setup_cuda125.py" "${setup_arguments[@]}"

control_directory="$install_root/minicpm_study/installation"
if "$start_services" && ! "$skip_models"; then
    bash "$control_directory/start.sh" "$install_root/runtime"
else
    printf 'Installation prepared. Start when ready: bash %q %q\n' "$control_directory/start.sh" "$install_root/runtime"
fi
printf 'Setup guide: %s/README.md\n' "$control_directory"
"$skip_models" || printf 'Study settings: %s/runtime/run-settings.json\n' "$install_root"
