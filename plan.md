# Speech study platform — implementation plan

## Agreed purpose

Build a local research website for the proposal in `annotated-project_proposal.pdf`. A study compares MiniCPM-o 4.5 under B0 (native), B1 (Whisper Tiny, Granite 4.0 350M, validated tools, context injection), and B2 (known-correct result injected through the same adapter). No model fine-tuning. Live evaluation is deferred.

## Application boundary

The study platform owns study configuration, a Granite-aligned tool designer, question synthesis, SQLite records, audio storage, review, analysis, and exports. The separately installable `tool_pipeline` project receives only saved audio and frozen run configuration. It independently runs the complete pipeline and returns generated audio, model text, the actual input transcript, events, timings, memory samples, and provenance. It never calls the platform to advance inference, execute tools, or inject a result. The platform observes jobs through the runtime API.

Kokoro-82M v1.0 synthesizes English questions with voice `af_heart`, speed 1.0. Save its revision, original 24 kHz audio, normalized 16 kHz mono input, and SHA-256. Synthesize once per case revision; replay identical bytes across B0/B1/B2. Preparation and answer transcription have separate traces outside the inference window. Human recordings can also be uploaded; synthesized evaluations are explicitly labeled and do not replace the proposal's 48 held-out human recordings.

## Study workflow

Dashboard → study setup → cases → tools → runs → analysis. Editable development studies become immutable evaluation snapshots when frozen. Changes require cloning a study. Every attempt retains its condition, snapshot, artifacts, telemetry, outcome, and errors. Use fresh native sessions per independent run; randomized condition order uses a saved seed. Never silently replace an attempt with a retry. Cases without tools inject no B2 fact. B2 oracle availability delay and delivery policy are explicit; report timing differences when interpreting B1/B2.

Template: 12 room questions, 12 document-search questions, 12 calculations, 12 no-tool questions; 48 cases × 3 conditions = 144 runs per repetition. Failed and silent attempts remain in denominators; unreviewed runs are visible. Manual scoring assesses audible answers; model text is not a substitute for generated speech.

## Tools

Use Granite's `type: function` JSON schema and tokenizer chat template. Initially expose one required bounded string parameter per tool, matching the reference controller contract, with no extra properties. Register tools dynamically; routing must not depend on three hard-coded names. Support fixed room records/aliases, document fixtures, safe arithmetic, and argument-keyed response fixtures. Tools have declared delays and failure policies. Keep raw and normalized arguments, validation decisions, sources, exact results, and exact delivered payloads. Expected spoken answers belong only to the review data; B1 receives neither expected answers nor oracle results.

## Telemetry contract

Measure at execution sites using monotonic integer nanosecond timestamps. Spans have IDs, parents, process/thread/clock identifiers, start/end, status, and attributes. Render milliseconds without implying nanosecond accuracy. Native MiniCPM substeps require native instrumentation; unavailable metrics are null with reasons. Record queue waits and asynchronous overlap; do not sum parallel spans as elapsed duration. Keep platform/transport timings separate from runtime timings and preparation/analysis timings.

Instrument session setup, audio decoding/resampling/chunking, replay schedule, ASR inference and segment decoding, Granite prompt/tokenization/transfers/route scoring/argument generation/parsing, validation/normalization, tool delays/execution, result queue, injection boundary/submission/evaluation ACK, per-unit native send/receive, speech chunk emission, output draining/assembly, and artifact finalization. Native audio encoding/prefill/decode/vocoding remain explicitly unavailable unless the native backend emits structured timing events. Record CUDA event timing in supported PyTorch sections without synchronizing every substep; distinguish GPU execution from CPU elapsed time.

Sample CPU RSS and NVIDIA process/device GPU memory; report sample interval, observed peak, allocation counters when available, telemetry overhead, and dropped samples. Sampling does not guarantee exact transient peaks or attribution during overlapping work. Remote native memory belongs to that host and is unavailable without remote telemetry. Capture cold initialization separately. Retain model revisions, adapter and patch provenance, hardware, software versions, input hash, pacing, sample rates, prompt, and injection timing.

Default non-live audio replay is paced at original audio duration, including final silence units and bounded output drain. Record input-start/finish, first/final output audio, tool request/completion, context submission/evaluation, and response silence/failure. Answer correctness and time to relevant fact require audio review/alignment.

## Code and storage

Python 3.11/3.12, FastAPI, SQLite (WAL), React/TypeScript, Vite, Tailwind and editable shadcn component source. Backend domain dataclasses, typed repositories, a unit of work, application services, request schemas and routers have separate responsibilities. A composition root constructs dependencies. Frontend feature modules use a typed API client and query/mutation hooks. Optional model extras: Kokoro, Torch/Transformers, faster-whisper, NVIDIA NVML bindings. Reuse `minicpm_tool` contracts and safe tool/controller logic through an editable package dependency; keep the reference folder unmodified.

`study_platform/src/speech_study/` contains domain, infrastructure, services, API, artifact storage, study preparation orchestration and analysis. `tool_pipeline/src/tool_pipeline/` independently contains the job service, CLI, inference pipeline, native adapter, Whisper/Granite caller, tool execution, model preparation and telemetry. `speech_contracts/src/speech_contracts/` contains only shared request/settings dataclasses and tool schema validation. The study package has no inference or model imports. SQLite holds study/case/tool/run/review records; filesystem holds WAVs, immutable requests, JSON/JSONL traces, and ZIP exports. Files are served only from the configured artifact root. Runtime jobs survive page refresh; interrupted workers preserve evidence. Launch platform on 127.0.0.1:8765 and runtime on 127.0.0.1:8766 by default.

## Delivery tasks and acceptance

- [ ] 1. Domain and persistence: study/case/tool CRUD, immutable freeze/clone, artifact checksums and access boundaries. Verify with isolated SQLite integration tests.
- [ ] 2. Runtime contracts and telemetry: standalone job API/CLI, nested spans, memory sampler, independent execution and retained failures. Verify trace nesting, overlap, missing metrics and failure artifacts.
- [ ] 3. Real inference integration: native realtime protocol, B0/B1/B2, dynamic Granite routing, safe fixture tools, exact payload and ACK lineage. Use a protocol fixture server for transport tests; real GPU inference requires the pinned patched MiniCPM runtime.
- [ ] 4. Platform preparation and orchestration: Kokoro synthesis/cache, upload, frozen submissions, polling/recovery, output ASR, scoring and exports. Verify one audio asset reused across conditions and oracle data excluded from B1.
- [ ] 5. Browser experience: dashboard, study navigation, case and tool editors, run inspector, nested timeline, memory plot, review and condition analysis. Check workflows in a browser when available.
- [ ] 6. Verification and handoff: run complete tests, launch both services, exercise an actual job via a fixture native transport, verify UI, document real GPU setup and remaining measurement limits.

## Execution notes

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
