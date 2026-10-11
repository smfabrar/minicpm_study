# NVIDIA server setup (CUDA 12.5)

Clone `minicpm_study/` and the reference `minicpm_tool/` as adjacent repositories on the server, following the [root README](../README.md). Run the commands below from `minicpm_study/`, which contains `tool_pipeline/`, `speech_contracts/` and `study_platform/`. Keep the checkouts in place: installation uses editable packages and launch scripts refer to these paths. Use `--reference /path/to/minicpm_tool` if the reference lives elsewhere.

Requirements: Linux x86_64, Python 3.11 or 3.12 with `venv` support, an NVIDIA driver **555.42.02 or newer**, the **CUDA 12.5 toolkit** (including `nvcc`), network access to GitHub/PyPI/Hugging Face, and disk space for the full MiniCPM module layout, other models, Python CUDA libraries and build objects. The script checks actual GPU access. It does not install the driver or toolkit, change system CUDA alternatives, or start services during installation.

The native server is compiled with CUDA 12.5 and GCC 12. Python uses **Torch 2.6.0's cu124 wheels**, because [PyTorch publishes CUDA 12.4 and 12.6 builds for this version](https://docs.pytorch.org/get-started/previous-versions/). A newer driver runs older CUDA applications; this setup uses the [CUDA 12.5 GA driver baseline](https://docs.nvidia.com/cuda/archive/12.5.0/cuda-toolkit-release-notes/index.html). It deliberately requires that baseline instead of relying on the lower driver version allowed by restricted CUDA minor compatibility.

## Run setup

From the copied project parent directory:

```bash
# Preview the steps; this also works on a machine without a GPU.
bash tool_pipeline/setup_cuda125.sh --dry-run

# Debian/Ubuntu: install compiler/audio/build prerequisites, then build and download.
bash tool_pipeline/setup_cuda125.sh --install-system-deps
```

`--install-system-deps` runs `apt-get` through sudo when needed. Without that flag, provide `git`, `gcc-12`, `g++-12`, `ninja`, `espeak-ng` and `libsndfile1` yourself. Provide Python's venv/ensurepip support separately (for example `python3.11-venv` on Debian). Run setup as your normal account; sudo is used only for apt.

Options:

```bash
# Python 3.12 or a nonstandard toolkit/install location:
SPEECH_SETUP_PYTHON=python3.12 bash tool_pipeline/setup_cuda125.sh \
  --cuda-home /opt/cuda-12.5 --root /srv/speech-runtime --jobs 4

# Install the study backend in a separate venv and build the React/shadcn website.
# Requires the sibling study_platform directory and an existing Node 22.12+/npm.
bash tool_pipeline/setup_cuda125.sh --install-system-deps --with-platform

# Build and install dependencies first; rerun without this flag to fetch weights.
bash tool_pipeline/setup_cuda125.sh --skip-models

# Optional explicit SM targets. Every visible GPU must be covered.
bash tool_pipeline/setup_cuda125.sh --architectures '80;86'
```

GPU architectures are detected through Torch and checked against `nvcc`'s supported targets. CUDA 12.5 cannot build for newer unsupported GPU architectures; use a suitable toolkit and a different setup configuration for those machines. Two compilation jobs are the default to limit host RAM use. GPU memory must still accommodate native MiniCPM and the sidecar models; setup's CUDA allocation check does not prove that all models fit together.

## What setup creates

The default installation root is `tool_pipeline/.gpu/`:

```text
venv/                            independent model/runtime environment
study-venv/                      separate website environment, with --with-platform
sources/                         pinned native and Demo checkouts
models/cache/                    Hugging Face weights
models/model-revisions.json      frozen model commit IDs, reused on reruns
activate.sh                      runtime environment and cuBLAS/cuDNN search paths
bin/start_native.sh              native backend + official gateway/remote worker
bin/start_runtime.sh             standalone pipeline HTTP service
bin/start_study.sh               website, with --with-platform
run-settings.json                model paths, revisions, patch hash, audio and devices
requirements-resolved.txt        installed Python packages
setup-manifest.json              successful setup's hardware/build/dependency evidence
data/                            service artifacts and optional SQLite study data
logs/                            native launch logs, created when launching
```

`--skip-models` omits native launcher and settings generation on a fresh installation. It still writes the runtime launcher. Existing downloaded weights and launch files are retained on subsequent runs.

The script fetches exact native/Demo commits, applies the reference injection patch once, and rebuilds incrementally on reruns. Unexpected revisions or tracked source changes cause failure; it never resets or cleans checkouts. Use one setup process per root. Model downloads resume at their recorded revisions. Python dependency constraints retain the CUDA wheel and Transformers 4; the resolved package list records the actual installation but is not a complete cross-machine lockfile.

The Demo runs as a gateway and **remote backend worker**, so its Hugging Face inference dependencies are unnecessary. Its full requirements file pins Transformers 4.51, which conflicts with Granite. The script installs [the required gateway dependencies](scripts/requirements-gateway.txt) instead. It also installs Kokoro's English spaCy model during setup. Faster Whisper uses Torch's installed cuBLAS/cuDNN 9 libraries; `activate.sh` sets the library paths before process startup, following [Faster Whisper's GPU requirements](https://github.com/SYSTRAN/faster-whisper#gpu).

## Start and connect

Run these in separate server terminals, replacing `.gpu` if you chose another root:

```bash
tool_pipeline/.gpu/bin/start_native.sh
```

```bash
export SPEECH_RUNTIME_TOKEN='choose-your-shared-token'
tool_pipeline/.gpu/bin/start_runtime.sh
```

If installed with `--with-platform`, start the website in a third terminal:

```bash
export SPEECH_RUNTIME_TOKEN='the-same-shared-token'
tool_pipeline/.gpu/bin/start_study.sh
```

The services bind to loopback. From your laptop, forward the website port when it runs remotely:

```bash
ssh -N -L 8765:127.0.0.1:8765 your-gpu-server
```

Open `http://127.0.0.1:8765`. If the website runs locally instead, forward `8766` and configure the local study backend with the same runtime token, as described in [the platform README](../study_platform/README.md).

Paste the generated `run-settings.json` into the study's **Settings → Runtime settings (JSON)** before preparing inputs or freezing the study. Granite/Whisper use device 1 when two or more GPUs are visible, otherwise device 0. Review native device placement and available memory before collecting a study; placement must match your machine and any `CUDA_VISIBLE_DEVICES` restriction. All model and reference-audio paths refer to the GPU server.

The manifest confirms source/build choices, imports, library loading and a small real Torch CUDA computation. It does **not** claim end-to-end model readiness or measured study latency. Validate one synthesized development question under B0, B1 and B2 on the server, listen to the saved speech, inspect the tool payload/ACK and telemetry, then run the full evaluation. Setup and compilation timing are not study measurements.
