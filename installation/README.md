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

## Reusable Vast.ai template

The saved template definition is [vast/template.json](vast/template.json), using
Vast's template API field names. Its startup script is
[vast/onstart.sh](vast/onstart.sh). The template uses the exact development image,
SSH mode, private visibility, 100 GB disk, and filters for one RTX 3090 with at
least 8 allocated vCPUs, 32 GB RAM and driver 555.42.02. The application revision
is pinned to `9cf8e9b`; make sure this commit is pushed before launching.

On your **laptop**, with the Vast CLI installed and authenticated:

```bash
cd /path/to/minicpm_study
python3 installation/vast/create_template.py
```

This runs `vastai create template` with SSH mode, the exact image tag, filters,
100 GB disk and the startup script. It creates a private template; it does not
rent an instance. Use `--dry-run` to inspect the command without contacting Vast.
CLI credentials remain in your existing local configuration.
See [Vast's template guide](https://docs.vast.ai/cli/templates).

You can also use Vast's editor: paste the entire `onstart.sh` into **On-start
Script**, apply the settings above, and choose **Private** then **Create**.
The JSON is the API representation of those settings. It contains no credentials.

With this template, skip the manual installation command below. First boot runs
the installer in the background. Subsequent boots start the installed stack
without updating it. Watch provisioning over SSH:

```bash
tail -f /workspace/minicpm-study-install/logs/vast-startup.log
```

Wait for the ready message before opening the SSH tunnel. If provisioning fails,
correct the cause and rerun the template's startup script. A failed download or
installation is logged and does not announce readiness. Updates remain an explicit
`installation/update.sh` operation. Export important studies before destroying an
instance; the template uses container storage.

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

## Install and start everything

**Server:** this downloads one script, installs the website, pipeline, patched
native server and model weights, then starts all three services. Keep SSH connected
until it finishes. The installer checks the toolkit before installing packages.

```bash
(
  set -euo pipefail
  apt-get update
  apt-get install -y curl ca-certificates
  mkdir -p /workspace/minicpm-study-install/logs
  curl --fail --location --retry 3 \
    https://raw.githubusercontent.com/smfabrar/minicpm_study/main/installation/install.sh \
    --output /tmp/minicpm-study-install.sh
  bash /tmp/minicpm-study-install.sh --jobs 2 \
    2>&1 | tee /workspace/minicpm-study-install/logs/install.log
)
```

If you already cloned the repository, run `bash installation/install.sh`.
Defaults are `/workspace/minicpm-study-install` and `/usr/local/cuda-12.5`.
Use `--prefix PATH` and `--cuda-home PATH` to change them. Begin with two native
compilation jobs; increasing `--jobs` needs more allocated CPU and host RAM.

| Option | Effect |
| --- | --- |
| `--no-start` | Install everything without starting services |
| `--skip-models` | Build without downloading weights or starting services; rerun without this flag to finish |
| `--runtime-only` | Omit the study website |
| `--ref COMMIT` | Install a specific application revision |
| `--dry-run` | Describe steps without changing files |

The free-space floor is 30 GiB for a fresh full install, 10 GiB without weights,
and 5 GiB when a previous setup manifest exists. These are early checks, not
storage guarantees. `SPEECH_INSTALL_MIN_FREE_GIB` overrides the floor. Check free
space on the filesystem holding the prefix, not only `/`.

The prefix contains application/reference checkouts, optional Node, and `runtime/`.
Runtime contains the two Python venvs, native sources, models, `data/` for studies
and recordings, `logs/`, and generated configuration. `runtime/bin/` contains
internal launchers with installation-specific paths; use the public commands below.
Keep the application checkout in place because editable packages reference it.

Python 3.11/3.12 and Node 22.12+ are required. The installer selects a supported
Python and provisions Node when needed. Native revisions are pinned; some Python
dependencies, Node downloads and first-time model resolution can vary. This is
not yet a published immutable application image.

## Manage services

**Server:** all operational scripts live in `installation/`. They detach services
from SSH, wait for startup, and keep logs. A successful install already starts them.

```bash
cd /workspace/minicpm-study-install/minicpm_study
bash installation/status.sh
```

| Command | Action |
| --- | --- |
| `bash installation/start.sh` | Start the installed stack; ready services are left running |
| `bash installation/stop.sh` | Stop this installation's stack |
| `bash installation/restart.sh` | Stop and start the stack |
| `bash installation/status.sh` | Show service readiness and process IDs |
| `bash installation/update.sh` | Fetch the selected revision, refresh dependencies/builds, then start |

Start, stop, restart and status accept `[runtime-directory] [all|native|runtime|study]`.
For example, restart only native:

```bash
bash installation/restart.sh /workspace/minicpm-study-install/runtime native
```

They match processes belonging to the selected runtime directory, including old
native launchers. They refuse occupied ports owned by other processes. Concurrent
service commands are rejected. Services survive SSH disconnection; they do not
restart automatically after a machine reboot. Run `start.sh` after rebooting.

All services bind to loopback: website 8765, pipeline 8766, native gateway 8000.
Export `SPEECH_STUDY_PORT` before commands if you change the website port. For an
optional pipeline bearer token, export the same `SPEECH_RUNTIME_TOKEN` when starting
runtime and study, and when checking status. Defaults use no token.

Readiness checks cover HTTP endpoints and native worker registration. They do not
prove model initialization or audible correctness; validate a short study below.

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
and [tool designer](../docs/TOOL_DESIGNER.md) for experiment details.

## Update an existing installation

Finish or cancel active experiments first. The update stops existing services and
uses the same installer, preserving runtime data and cached weights. Native builds
are incremental; dependency and frontend checks still run. Save tracked local
changes before updating; the installer refuses to overwrite them.

**Server:**

```bash
cd /workspace/minicpm-study-install/minicpm_study
bash installation/update.sh --jobs 2
```

`update.sh` accepts the same flags as `install.sh`, including `--prefix`,
`--cuda-home`, `--ref` and `--no-start`. Repeat custom options on each update.
If migrating from a revision without `installation/`, use the downloadable install
command above with the same prefix. You do not need a manual Git checkout or
separate package/frontend updaters. Reload the browser after a successful update.

The update also installs the runtime's bitsandbytes dependency for Qwen NF4.
To reduce Qwen weight memory, clone a frozen study, select **Qwen3-1.7B** in
Settings, set **Caller device** to `cuda:0`, select **4-bit NF4** under
**Caller weight precision**, then save. Existing studies keep their previous
precision until explicitly edited. Run one B1 case before the full matrix;
quantization does not guarantee enough headroom alongside MiniCPM on 12 GB.

## Resume installation and diagnose failures

Preserve `logs/install.log` and rerun the downloaded installer with the same prefix
after correcting the reported cause. Failed setup does not proceed to startup.
A startup failure preserves service logs; components started earlier may remain
running. Use `status.sh`, fix the error, then `start.sh` or `restart.sh` as appropriate.
A manifest left by an older installation does not prove an update completed.

| Symptom | Check |
| --- | --- |
| Missing CUDA or compiler is 13.x | Verify the exact template tag and `/usr/local/cuda-12.5/bin/nvcc`; use `--cuda-home` for another complete 12.5 toolkit |
| Missing headers / dangling libraries | The selected toolkit is incomplete; use the development image. CUDA cache repair was removed |
| Disk full | `df -h / /workspace /tmp` and `df -i /workspace`; enlarge the filesystem actually holding the installation |
| Slow CUDA build | Watch build progress and available host RAM; GPU utilization does not measure compiler progress |
| SSH channel connection refused | Check `127.0.0.1:8765/api/health` on the server and the tunnel's destination port |
| Runtime cannot connect to port 8000 | Inspect native logs and restart native after correcting the failure |
| Reference WAV missing or empty | Inspect saved run settings and verify the server WAV path |
| Website unchanged | Check source revision, run `installation/update.sh`, then reload |

Service logs are `runtime/logs/native-service.log`, `runtime-service.log`, and
`study-service.log`. The native launch subdirectory contains detailed backend,
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
