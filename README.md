# MiniCPM Study

A recorded-audio study platform comparing MiniCPM-o 4.5 under B0 (native speech),
B1 (Whisper + Granite tools), and B2 (oracle context). Live evaluation is deferred.

**Start with [the setup guide](installation/README.md)** for the exact Vast.ai template,
installation command, service startup, SSH tunnel, updates, and troubleshooting.
The installer requires an existing complete CUDA 12.5 development toolkit and
creates its own Python environments.

| Directory | Responsibility |
| --- | --- |
| [installation](installation/README.md) | One-command installer, updates, start/stop/restart/status |
| [study_platform](study_platform/README.md) | FastAPI, SQLite, React/shadcn website, study storage and review |
| [tool_pipeline](tool_pipeline/README.md) | Independent audio-in/audio-out model and tool execution |
| [speech_contracts](speech_contracts/README.md) | Shared request/settings dataclasses and tool schemas |

The website submits audio and configuration over HTTP. The pipeline owns model
inference, tool execution, context injection, output audio and telemetry.
`minicpm_tool` is a separately fetched reference dependency; the installer keeps
it beside this repository.

- [Tool designer](docs/TOOL_DESIGNER.md): authored Python tools and execution evidence.
- [Project plan](plan.md): study protocol, boundaries and acceptance criteria.
- [History](docs/HISTORY.md): prior implementation and diagnostic records.

Generated environments, model weights, databases, recordings and runtime artifacts
are excluded from Git. Keep the installed checkout in place: launch scripts and
editable packages reference its paths. Actual model execution requires the GPU
server; the setup guide distinguishes dependency checks from inference validation.
