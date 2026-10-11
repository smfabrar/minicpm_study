#!/usr/bin/env bash
# Downloadable entry point. Run with bash; no existing project checkout is required.
set -euo pipefail
trap 'printf "Installation stopped at line %s. Fix the error above and rerun.\n" "$LINENO" >&2' ERR

install_root="${PWD}/minicpm-study-install"
study_ref="${SPEECH_STUDY_REF:-main}"
study_repository="${SPEECH_STUDY_REPOSITORY:-https://github.com/smfabrar/minicpm_study.git}"
reference_repository="https://github.com/smfabrar/minicpm_tool.git"
reference_ref="f3e7cdc08cdf49c50414f405f31fc0eee9bca105"
with_platform=true
skip_models=false
dry_run=false
build_jobs=2
cuda_home=""
minimum_free_gib="${SPEECH_INSTALL_MIN_FREE_GIB:-}"

usage() {
    cat <<'HELP'
Usage: bash install.sh [options]

Install the MiniCPM study website and GPU pipeline on Ubuntu/Debian Linux x86_64.
An NVIDIA driver must already be installed. CUDA 12.5 is installed locally if needed.

  --prefix PATH       Installation directory (default: ./minicpm-study-install)
  --ref REF           Study branch/tag/commit (default: main)
  --cuda-home PATH    Use this existing CUDA 12.5 toolkit
  --jobs N            Native build parallelism (default: 2)
  --runtime-only      Omit website and Node installation
  --skip-models       Install/build first without downloading model weights
  --dry-run           Describe steps without downloads or changes
  --help              Show this help

SPEECH_STUDY_REPOSITORY can override the Git clone URL for a private repository.
SPEECH_SETUP_PYTHON can select an existing Python 3.11/3.12 interpreter.
SPEECH_INSTALL_MIN_FREE_GIB overrides the free-space floor (30 GiB full, 10 GiB without models).
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
fi
[[ "$minimum_free_gib" =~ ^[1-9][0-9]{0,3}$ ]] \
    || die 'SPEECH_INSTALL_MIN_FREE_GIB must be an integer between 1 and 9999'

if "$dry_run"; then
    printf 'Dry run: no changes. Installation root: %s\n' "$install_root"
    printf '%s\n' \
        '1. Check Linux x86_64 and the existing NVIDIA driver.' \
        "   Check at least $minimum_free_gib GiB free on the installation filesystem." \
        '2. Install apt build/audio/download prerequisites.' \
        "3. Download study ref $study_ref and the pinned minicpm_tool reference." \
        '4. Reuse Python 3.11/3.12, or install Python 3.12 locally.' \
        '5. Reuse CUDA 12.5, or install it locally alongside existing CUDA.'
    "$with_platform" && printf '%s\n' '6. Reuse Node 22.12+, or download a checksum-verified Node 22 build.'
    printf '7. Run package setup; website=%s, download models=%s, build jobs=%s.\n' \
        "$with_platform" "$([[ "$skip_models" == true ]] && printf false || printf true)" "$build_jobs"
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
command -v apt-get >/dev/null || die 'This installer supports Ubuntu/Debian with apt-get'
sudo_command=()
if ((EUID != 0)); then
    command -v sudo >/dev/null || die 'Run as root or provide sudo for system prerequisites'
    sudo_command=(sudo)
fi
"${sudo_command[@]}" apt-get update
"${sudo_command[@]}" apt-get install -y \
    git curl ca-certificates bzip2 xz-utils tar build-essential gcc-12 g++-12 \
    ninja-build pkg-config espeak-ng libsndfile1 python3-venv
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

micromamba() {
    if [[ ! -x "$install_root/bin/micromamba" ]]; then
        download 'https://micro.mamba.pm/api/micromamba/linux-64/latest' "$install_root/cache/micromamba.tar.bz2"
        tar -xjf "$install_root/cache/micromamba.tar.bz2" -C "$install_root" bin/micromamba
    fi
    "$install_root/bin/micromamba" --no-rc --root-prefix "$install_root/mamba" "$@"
}

install_environment() {
    local environment_prefix="$1" operation=create
    shift
    [[ ! -d "$environment_prefix/conda-meta" ]] || operation=install
    micromamba "$operation" --yes --prefix "$environment_prefix" --override-channels "$@"
}

find_python() {
    local candidate
    local -a candidates
    if [[ -n "${SPEECH_SETUP_PYTHON:-}" ]]; then
        candidates=("$SPEECH_SETUP_PYTHON")
    else
        candidates=(python3.12 python3.11 python3 "$install_root/python/bin/python")
    fi
    for candidate in "${candidates[@]}"; do
        if command -v "$candidate" >/dev/null && "$candidate" -c \
            'import ensurepip, sys, venv; sys.exit(not ((3, 11) <= sys.version_info[:2] < (3, 13)))' \
            >/dev/null 2>&1; then
            setup_python="$(command -v "$candidate")"
            return
        fi
    done
    [[ -z "${SPEECH_SETUP_PYTHON:-}" ]] || die 'SPEECH_SETUP_PYTHON must provide Python 3.11/3.12 with venv/ensurepip'
    install_environment "$install_root/python" -c conda-forge python=3.12 pip
    setup_python="$install_root/python/bin/python"
}

is_cuda125() {
    [[ -x "$1/bin/nvcc" ]] && "$1/bin/nvcc" --version | grep -Eq 'release 12\.5[,[:space:]]'
}

prepare_cuda() {
    if [[ -n "$cuda_home" ]]; then
        is_cuda125 "$cuda_home" || die '--cuda-home must contain a CUDA 12.5 nvcc'
        return
    fi
    local candidate nvcc_path
    nvcc_path="$(command -v nvcc || true)"
    for candidate in /usr/local/cuda-12.5 "${CUDA_HOME:-/nonexistent}" \
        "${nvcc_path%/bin/nvcc}" "$install_root/cuda-12.5"; do
        if is_cuda125 "$candidate"; then
            cuda_home="$(cd -- "$candidate" && pwd)"
            return
        fi
    done
    install_environment "$install_root/cuda-12.5" \
        -c nvidia/label/cuda-12.5.1 -c conda-forge cuda-toolkit=12.5
    cuda_home="$install_root/cuda-12.5"
    is_cuda125 "$cuda_home" || die 'CUDA installation finished without a CUDA 12.5 compiler'
}

prepare_node() {
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

checkout "$install_root/minicpm_study" "$study_repository" "$study_ref"
checkout "$install_root/minicpm_tool" "$reference_repository" "$reference_ref"
git -C "$install_root/minicpm_study" rev-parse HEAD > "$install_root/study-revision.txt"
find_python
prepare_cuda
"$with_platform" && prepare_node

setup_arguments=(--root "$install_root/runtime" --reference "$install_root/minicpm_tool" \
    --cuda-home "$cuda_home" --jobs "$build_jobs")
"$with_platform" && setup_arguments+=(--with-platform)
"$skip_models" && setup_arguments+=(--skip-models)
SPEECH_SETUP_PYTHON="$setup_python" bash "$install_root/minicpm_study/tool_pipeline/setup_cuda125.sh" "${setup_arguments[@]}"

printf '\nInstallation ready in %s\nStart services in separate terminals:\n' "$install_root"
"$skip_models" || printf '%q\n' "$install_root/runtime/bin/start_native.sh"
printf '%q\n' "$install_root/runtime/bin/start_runtime.sh"
"$with_platform" && printf 'SPEECH_STUDY_PORT=8080 %q\n' "$install_root/runtime/bin/start_study.sh"
"$skip_models" || printf 'Study settings: %s\n' "$install_root/runtime/run-settings.json"
