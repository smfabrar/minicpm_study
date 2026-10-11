# Standalone extraction verification

The pipeline was extracted from study_platform into this independently installable project. It has its own dependencies, model extras, HTTP service, CLI, subprocess worker, native launcher and tests. Shared settings/request/schema types are supplied by speech_contracts; no study imports remain.

Verification: combined suites 27 passed / 1 socket fixture skipped. Package installation, console entry points, dependency-boundary guards and a real worker subprocess failure/artifact lifecycle were checked. Independent review found no important issues. Reference minicpm_tool source was unchanged.

Unverified here: actual GPU model execution, Kokoro generation and audible correctness. Native launcher is a source-checkout helper; its build/source validation does not prove that an old native binary was rebuilt. See README.md.

## CUDA 12.5 setup

Added `setup_cuda125.sh` with separate host/dependency/source/build/launch responsibilities and a model-environment helper. It supports optional apt prerequisites, Torch cu124, an incremental CUDA 12.5 native build, frozen model downloads, generated server launch commands and run settings. `--with-platform` installs the website backend in a distinct environment and builds the frontend. See CUDA125_SETUP.md.

Verification: combined suites **37 passed, 1 socket fixture skipped**. Ten setup checks cover dry-run side effects, unsupported/excluded GPU targets, preserved Git index/user changes, interrupted checkout recovery, model pin reuse after interruption, generated shell quoting and device/settings selection. Python compilation and shell syntax checks passed. A fresh review identified interrupted source initialization; it was fixed, verified with local Git fixtures and re-reviewed. The reference checkout remains unchanged. Ruff was unavailable locally.

Still requires the remote server: Linux package resolution, CUDA compilation, cuBLAS/cuDNN execution, real model loading/inference and optional Node frontend build. No GPU or model execution results are fabricated by these CPU checks.

## Python module readability cleanup

Organized implementation into `pipeline/`, `models/` and `service/`. `InferencePipeline` is the single run coordinator. Plain functions handle context resolution, playback and result output; `RunState` collects run data. Model loading stays lazy. The public pipeline import, CLI names, HTTP API and result JSON remain compatible; existing installations must refresh console entry points with an editable reinstall, as documented in README.md.

The combined suites passed 46 checks with one socket fixture skipped. A subsequently added core-import guard also passed with the four-check boundary suite. Full-run fixtures cover all three conditions, no-call/clarification/invalid actions, rejected arguments, missing ACKs and timeout cleanup. The existing late-oracle and in-memory native protocol checks pass. Editable installation, CLI/worker help and Python compilation passed. Independent review found no critical or important issues. Real GPU inference remains unverified locally.
