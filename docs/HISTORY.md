# Historical implementation and installation notes

These are records of earlier changes and investigations, not current installation
instructions. Commands, dependency choices, test counts, and paths below describe
their original revisions. Follow [SETUP.md](SETUP.md) for current server operations.

## Implementation log

2026-10-11: User approved the design and explicitly requested implementation and `plan.md`. Implement inline in a new `study_platform` directory; workspace root is not a Git repository, so no worktree is needed. Do not deploy to Sites: the agreed application requires local filesystem/SQLite and a GPU runtime. Preserve existing reference source. Do not substitute fabricated measurements or synthetic audio tones for model inference.

2026-10-11 implementation steering: The user explicitly chose FastAPI, shadcn frontend components, dataclasses, repositories and services, and waived test-first development. These supersede the earlier browser ES-module fallback. Implementation uses React/TypeScript with a Node build. Network restrictions prevented npm installation/build and optional agent-skill installation in this environment. CPU integration checks follow implementation; GPU verification remains on the remote server.

Implementation status: tasks 1–4 implemented with CPU boundary verification. Task 5 frontend source implemented and syntax/import checked; production build and browser verification remain pending. Task 6 remote setup, native launcher and CPU protocol fixture supplied; actual GPU/native/TTS execution remains pending. See study_platform/README.md and study_platform/PROGRESS.md for commands and evidence. No study measurements have been fabricated.

## Standalone tool pipeline extraction

The tool pipeline must also be a separately installable project, outside the study backend. Extract it to sibling `tool_pipeline/`, with its own package, dependencies, service/CLI entry points, tests and native launcher. `study_platform/` retains only its HTTP client and study orchestration. A small standard-library-only `speech_contracts/` package contains request/settings dataclasses and tool-definition/schema validation; it contains no model execution, database or service code.

Tasks: (1) extract contracts and inference implementation, (2) remove every pipeline/model import and model dependency from study_platform, (3) update independent installation/deployment documentation, (4) run both suites and isolation checks proving each application loads without the other's package. Preserve existing SQLite and artifact formats and the existing HTTP API. Keep remote GPU/model validation limitations explicit.

Extraction implemented: the old `speech_study.runtime` and model preparation modules were removed, runtime entry points moved to `tool-pipeline`, model dependencies removed from `speech-study`, and both projects retain the existing HTTP protocol and storage formats. Independent installation and import-blocking checks verify neither executable project requires the other.

Standalone extraction acceptance: 27 CPU checks passed, 1 socket fixture skipped; console entry points and independent import guards passed. Fresh package review found no important issues. The HTTP API, SQLite records and audio artifacts keep their existing formats; no data migration is required.

## CUDA 12.5 server setup

Add a noninteractive Linux x86_64 setup command for an existing NVIDIA driver and CUDA 12.5 toolkit. Keep host checks, dependency installation, source/build preparation, model downloads and launch generation separate. Use Python 3.11/3.12, GCC 12 and PyTorch 2.6.0 cu124; preserve Granite-compatible Transformers 4 and the official Demo's remote backend mode. Check actual CUDA allocation and GPU architecture support. Freeze model commits on first download and reuse them after interruption. Retain compiler/build choices, patch hash, hardware and resolved dependencies in a setup manifest.

Generate separate native/runtime launch commands and validated study settings. Optionally install the website in its own environment and build the React/shadcn frontend when Node 22.12+/npm are available. Do not automatically change GPU drivers, start services or report setup checks as inference measurements. Verify command parsing, dry-run behavior, safe reruns, source-change rejection and generated launch commands locally; full build, dependency resolution and real model execution remain remote GPU checks.

Setup implemented in tool_pipeline/setup_cuda125.sh and scripts/. Acceptance: 37 combined CPU checks passed, 1 socket fixture skipped; Python compilation, shell syntax, dry-run without writes and clean reference checkout verified. Independent review's interrupted-checkout finding was fixed and re-reviewed. CUDA compilation, remote dependency resolution, optional frontend build and actual model inference remain unverified here.

## Readability cleanup inside tool_pipeline

The user requested simpler code organized as Python modules. Keep one InferencePipeline entry point and three small subpackages: pipeline (run sequence, context, playback, results), models (Granite, Whisper, MiniCPM, preparation), and service (HTTP API, jobs, worker, files). Use plain functions for playback and condition-specific context work, with one dataclass for collected run state. Avoid new abstract interfaces, strategy hierarchies or controller layers.

- [x] Move existing model and service code into the named subpackages; update imports and executable entry points.
- [x] Make InferencePipeline.run read as initialize/infer, finalize, save; isolate B1/B2 context work and the bounded playback loop.
- [x] Preserve B0/B1/B2 behavior, timing events, timeout/failure artifacts, result JSON and the study HTTP boundary.
- [x] Verify existing suites plus full-run fixtures for no-call, rejected tools, late context, missing ACKs and timeout. Update the pipeline README with a short reading order and diagram.

Cleanup verification: combined suites passed 46 checks with one socket fixture skipped, followed by all four import/worker boundary checks passing after adding the core-without-service import guard. Editable package installation, both console entry points, worker module invocation and compilation passed. Independent review found no critical or important issues. GPU/model execution remains a remote check.

## Repository organization

Moved tool_pipeline, speech_contracts and study_platform into the minicpm_study repository root. The existing minicpm_tool reference remains an adjacent external checkout. Updated reference discovery, setup defaults and installation documentation for this layout. The requested remote is git@github.com:smfabrar/minicpm_study.git. Generated environments, model weights, study databases and recordings remain excluded from version control.

Relocation verification: 47 CPU checks passed, one socket fixture skipped. Editable installations and console commands were refreshed for the moved environment; compilation, setup dry-run and discovery of the adjacent reference checkout passed. GitHub publishing requires working network/DNS access.

## Single-file bootstrap

Add a root install.sh that can be downloaded with wget and executed on the user's Ubuntu/Debian GPU machine. Default to the full website plus runtime and model downloads. Download the study checkout and pinned reference, install apt prerequisites, reuse Python 3.12 or prepare a local Python, install Node when missing, and prepare CUDA 12.5 in an isolated prefix when the host only has CUDA 13. Delegate package/model/native setup to the existing setup command. Expose a dry-run and runtime-only/skip-models options. Allow the website port to be selected through SPEECH_STUDY_PORT for the user's 8080 SSH tunnel. Record the study source revision and verify bootstrap control flow locally; real network/GPU installation requires server validation. Publishing is required before wget can retrieve the new script from GitHub.

Implemented. Twelve setup/bootstrap CPU checks passed, including local-Git downloads, CUDA 13 detection and local toolkit dispatch, verified fixture Node download, safe reruns with generated untracked files, rejection of tracked source edits, paths containing spaces and the generated website's port-8080 invocation. Bash syntax, Python compilation and Git whitespace checks passed. Independent review found no material issue. Actual apt/download/Conda resolution, CUDA compilation, 12 GB GPU memory fit and speech inference remain remote validation.

Disk failure follow-up: the user's df output shows the 10 GB /workspace mount is full, while / has 18 GB free. Installation files are on /workspace. Added an early destination-filesystem capacity check (30 GiB free for a full installation, 10 GiB without weights, explicit environment override), disabled pip caching, and placed download temporary files under the installation prefix. These changes report the actual storage constraint before new downloads; they cannot expand the user's volume. Recommend a 50–60 GB installation volume and rerun with the same prefix after allocating space.

Verification: all 13 targeted setup/bootstrap checks passed; Bash syntax, Python compilation and Git whitespace checks passed. Independent review found no material issue. The capacity floor is preventive, not a measured guarantee of full-stack size.

## GPU question preparation

Add an explicit `tts_device` setting for Kokoro question synthesis. Keep CPU as the default for existing studies and generate CUDA placement in new GPU installations. The pipeline worker moves the Kokoro model to the selected device, runs in float32 inference mode, and synchronizes CUDA within device setup, model loading and synthesis spans. Save the actual device in audio provenance and distinguish GPU synthesis from existing CPU cache entries. Keep text processing and WAV storage on CPU, preparation outside inference timing, and all model execution outside the study backend. Verify configuration, cache behavior and worker device selection locally; real GPU latency and audio quality require the remote server.

Implemented. The full local CPU suite passed 67 checks with one sandbox socket fixture skipped. Device placement, unavailable-device errors, provenance, completed spans, WAV formats, settings persistence and cache separation were checked using model doubles. Five preparation checks passed again after making their audio dependencies optional for test collection. Python compilation and Git whitespace checks passed; independent review found no material issue. CUDA execution, audio quality and measured GPU speed still require remote validation.

## Native snapshot path correction

The remote backend log shows session initialization trying to load `blobs/tts/MiniCPM-o-4_5-tts-F16.gguf`, which does not exist. The launcher resolved the main model's Hugging Face snapshot symlink to its hash-named blob and broke native companion-module discovery. Preserve the absolute snapshot filename for the model argument while resolving the other launcher paths as before. Verify absolute and relative snapshot paths with real filesystem symlinks and retain ordinary-file behavior. Only the Python launcher needs updating and the native stack restarting; downloaded weights and the compiled CUDA binary can be reused.

Verification: 16 launcher/setup/bootstrap checks passed, including three path regression checks using actual symlinks. Python compilation and Git whitespace checks passed, and independent review found no significant issue. This verifies launcher argument handling; native initialization on the GPU server still needs a new run.

## Native restart helper

Provide a standalone `tool_pipeline/restart_native.sh` for the existing GPU installation, plus a generated wrapper under each new installation's `runtime/bin`. Match native processes by installation paths, include descendants and orphaned services, stop them with bounded termination waits, and start the existing native launcher through nohup. Keep study/runtime services running, guard concurrent restarts, preserve the previous service log, and report startup based on the new launcher's own manifest. Startup health does not prove successful model session initialization.

Implemented. Twenty targeted restart/launcher/setup/bootstrap checks passed. Four restart checks passed again after excluding historical manifests from readiness. Process ownership and zombie handling use explicit process doubles; shell startup, failed-launch diagnostics, previous-log preservation and locking were exercised with local process fixtures. Bash syntax, Python compilation and Git whitespace checks passed. Independent review found no remaining blocking issue. Actual Linux process termination and GPU startup require remote execution.

## Faster Whisper audio-decoder compatibility

The reported `metadata_errors` keyword failure matches Faster Whisper's upstream issue 1589: released 1.2.1 still passes that argument to `av.open`, and PyAV 19 removed it. Constrain the model extra and GPU installer to `av>=11,<19`, record PyAV in run software provenance, and document a wheel-only dependency repair for the existing runtime environment. New pipeline jobs spawn fresh workers and load the corrected package; neither native CUDA rebuilds nor model downloads are needed. Remote package installation and audio decoding remain to be verified on the server.

Verification: 22 targeted setup/bootstrap/pipeline checks passed. Dependency-specifier checks confirm both installation paths allow PyAV 18.1.0 and reject 19.0.0; the software provenance field is present. Python compilation and Git whitespace checks passed. Independent review found no significant issue. These checks verify configuration and pipeline behavior with CPU fixtures, not installation or audio decoding on the remote machine.

## Apply updates from repository configuration

Add `tool_pipeline/update_runtime.sh` so the existing GPU installation applies the repository's model dependencies and CUDA constraints without manual version edits, native rebuilding or model downloads. Check dependency consistency, decode a temporary PCM WAV with Faster Whisper, and refresh the installed dependency list. Run the same decoder check during full setup so future incompatible decoder installations fail during verification. Commit and push the update, then provide fetch/checkout/update commands for the remote installation.

Verification: 17 targeted updater/setup/bootstrap checks passed. Local fixtures check committed dependency dispatch, environment activation, fail-fast behavior, temporary WAV handling and propagation of incompatible-decoder errors. Bash syntax, Python compilation and Git whitespace checks passed. Independent review found no significant issue. Package installation and real Faster Whisper decoding require remote execution; publishing is subject to GitHub connectivity.

## Reference-audio failure diagnostics

The repeated reference-audio failure needs the affected runtime job's saved setting, because the previously displayed study configuration had a nonempty path and that file was confirmed present. Improve native validation errors to distinguish an empty saved setting from a missing file, and include the checked path and runtime hostname. Preserve submitted settings and require a new run after configuration edits. Request a read-only inspection of the actual failed job before deciding on a configuration or filesystem repair.

The user's read-only inspection confirmed that the affected B2 job saved `reference_audio` as an empty string. Correct that study's configuration and create a new run; keep the failed request unchanged as evidence. Twelve native-transport/study checks passed, one socket fixture was skipped, and three reference-error subtests passed. Python compilation and Git whitespace checks passed. No remote configuration or filesystem was changed by the agent.

## Study settings save feedback

The user reports that a corrected reference path reverts after reloading. Local API reproduction saved the path and preserved it after recreating the backend. The existing frontend only reports failures through temporary toasts and gives no save confirmation. Add a separate reference-path field backed by the same JSON state, a visible submit button, persistent inline errors, duplicate-key validation, and a fresh server read before confirming a save. Keep frozen-study edits locked and prevent editing during a save. Extract the form into its own feature module and provide a source-controlled frontend rebuild helper. Remote browser behavior still needs verification; ask the user what happens when clicking Save rather than assume the backend loses the field.

Implemented. All 11 study backend checks passed, including per-study reference persistence across backend recreation and forwarding the saved path to all three conditions. Six settings helper cases passed in V8 after removing type annotations, covering duplicate/escaped keys, quoted text, malformed setting structure and readback verification. Bash syntax, Python compilation and Git whitespace checks passed. Independent review found no blocking issue. Node/npm and a connected browser are unavailable here, so the actual frontend test runner, TypeScript/Vite build and live save lifecycle require the server rebuild helper and browser verification. The original remote save failure is not yet reproduced.

## Study exports, reusable Python tools, and operation logs (2026-10-13)

Goal: export a complete study archive, remove individual studies, share tool designs between studies, execute authored Python functions in the independent runtime, and inspect queued work.

Architecture: keep dataclasses, repositories, and services in the FastAPI study application. Store reusable tool templates in SQLite; attaching a template copies its definition into a study so frozen experiments remain reproducible. Only `tool_pipeline` executes Python tools, in a separate process with validated JSON arguments, a deadline, and captured output. Granite selects the function and generates arguments; it never generates executable source.

- [x] Extend shared tool definitions with JSON Schema parameters, Python source, argument grounding, and execution timeout. Keep the existing fixtures backward compatible. Provide a general Python editor; do not add named datetime or file-search tools.
- [x] Add Python execution to `tool_pipeline`, record source/arguments/results/stdout/stderr/timing in run artifacts, and show required arguments in Granite routing options. Check zero-argument tools, invalid arguments, failures, and timeouts without GPU inference.
- [x] Add a tool-library dataclass/repository/service and CRUD/attach endpoints. Copies can be added to any draft study; editing a library entry does not change existing study copies.
- [x] Persist operation start time, remote job references, progress messages, and detailed logs. Expose ordered queued work and operation details, including runtime worker output. Keep all active operations visible.
- [x] Add recoverable study deletion (unless the user selects permanent deletion), reject deletion while work is active, and support restore from the dashboard.
- [x] Expand ZIP exports with a manifest of sizes and SHA-256 checksums, historical input audio, run artifacts, tool definitions/source, operation records/logs, metadata, analysis and CSV. Report unavailable artifacts rather than pretending pending runs are complete.
- [x] Add shadcn frontend tool library/editor, Python/schema fields, attach-from-library actions, operation list/details/logs, prominent Export ZIP and Delete buttons, and restore controls.
- [x] Verify backend/API/archive/Python execution behavior using CPU fixtures after implementation, check frontend types/build if Node is available, document runtime/server update commands, and review the complete change.

Review focus: old database payloads must still decode; zero-argument tools must not require a fictional query; duplicate names and invalid schemas must fail clearly; frozen studies must retain exact source and schema; deleting a study must not interrupt active work or remove shared recordings; archives must include input audio referenced by historical runs and identify missing artifacts; queued jobs and failed Python tools must retain inspectable logs.

Execution: inline implementation; follow the user's preference to implement before writing verification tests. Local GPU inference and Node build may be unavailable, and their verification limits must be reported accurately.

User clarification: datetime was an illustration of what they should be able to design themselves. Removed named tool examples and their creation buttons. New tools start with an unnamed Python function scaffold and an editable parameter schema. There are no built-in datetime or file-search tools added by this change.


Implemented the generic designer and all study-management changes. The shared schema validator deliberately supports a documented JSON Schema subset without adding third-party dependencies to contracts. New tools start unnamed with a synchronous Python scaffold; no named tools are auto-created. An authored definition is copied into a study, frozen into run requests, validated and executed only by the standalone runtime.

Verification: 106 CPU checks passed, one socket-based protocol fixture was skipped by the local sandbox, and three reference-error subtests passed. These checks include arbitrary typed arguments, zero-argument functions, actual Python execution, process timeout/cleanup, library copy/freeze/persistence, study Trash/restore and active-work guards, archive historical inputs and checksums/missing evidence, queue positions and persistent tracebacks, and authenticated bounded runtime logs. Three frontend tool-design helper checks passed in V8 after type erasure. Python compilation, Bash syntax/helper usage and Git whitespace checks passed. Node/npm, a connected browser and GPU models are unavailable locally: the TypeScript/Vite build and real inference must be checked on the server using the committed update helpers.

Independent review identified three important issues, all corrected: terminate owned Python descendants when stopping an outer runtime worker, declare missing generated output/tool artifacts in exports, and initialize the native voice from the saved reference snapshot. Regression checks cover each. Runtime process registration and shutdown now share a lock to avoid a process starting after the shutdown snapshot. The existing boundary regression's stale reference-error assertion was updated to match the earlier detailed diagnostic.

Update instructions are in study_platform/README.md. The Python-tool contract, Granite routing/generation flow, fixture versus actual file search, operation inspection, ZIP contents and Trash behavior are documented in docs/TOOL_DESIGNER.md. The new update_platform.sh updates the separate study environment and builds the frontend; the existing runtime updater applies pipeline changes. Restart both API services afterwards; a native CUDA rebuild is unnecessary.

## GPU checkout update diagnosis

The remote inspection shows HEAD at 27d0c2f, no ToolLibraryPage/OperationsPage imports or built library assets, and a 404 from /api/tools. The configured frontend directory is correct. The GPU server has not received the feature commit 2d4ac5f. The installer deliberately checks out detached FETCH_HEAD, so the earlier git pull instruction was unsuitable; corrected the study update guide to git fetch origin main followed by git checkout --detach FETCH_HEAD. Publishing from this agent still fails because GitHub DNS is unavailable; the user must push from the Mac terminal before fetching on the server. No remote processes or files were changed by the agent.

## CUDA 12.5 development payload repair (2026-10-17)

The new server finds nvcc 12.5.82 but CMake reports missing CUDA_CUDART and a nonexistent targets/x86_64-linux directory. User inspection lists libcudart entries under lib/ and installed CUDA 12.5 package records, but no cuda_runtime.h. Merely finding an nvcc version is insufficient; file entries may also be broken symlinks.

Implement a small standard-library helper in tool_pipeline/scripts/cuda_toolkit.py to validate development headers and linkable runtime/cuBLAS files for flat or target layouts. Compare installed file manifests only for packages from the pinned NVIDIA CUDA 12.5.1 channel, and use the existing managed micromamba to reinstall missing payloads at their recorded versions/builds. The bootstrap invokes this helper for creation/repair and validates before reusing a toolkit. Host preflight performs the same file check. Native CMake gets explicit toolkit root, prefix, library directories and CUDA_CUDART. Expose the helper's install command to repair the existing prefix and resume the direct setup without requiring another fresh-install disk floor or replacing other environments. Do not alter the preexisting, uncommitted native-caller work in this workspace.

Verification covers valid flat/target directories, absent headers, dangling library links, precise package selection and malformed metadata paths, bootstrap repair/rerun with cached package fixtures, and native CMake argument selection. Real package downloads and CUDA compilation remain remote checks. Update instructions are in tool_pipeline/CUDA125_SETUP.md.

Completed local verification: 26 setup/bootstrap/native-launcher/runtime-updater CPU checks passed. The bootstrap fixture covers successful first installation, reuse, missing-header detection, exact force-reinstall repair, and preservation of unrelated local edits. Bash syntax, Python compilation and Git whitespace checks passed. Independent scoped review found no actionable issue. Actual NVIDIA package repair and CUDA compilation have not run on the remote server from this agent.

## Pipeline verification notes

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

## Study verification notes

# Implementation progress

Approved specification: ../plan.md. User requested FastAPI, shadcn, clean dataclasses/repositories/services, and implementation without test-first development.

Implemented:
- React/TypeScript dashboard, case and tool designers, run history, audio review, timeline, memory chart, analysis and runtime connection UI.
- FastAPI routers/request schemas, typed domain dataclasses, SQLite repositories/unit of work, and application services.
- Immutable evaluation snapshots, cloned development studies, shared checksummed audio, seeded B0/B1/B2 matrix, reviews and ZIP export.
- Independent runtime and model implementation extracted to sibling tool_pipeline/. Study backend retains HTTP orchestration only.
- Remote setup documentation and pinned native source/patch launcher now belong to tool_pipeline/. Shared protocol DTOs live in dependency-free speech_contracts/.

Verification on 2026-10-11: 18 CPU checks passed, 1 real TCP fixture skipped because listening sockets are blocked. Python modules and native launcher compiled. Platform lifespan/health/docs, 48-case template balance, malformed-audio rejection, runtime token enforcement and invalid-job rejection passed via FastAPI TestClient. All 27 TypeScript modules parsed without syntax errors; local import/export names matched. CPU integration and in-memory transport checks can run here. Real TCP sockets, npm dependency download/build, browser interaction, Kokoro/model execution and GPU measurements remain environment-dependent and have not been claimed as observed results.

Native internal timing and native-process memory are represented as unavailable, with reasons. External timers cannot infer those measurements.

Standalone extraction: removed runtime/model source and extras from the study distribution; pipeline has its own pyproject, service/CLI, worker subprocess and tests. Platform upload tracing no longer imports inference telemetry. Existing SQLite and request payload formats are retained. See the final extraction verification below.

Extraction verification (2026-10-11): 27 checks passed across the three projects, 1 real TCP fixture skipped by the socket sandbox. All three distributions built/installed editable without network and their console scripts loaded. Fresh-process guards prove study CRUD/template generation works with pipeline/model imports forbidden, and the pipeline service/worker modules load with study imports forbidden. A real standalone worker subprocess retained telemetry and a predictable pre-GPU failure. Package review found no important extraction issues. GPU/model execution remains unverified.

## CUDA installation investigation (before explicit-image setup)

# Installation investigation — 2026-10-17

Status: source audit and supplied-log analysis complete; server cache diagnosis pending.
This document proposes changes. It does not claim an installer fix or GPU validation.

## Objective

Provide repeatable installation and recovery on rented NVIDIA GPU machines, with a
clear compatibility check before expensive downloads or compilation. Preserve the
separate study backend and tool pipeline. Unsupported machines should receive a
specific explanation before installation changes their environment.

## What the evidence establishes

1. The original CUDA prefix was incomplete. `nvcc` reported 12.5.82 and Conda
   listed development packages, but `targets/x86_64-linux` and `cuda_runtime.h`
   were absent. The listed `libcudart.so` filenames do not prove usable libraries:
   they may be dangling symlinks. CMake therefore could not find the development
   runtime it needed.
2. The repair failed inside micromamba while linking
   `cuda-cccl_linux-64-12.5.39-0.tar.bz2`. It could not obtain an extracted package
   directory that its cache validator accepted. Compilation had not started.
3. The installer previously accepted the compiler version as evidence of a
   complete toolkit. Commit `6451af4` added file validation, but its repair still
   operates in the existing environment and reuses micromamba's configured caches.
   `--force-reinstall` is not a guarantee of a new download into a clean cache.
4. The supplied RTX 3060 / driver 580 environment is not explained by an
   insufficient driver for this CUDA 12.5 profile. Newer NVIDIA drivers support
   older CUDA applications through backward compatibility.

The initiating cause of missing package files is **not yet established**. Possible
causes include interrupted extraction, missing cache payloads, filesystem limits,
or package-manager cache validation bugs. These require different remedies.

Mamba upstream reported the same linking failure in issue #4322 and merged a
stale-negative-cache fix in #4328. That is a relevant lead, not proof that this
server encountered the same bug. Its micromamba version and cache contents have
not been inspected. Direct SSH from this development environment is blocked.

Sources:

- [Mamba cache failure report](https://github.com/mamba-org/mamba/issues/4322)
- [Mamba cache validation fix](https://github.com/mamba-org/mamba/pull/4328)
- [Mamba linking/cache recovery implementation](https://github.com/mamba-org/mamba/blob/main/libmamba/src/core/transaction.cpp)
- [NVIDIA CUDA compatibility](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)

## Confirmed installer weaknesses

| Area | Current behavior | Required improvement |
| --- | --- | --- |
| Reproducibility | `install.sh` downloads latest micromamba and Node 22; Python dependencies include version ranges; model commits are resolved on first installation | Version each release with exact artifacts, hashes, package locks, model revisions, native revisions, and patch hash |
| Validation order | Full toolkit installation happens before the detailed driver check; GPU architecture detection follows Python installation | Inspect host, visible devices, driver, architecture, permissions, disk and inode availability first |
| Cache recovery | Repair reuses existing cache configuration and mutates the partially installed prefix | Inspect and record cache state; use a dedicated cache; quarantine invalid artifacts and permit one bounded refetch; preserve a usable installation |
| Completion | Some stages use directory/package presence as reuse evidence | Verify each stage's outputs and inputs before marking it complete; do not skip a stage just because its directory exists |
| Resource use | Full CUDA toolkit and source build on every fresh machine; fixed fresh-install disk floor | Ship prebuilt artifacts where possible; estimate remaining peak download, extraction, build, and model space per filesystem; bound jobs by available memory and CPU quota |
| Diagnostics | Completion manifest is written at the end; failures can precede useful provenance | Write an initial environment report and append stage logs/results, including exact tool versions, commands, cache locations, and failed validation |
| Readiness | Existing checks exercise Torch and imports, but do not validate full model inference | Report installation, service startup, and end-to-end inference readiness as separate states |

Relevant source: `install.sh`, `tool_pipeline/scripts/cuda_toolkit.py`,
`tool_pipeline/scripts/setup_cuda125.py`, and
`tool_pipeline/scripts/gpu_setup_support.py`.

## Compatibility contract

“Any NVIDIA GPU with CUDA” is too broad. Compatibility depends on GPU architecture,
driver, OS/CPU architecture, runtime libraries, and memory. A GPU can be visible to
`nvidia-smi` while an application's compiled kernels or libraries cannot run on it.

Start with a validated Linux x86_64 profile for the RTX 3060 and the current
MiniCPM pipeline. Expand the support matrix only after testing additional GPU
families. Keep the current driver floor explicit until lower versions have been
validated. Treat VRAM requirements as model/configuration measurements, not merely
as installation requirements.

Newer architectures need their own tested stack when the current compiler and
wheels do not support them. For example, native Blackwell compilation requires a
newer toolkit than the project's 12.5 profile. CUDA 12.8 introduced Blackwell
support; changing only the detected CMake architecture is insufficient.

Sources:

- [CUDA 12.5 host platform requirements](https://docs.nvidia.com/cuda/archive/12.5.1/cuda-installation-guide-linux/index.html)
- [NVIDIA Blackwell compatibility guidance](https://docs.nvidia.com/cuda/archive/12.8.2/blackwell-compatibility-guide/index.html)

## Recommended deployment design

### Primary: versioned application image for rented machines

Build an application image from a pinned NVIDIA CUDA base-image digest. Install
locked Python dependencies, compile the patched native server for the declared
GPU architectures, and build the frontend during release creation. Publish the
image by immutable digest only after GPU smoke tests pass.

For Vast, select the application image when creating the instance. This avoids
depending on nested Docker being available inside an existing rented container.
On a conventional Docker host, the NVIDIA Container Toolkit must expose the GPU.
The host still supplies the compatible NVIDIA driver.

Store model downloads, recordings, SQLite data, and logs in a separate persistent
directory. Resolve model revisions in the release manifest, verify their complete
layout, and resume interrupted downloads. Start the three existing services with
explicit ports and process supervision, and report each service's health.

The downloaded shell entry point remains a small compatibility checker and
launcher. It selects a supported release and produces an actionable failure if
the required runtime is unavailable. It must not silently switch to an untested
installation method.

Reference: [NVIDIA container runtime prerequisites](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).

### Secondary: native installation on explicitly supported Ubuntu releases

Keep one documented native path for users who cannot use the image. Install a
versioned, verified NVIDIA toolkit through a supported toolkit-only mechanism;
do not replace the machine's driver. Use the same application dependency locks
and model manifest as the image.

If micromamba remains in this path, pin its tested binary and checksum, specify
the cache location explicitly, and validate real extraction/reinstallation in
Linux integration tests. An unverified retry with a new cache is not sufficient
evidence that the current failure has been fixed.

Install releases into their final versioned directories, verify them there, and
atomically switch a launcher pointer after success. Do not rename an installed
Python/Conda environment as a promotion mechanism: embedded paths may break.
Use an installation lock to prevent concurrent mutation. Resume completed stages
only when their manifest inputs and validated outputs still match.

## Verification before claiming reliability

- Linux integration checks: first installation, unchanged rerun, interrupted
  download, corrupted archive/extracted cache, insufficient disk/inodes, and
  simultaneous installer invocation.
- GPU checks: actual CUDA operation, native model initialization, short Kokoro
  synthesis, Whisper transcription, Granite call, and one short B0/B1/B2 run with
  expected artifacts and context acknowledgements where applicable.
- Release reproducibility: rebuild from locked inputs, record artifacts and
  hashes, and test a clean machine for every claimed GPU profile.
- Recovery: keep the previous successful release usable after a failed update;
  preserve study data and provide the failed stage's report.

CPU mocks are useful for installer control flow. They cannot establish real
micromamba extraction, CUDA compilation, GPU compatibility, or model readiness.

## Immediate evidence needed from this server

Run these read-only commands on the GPU server:

```bash
base=/workspace/minicpm-study-install
"$base/bin/micromamba" --version
"$base/bin/micromamba" --no-rc --root-prefix "$base/mamba" info
printenv CONDA_PKGS_DIRS MAMBA_PKGS_DIRS CONDA_SUBDIR
df -h "$base"
df -i "$base"
```

Then inspect the actual cache locations reported by micromamba for the failed
CCCL archive, extracted payload, and package metadata. Compare checksums and file
manifests before changing or deleting them. Earlier warnings from the failed
transaction are also useful: they can identify the exact missing cache file.

This establishes whether recovery needs a verified redownload, a package-manager
version correction, filesystem remediation, or a fresh toolkit installation.
