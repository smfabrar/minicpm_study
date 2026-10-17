# Fresh GPU machine setup

Follow the steps in order. Commands marked **server** run inside your SSH session;
commands marked **laptop** run on your own computer. Stop at a failed step and
inspect its log before continuing.

This guide uses the repository's existing native installer with an explicitly
selected CUDA 12.5 toolkit. It bypasses the micromamba CUDA installation path
that recently failed. The proposed prebuilt application image is not published
yet. These instructions have been checked against the source; this deployment
path still requires validation on a fresh GPU server.

## 1. Choose the machine

### Recommended Vast.ai selection

Create a custom template with these settings:

| Setting | Selection |
| --- | --- |
| Image Path:Tag | `nvidia/cuda:12.5.1-devel-ubuntu24.04` |
| Version selection | Exact tag above; do not select `[Automatic]` |
| Launch mode | Interactive shell server, SSH |
| GPU | One RTX 3090, 24 GB VRAM |
| Allocated CPU / host RAM | Prefer 8 vCPUs and 32 GB RAM |
| Instance storage | Prefer 100 GB |
| Host driver | At least 555.42.02 |

This is a recommended configuration with more memory headroom than the RTX 3060,
not a claim of completed end-to-end validation on an RTX 3090. The image includes
CUDA development tools; the application, models, and native build still require
installation. The image download itself can take time on a host that has not
cached it.

In Vast's template editor, set **Image Path:Tag** and choose **Interactive shell
server, SSH**, then save and use the template to select an offer. Select the
exact version rather than automatic version selection. See
[Vast's template settings](https://docs.vast.ai/guides/templates/template-settings)
and [NVIDIA's published image tags](https://gitlab.com/nvidia/container-images/cuda/-/blob/master/doc/supported-tags.md).

The offer's **Max CUDA** value must support this toolkit, but that field alone
does not establish which toolkit is installed inside the selected image. A host
advertising CUDA 12.6 or 13 can run this older image with a compatible driver.
Verify the driver and actual toolkit after connecting. With this template,
skip the apt CUDA installation in step 3 if its verification block passes.

### General requirements

- Ubuntu 22.04 or 24.04, Linux x86_64, with root or sudo access.
- NVIDIA GPU supported by the current CUDA 12.5 / Torch 2.6 cu124 stack.
  RTX 3060 is the current target; this guide does not establish support for
  Blackwell/RTX 50-series GPUs.
- Existing NVIDIA driver **555.42.02 or newer**, as required by this installer.
- Prefer at least **80 GB storage** for installation and recordings. This is a
  planning allowance, not a measured minimum. The installer requires 30 GiB
  free before a full installation; temporary extraction can require more space.
- Prefer at least **16 GB host RAM**, using two native compilation jobs initially.
  GPU memory fit must be checked with actual model inference.
- Access to GitHub, NVIDIA's package repository, PyPI, PyTorch, and Hugging Face.

A template with a complete CUDA **12.5 development toolkit** can skip the toolkit
installation in step 3 after verification. A runtime-only image is insufficient
for compiling the native server.

## 2. Connect and inspect the server

**Laptop:** substitute the SSH host and port provided for the new instance.

```bash
ssh -p SSH_PORT root@SSH_HOST
```

**Server:** use Bash. The server commands below assume root, as in Vast's default
SSH login. On a server using another account, enter an authorized root shell with
`sudo -i` first.

```bash
bash
if [ -f /etc/vast-agents-guide.md ]; then
  cat /etc/vast-agents-guide.md
fi
cat /etc/os-release
uname -m
nvidia-smi
python3 --version
mkdir -p /workspace
df -h / /workspace /tmp
df -i /workspace
free -h
```

The bare CUDA image may not yet include Python. If `python3 --version` reports
that it is missing, step 4 installs Ubuntu's Python and venv support.

Check the filesystem containing `/workspace`, even if `/` has plenty of space.
Use a larger mounted volume throughout this guide if `/workspace` is too small.
The CUDA label in `nvidia-smi` describes driver capability; the selected compiler
version is checked separately below.

## 3. Provide a complete CUDA 12.5 toolkit

**Server:** if `/usr/local/cuda-12.5` already contains a complete development
toolkit, skip the installation block and run the verification block.

Otherwise install NVIDIA's toolkit-only package. This block supports Ubuntu
22.04 and 24.04 and exits on other distributions. Run it as one block:

```bash
(
  set -euo pipefail
  source /etc/os-release
  case "${ID}:${VERSION_ID}" in
    ubuntu:22.04) cuda_repo=ubuntu2204 ;;
    ubuntu:24.04) cuda_repo=ubuntu2404 ;;
    *) echo 'This guide requires Ubuntu 22.04 or 24.04.' >&2; exit 1 ;;
  esac
  test "$(uname -m)" = x86_64
  apt-get update
  apt-get install -y ca-certificates curl git python3-venv
  curl --fail --location --retry 3 \
    "https://developer.download.nvidia.com/compute/cuda/repos/${cuda_repo}/x86_64/cuda-keyring_1.1-1_all.deb" \
    --output /tmp/minicpm-cuda-keyring.deb
  dpkg -i /tmp/minicpm-cuda-keyring.deb
  apt-get update
  apt-cache policy cuda-toolkit-12-5
  apt-get install -y --no-install-recommends cuda-toolkit-12-5
)
```

`cuda-toolkit-12-5` installs the versioned development toolkit without including
the NVIDIA driver. Use that package name, rather than `cuda` or `cuda-12-5`, which
include driver packages. See [NVIDIA's installation instructions and package definitions](https://docs.nvidia.com/cuda/archive/12.5.1/cuda-installation-guide-linux/index.html#meta-packages).
This selects the 12.5 package series; it is not a complete transitive package lock.
If apt reports no installation candidate or a repository error, stop and retain
the output instead of falling back to the failed micromamba repair.

**Server — verify:**

```bash
(
  set -euo pipefail
  /usr/local/cuda-12.5/bin/nvcc --version
  test -f /usr/local/cuda-12.5/targets/x86_64-linux/include/cuda_runtime.h
  test -f /usr/local/cuda-12.5/targets/x86_64-linux/include/cuda.h
  test -f /usr/local/cuda-12.5/targets/x86_64-linux/include/cublas_v2.h
  test -f /usr/local/cuda-12.5/targets/x86_64-linux/lib/libcudart.so
  test -f /usr/local/cuda-12.5/targets/x86_64-linux/lib/libcublas.so
  echo 'CUDA development files found.'
)
```

Expect `release 12.5` and the final confirmation. `test -f` also rejects dangling
library symlinks. Leave an existing CUDA 13 installation in place: the following
commands select CUDA 12.5 by its explicit path.

## 4. Clone the repository and run installation

**Server — fresh checkout:**

```bash
apt-get update
apt-get install -y git python3 python3-venv
mkdir -p /workspace/minicpm-study-install
git clone https://github.com/smfabrar/minicpm_study.git \
  /workspace/minicpm-study-install/minicpm_study
cd /workspace/minicpm-study-install/minicpm_study
git log -1 --oneline
```

If the repository requires authentication, use your configured Git credentials
or its SSH clone URL. If this checkout already exists, inspect it and follow the
resume section rather than cloning over it.

**Server — validate the toolkit using the repository's checker:**

```bash
python3 tool_pipeline/scripts/cuda_toolkit.py check /usr/local/cuda-12.5
bash install.sh --dry-run \
  --prefix /workspace/minicpm-study-install \
  --cuda-home /usr/local/cuda-12.5 --jobs 2
```

**Server — install and save the full log:**

```bash
(
  set -euo pipefail
  cd /workspace/minicpm-study-install/minicpm_study
  study_revision=$(git rev-parse HEAD)
  mkdir -p /workspace/minicpm-study-install/logs
  bash install.sh \
    --prefix /workspace/minicpm-study-install \
    --ref "$study_revision" \
    --cuda-home /usr/local/cuda-12.5 \
    --jobs 2 \
    2>&1 | tee /workspace/minicpm-study-install/logs/install.log
)
```

This pins the application checkout to the commit you just inspected. The script
fetches the pinned `minicpm_tool` reference, installs the separate Python
environments, builds native MiniCPM and the frontend, and downloads models.
Its remaining dependency ranges and first-download model resolution still mean
the full installation is not locked across machines.

Keep the SSH session connected while installation runs. CUDA compilation can
take substantial time. Begin with two jobs; raise the count only after checking
available host memory and CPU allocation. Do not launch a second installer for
the same directory.

## 5. Confirm installation completed

**Server:**

```bash
(
  set -euo pipefail
  run=/workspace/minicpm-study-install/runtime
  test -s "$run/setup-manifest.json"
  test -s "$run/run-settings.json"
  test -x "$run/bin/start_native.sh"
  test -x "$run/bin/start_runtime.sh"
  test -x "$run/bin/start_study.sh"
  "$run/venv/bin/python" -m pip check
  "$run/study-venv/bin/python" -m pip check
  cat "$run/run-settings.json"
)
```

On a fresh installation, continue only after setup finishes successfully and
these checks pass. A manifest left by an older installation does not prove a
failed update succeeded. Model inference readiness is checked in step 9.

## 6. Start all three services from one server terminal

All services use loopback addresses. Run this once after successful installation;
repeating it while services are already running creates port conflicts.

**Server:**

```bash
run=/workspace/minicpm-study-install/runtime
mkdir -p "$run/logs"

nohup "$run/bin/start_native.sh" \
  > "$run/logs/native-service.log" 2>&1 </dev/null &

nohup "$run/bin/start_runtime.sh" \
  > "$run/logs/runtime-service.log" 2>&1 </dev/null &

nohup env SPEECH_STUDY_PORT=8765 "$run/bin/start_study.sh" \
  > "$run/logs/study-8765.log" 2>&1 </dev/null &
```

This avoids depending on multiple SSH windows, which may attach to the same
provider-managed tmux session. `nohup` keeps the services running after SSH
disconnects; it does not restart them after a machine reboot.

| Service | Server address | Log under `runtime/logs/` |
| --- | --- | --- |
| Study website | `http://127.0.0.1:8765` | `study-8765.log` |
| Tool pipeline | `http://127.0.0.1:8766` | `runtime-service.log` |
| Native gateway | `http://127.0.0.1:8000` | `native-service.log` and native launch subdirectory |

## 7. Check the services before opening a tunnel

**Server:**

```bash
run=/workspace/minicpm-study-install/runtime
tail -n 60 "$run/logs/native-service.log"
tail -n 30 "$run/logs/runtime-service.log"
tail -n 30 "$run/logs/study-8765.log"
curl --fail --max-time 5 http://127.0.0.1:8765/api/health
curl --fail --max-time 5 http://127.0.0.1:8766/health
curl --fail --max-time 5 http://127.0.0.1:8000/health
```

Allow startup time and repeat the health checks if processes are still starting.
If a process exits, inspect its log. A healthy gateway does not establish that
the native model can initialize; step 9 exercises that separately.

These examples use the fresh default of no pipeline token. If you configure
`SPEECH_RUNTIME_TOKEN`, export the same value before starting the runtime and
study services, and supply its bearer token when querying the runtime directly.

## 8. Open the website from your laptop

**Laptop — a new local terminal:**

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -p SSH_PORT root@SSH_HOST \
  -L 8080:127.0.0.1:8765
```

Use the current instance's SSH host and port. Open **http://127.0.0.1:8080** on
your laptop. Leave this tunnel running. With `-N`, no remote shell prompt is
expected.

If SSH prints `channel ... Connection refused`, run the server-side website
health check in step 7. The forwarding destination must be server port **8765**.
If local port 8080 is occupied, use `-L 8081:127.0.0.1:8765` and open local port
8081. Do not run `/workspace/...` launcher commands on your laptop.

## 9. Configure a study and run a small experiment

**Server:** display the generated settings.

```bash
cat /workspace/minicpm-study-install/runtime/run-settings.json
```

In the website, create a study and paste the complete object into its runtime
settings. Save, reload, and confirm the values remain present. Use each JSON key
once; a duplicate empty `reference_audio` can overwrite the actual path.

The reference voice field should contain:

```text
/workspace/minicpm-study-install/runtime/sources/MiniCPM-o-Demo/assets/ref_audio/ref_en_dlc_1.wav
```

This is a WAV on the pipeline server used to condition the native output voice.
It is separate from the question audio prepared by Kokoro. Confirm it exists:

```bash
ls -lh /workspace/minicpm-study-install/runtime/sources/MiniCPM-o-Demo/assets/ref_audio/ref_en_dlc_1.wav
```

Use the generated device settings. For one visible GPU, expect `cuda:0` for
Granite/Kokoro and Whisper device index `0`.

1. Add one short textual question and prepare its audio. Listen to the result.
2. Configure the case's tool and oracle information as appropriate.
3. Run B0, then B1, then B2. Inspect output recordings, transcription, operation
   logs, telemetry, and tool-context evaluation acknowledgements where applicable.
4. Confirm the results before queuing a larger study.

## Resume or diagnose a failed installation

Keep the original install log. For the unresolved micromamba cache failure, see
[the investigation](INSTALLATION_INVESTIGATION.md). This guide selects
`/usr/local/cuda-12.5` explicitly; it does not repair the old managed CUDA prefix.

If bootstrap already prepared the checkouts and Node, and package installation or
native compilation failed, rerun the lower-level setup after correcting the
reported cause. This avoids the bootstrap's fresh-install disk floor, but still
requires enough space for the remaining work:

```bash
(
  set -euo pipefail
  cd /workspace/minicpm-study-install/minicpm_study
  mkdir -p /workspace/minicpm-study-install/logs
  PATH="/workspace/minicpm-study-install/node/bin:$PATH" \
    bash tool_pipeline/setup_cuda125.sh \
    --root /workspace/minicpm-study-install/runtime \
    --reference /workspace/minicpm-study-install/minicpm_tool \
    --cuda-home /usr/local/cuda-12.5 \
    --with-platform --jobs 2 \
    2>&1 | tee /workspace/minicpm-study-install/logs/setup-resume.log
)
```

If bootstrap failed before preparing Node or the reference checkout, resume step
4 instead. On a new shell, recreate any variables used in commands. Do not remove
model caches or study data to repair toolkit files.

For a failed native service after installation, inspect its logs, correct the
cause, then use the existing restart helper:

```bash
cd /workspace/minicpm-study-install/minicpm_study
bash tool_pipeline/restart_native.sh /workspace/minicpm-study-install/runtime
```

This restarts the native stack only. Runtime and study-service failures have
their own logs. Save the study checkout commit, `setup-manifest.json`, and the
relevant log when reporting a failure.
