# GPU server setup and operation

This is the single guide for installing, starting, updating, and diagnosing this
project. Commands labelled **server** run inside SSH; commands labelled **laptop**
run on your own computer. Run one installer per directory and stop at a failed
step before starting services.

## Select the Vast.ai template

| Setting | Selection |
| --- | --- |
| Image Path:Tag | `nvidia/cuda:12.5.1-devel-ubuntu24.04` |
| Version selection | Exact tag; do not choose Automatic |
| Launch mode | Interactive shell server, SSH |
| GPU | Recommend one RTX 3090 with 24 GB VRAM |
| Allocated host resources | Prefer 8 vCPUs, 32 GB RAM, 100 GB storage |
| NVIDIA driver | At least 555.42.02 |

Enter the image in Vast's custom template editor, select SSH mode, then save and
use the template when choosing an offer. NVIDIA publishes this development image;
it includes CUDA headers, libraries and the compiler. It does not include this
application or its model weights. The suggested hardware provides more memory
headroom than the RTX 3060; full model readiness still requires a real run.
Sources: [Vast template settings](https://docs.vast.ai/guides/templates/template-settings),
[NVIDIA image tags](https://gitlab.com/nvidia/container-images/cuda/-/blob/master/doc/supported-tags.md).

The image tag matters independently of the host offer's **Max CUDA** field:

| Value | What it describes |
| --- | --- |
| CUDA label in `nvidia-smi` | Host driver capability |
| `nvcc --version` | Selected CUDA compiler/toolkit |
| `torch.version.cuda` | CUDA backend of that Python environment's PyTorch |

A newer compatible driver can run this CUDA 12.5 image. The project uses native
CUDA **12.5** and installs Torch **2.6.0 cu124** in its own venv. It does not reuse
`/venv/main` or install CUDA, drivers, or Conda. Base/runtime-only CUDA images
lack required development tools. CUDA 13-only and unsupported GPU architectures
are rejected; this profile does not support RTX 50-series/Blackwell.

If you already have a server with a complete `/usr/local/cuda-12.5`, you can use
it without replacing the instance. Another toolkit location can be selected
explicitly with `--cuda-home`. There is no automatic fallback to a different CUDA.

## Connect and verify the image

**Laptop:** substitute the SSH port and host of the current instance.

```bash
ssh -p SSH_PORT root@SSH_HOST
```

**Server:** use Bash. These commands assume Vast's root login; on another host,
use an authorized root shell for package installation.

```bash
bash
if [ -f /etc/vast-agents-guide.md ]; then
  cat /etc/vast-agents-guide.md
fi
cat /etc/os-release
nvidia-smi
/usr/local/cuda-12.5/bin/nvcc --version
mkdir -p /workspace
df -h / /workspace /tmp
df -i /workspace
```

Expect Ubuntu 24.04, a visible GPU, driver >=555.42.02, and compiler release 12.5.
The installer also checks that development headers and linkable libraries exist.
It rejects an incomplete toolkit before apt or package downloads. If the version
is wrong or the path is missing, check the selected image; do not rerun a CUDA
cache repair. A missing Python on the bare CUDA image is normal: apt provides
Ubuntu's Python 3.12 and venv support during installation.

## Install

**Server:** the single downloadable entry point installs the website, pipeline,
patched native server, and models. Use at least 30 GiB free on the destination
filesystem; this floor is not a guarantee of enough space for every workload.

```bash
(
  set -euo pipefail
  apt-get update
  apt-get install -y curl ca-certificates
  mkdir -p /workspace/minicpm-study-install/logs
  curl --fail --location --retry 3 \
    https://raw.githubusercontent.com/smfabrar/minicpm_study/main/install.sh \
    --output /tmp/minicpm-study-install.sh
  bash /tmp/minicpm-study-install.sh \
    --prefix /workspace/minicpm-study-install \
    --cuda-home /usr/local/cuda-12.5 \
    --jobs 2 \
    2>&1 | tee /workspace/minicpm-study-install/logs/install.log
)
```

If you already cloned the repository, run its `install.sh` with those same
arguments. Use `--ref COMMIT` to select an application revision, `--runtime-only`
to omit the website, or `--skip-models` to defer weights. A fresh `--skip-models`
installation has no native launcher or run-settings file until setup is completed
without that flag. `--dry-run` previews the steps without changing files.

Keep SSH connected during installation. Begin with two compilation jobs; more
jobs require more host RAM and CPU allocation. Setup creates:

```text
/workspace/minicpm-study-install/
  minicpm_study/              application checkout (keep in place)
  minicpm_tool/               pinned reference checkout
  node/                      managed Node installation when needed
  logs/install.log           bootstrap/build output
  runtime/
    venv/                    pipeline, models, native gateway dependencies
    study-venv/              independent study backend environment
    sources/                 patched native source and official Demo
    models/                  saved model revisions and download cache
    bin/                     generated start/restart scripts
    data/                    study database, recordings and job artifacts
    logs/                    service logs
    activate.sh              selected CUDA and runtime environment
    run-settings.json        server paths, model revisions and GPU placement
    setup-manifest.json      successful setup's build/dependency evidence
```

Python 3.11/3.12 and Node 22.12+ are required. The bootstrap selects a supported
Python and provisions Node if needed. Native source revisions are pinned; some
Python dependency ranges, Node downloads, and initial model resolution still
vary across fresh installs. The complete stack is not yet a published, immutable
application image.

## Start services

After successful setup, run this **once on the server** from a single terminal.
All services bind to loopback. Duplicate starts will cause port conflicts.

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

`nohup` survives SSH disconnection, but does not restart processes after a reboot.
For an optional pipeline bearer token, export the same `SPEECH_RUNTIME_TOKEN`
before starting both runtime and study services. Fresh defaults use no token.

After startup, check on the **server**:

```bash
curl --fail --max-time 5 http://127.0.0.1:8765/api/health
curl --fail --max-time 5 http://127.0.0.1:8766/health
curl --fail --max-time 5 http://127.0.0.1:8000/health
```

For a token-protected runtime, its health request also needs an
`Authorization: Bearer <token>` header. These endpoints check services; they do
not prove model initialization or audible correctness.

## Open the website

**Laptop — a separate terminal:**

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -p SSH_PORT root@SSH_HOST \
  -L 8080:127.0.0.1:8765
```

Open **http://127.0.0.1:8080** and leave the tunnel running. With `-N`, no remote
shell prompt is expected. The mapping is laptop **8080** → server **8765**.
If local port 8080 is busy, use `8081:127.0.0.1:8765` and open local port 8081.

## Configure and validate a study

On the **server**, display the generated settings:

```bash
cat /workspace/minicpm-study-install/runtime/run-settings.json
```

Paste the entire object into a new study's runtime settings, save, and reload to
verify persistence. Use each JSON key once. Generated settings select GPU 0 when
one GPU is visible. They include `tts_device` for Kokoro question preparation.

The reference voice WAV is on the pipeline server:

```text
/workspace/minicpm-study-install/runtime/sources/MiniCPM-o-Demo/assets/ref_audio/ref_en_dlc_1.wav
```

It conditions the native output voice; it is separate from question audio.
Keep model paths inside their Hugging Face snapshot layout: resolving the main
GGUF into a hash-named `blobs/` path breaks companion-module discovery.

Prepare one short question and listen to the synthesized input. Configure its
tool and oracle information, then run B0, B1 and B2. Inspect recordings,
transcripts, operation logs, telemetry and relevant context acknowledgements
before queuing a larger study. An acknowledgement establishes delivery, not that
the model spoke the correct answer. See the [study workflow](../study_platform/README.md)
and [tool designer](TOOL_DESIGNER.md) for experiment details.

## Update an existing installation

Finish or cancel active experiments first. The installer uses a detached checkout:
fetch and check out the desired revision instead of running `git pull`. Preserve
any local changes before checking out another revision.

**Server:**

```bash
(
  set -euo pipefail
  cd /workspace/minicpm-study-install/minicpm_study
  git fetch origin main
  git checkout --detach FETCH_HEAD
  bash tool_pipeline/update_runtime.sh /workspace/minicpm-study-install/runtime
  bash study_platform/update_platform.sh /workspace/minicpm-study-install/runtime
)
```

The runtime updater uses the installed project venv and committed dependency
constraints, checks dependencies/audio decoding, and saves resolved versions.
The platform updater installs the study backend and rebuilds the frontend.
For only frontend changes, use `study_platform/update_frontend.sh` with the same
runtime directory. These updaters do not rebuild native CUDA or download models.

Restart runtime and study services after updating; run this in **Bash on the
server**, after the update succeeds:

```bash
run=/workspace/minicpm-study-install/runtime
pkill -TERM -f "$run/venv/bin/[s]peech-runtime" || true
pkill -TERM -f "$run/study-venv/bin/[s]peech-study" || true
```

Wait for their logs to confirm shutdown, then rerun just the runtime and study
`nohup` commands from **Start services**. Reload the browser. Source, dependency,
or patch changes to the native stack require rerunning setup/build as well.

To restart the native stack after correcting a native failure or rebuilding:

```bash
cd /workspace/minicpm-study-install/minicpm_study
bash tool_pipeline/restart_native.sh /workspace/minicpm-study-install/runtime
```

## Resume installation and diagnose failures

Preserve `logs/install.log`. Rerun the same installer and prefix after correcting
the reported cause. If bootstrap already prepared both checkouts and Node,
resume the lower-level setup without applying the fresh-install disk floor:

```bash
(
  set -euo pipefail
  cd /workspace/minicpm-study-install/minicpm_study
  PATH="/workspace/minicpm-study-install/node/bin:$PATH" \
    bash tool_pipeline/setup_cuda125.sh \
    --root /workspace/minicpm-study-install/runtime \
    --reference /workspace/minicpm-study-install/minicpm_tool \
    --cuda-home /usr/local/cuda-12.5 --with-platform --jobs 2 \
    2>&1 | tee /workspace/minicpm-study-install/logs/setup-resume.log
)
```

Enough space for the remaining work is still required. Only continue to startup
after setup succeeds. A manifest left by an older installation does not prove a
failed update completed.

| Symptom | Check |
| --- | --- |
| Missing CUDA or compiler is 13.x | Verify the exact template tag and `/usr/local/cuda-12.5/bin/nvcc`; use `--cuda-home` for another complete 12.5 toolkit |
| Missing headers / dangling libraries | The selected toolkit is incomplete; use the development image. CUDA cache repair was removed |
| Disk full | `df -h / /workspace /tmp` and `df -i /workspace`; enlarge the filesystem actually holding the installation |
| Slow CUDA build | Watch build progress and available host RAM; GPU utilization does not measure compiler progress |
| SSH channel connection refused | Check `127.0.0.1:8765/api/health` on the server and the tunnel's destination port |
| Runtime cannot connect to port 8000 | Inspect native logs and restart native after correcting the failure |
| Reference WAV missing or empty | Inspect saved run settings and verify the server WAV path |
| Website unchanged | Check source revision, run the platform updater, restart study, then reload |

Service logs are `runtime/logs/native-service.log`, `runtime-service.log`, and
`study-8765.log`. The native launch subdirectory contains detailed backend,
gateway and worker logs. For a failure report, retain these and
`runtime/setup-manifest.json`, if present, plus the checkout commit.

## Local website development

Use the [study README](../study_platform/README.md#local-application) for local
Python/frontend development. To connect that website to a remote pipeline,
forward its port from the laptop:

```bash
ssh -N -p SSH_PORT root@SSH_HOST -L 8766:127.0.0.1:8766
```

Start the local study backend with `SPEECH_RUNTIME_URL=http://127.0.0.1:8766` and
the same `SPEECH_RUNTIME_TOKEN` as the remote pipeline, if configured. The remote
pipeline still owns all model execution. This is separate from forwarding the
server-hosted website on port 8765.
