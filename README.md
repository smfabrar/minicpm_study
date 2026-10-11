# MiniCPM Study

A recorded-audio study platform for comparing MiniCPM-o 4.5 under B0 (native speech), B1 (Whisper + Granite tools), and B2 (oracle context). Live evaluation is deferred.

```text
minicpm_study/
  study_platform/     FastAPI, SQLite and React/shadcn study website
  tool_pipeline/      independent audio-in/audio-out inference pipeline
  speech_contracts/   shared request/settings dataclasses and tool schemas
  plan.md            implementation plan and verification notes
```

The website submits one audio recording and its configuration to the pipeline over HTTP. The pipeline owns model inference, tool execution, context injection, output audio and telemetry. Study storage and review remain in the website backend.

## Clone and prepare the reference

Keep the existing reference package alongside this repository:

```bash
git clone git@github.com:smfabrar/minicpm_study.git
git clone https://github.com/smfabrar/minicpm_tool.git
cd minicpm_study
```

Expected layout:

```text
projects/
  minicpm_study/
    tool_pipeline/
    speech_contracts/
    study_platform/
  minicpm_tool/
```

The reference checkout is an external dependency. Set `DUPLEX_TOOLS_SOURCE` or pass the setup script's `--reference` option when it lives elsewhere.

## GPU server

On Linux x86_64 with Python 3.11/3.12, an existing NVIDIA driver and the CUDA 12.5 toolkit:

```bash
bash tool_pipeline/setup_cuda125.sh --install-system-deps
# Also install the website in a separate environment; requires Node 22.12+/npm:
bash tool_pipeline/setup_cuda125.sh --install-system-deps --with-platform
```

Follow the [CUDA server guide](tool_pipeline/CUDA125_SETUP.md) to launch services, configure run settings and connect through SSH. The setup checks are separate from study measurements.

## Local website and code

See [study_platform/README.md](study_platform/README.md) for local installation, the study workflow and analysis. See [tool_pipeline/README.md](tool_pipeline/README.md) for standalone inference and the module reading order. Shared contracts are described in [speech_contracts/README.md](speech_contracts/README.md).

Model execution requires the GPU server. CPU protocol/lifecycle checks can run after installing the editable packages and test dependencies:

```bash
python -m pytest tool_pipeline/tests speech_contracts/tests study_platform/tests -q
```

Generated environments, model weights, study databases, recordings and runtime job artifacts are excluded from Git.
