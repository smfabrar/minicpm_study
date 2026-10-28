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

## Deployment decision

Use `nvidia/cuda:12.5.1-devel-ubuntu24.04` with SSH launch mode on Vast.ai.
The bootstrap checks the existing driver and selected CUDA 12.5 development
files before apt or downloads. It creates independent runtime and study venvs;
the template's preinstalled PyTorch is not used. Automatic CUDA/Conda installation
and cache repair have been removed. Native CUDA 12.5 and Torch 2.6 cu124 remain
the selected project stack.

The installer defaults to `/usr/local/cuda-12.5`; an explicit `--cuda-home`
can select another complete 12.5 toolkit. Setup, update, and restart helpers use
`/workspace/minicpm-study-install/runtime` as the runtime directory. The study
website listens on 8765, the pipeline on 8766, and the native gateway on 8000.
The laptop forwards port 8080 to the server's 8765.

[installation/README.md](installation/README.md) is the single installation, update, and operating
guide. All operational scripts are under `installation/`: `install.sh` installs
and starts the stack, `update.sh` refreshes it, and `start.sh`, `stop.sh`,
`restart.sh`, and `status.sh` manage services. Helpers and constraints are in
`installation/internal/`. Package READMEs describe development and application interfaces. Prior
implementation decisions and verification records are retained in
[docs/HISTORY.md](docs/HISTORY.md).

## Swappable native tool caller (2026-10-28)

Implement the requested Qwen3-1.7B alternative inside `tool_pipeline`, using
the existing Transformers runtime. Study settings select `caller_backend`
(`granite` or `qwen3`), model, revision and device. Existing Granite settings
remain valid; Granite remains the default. Qwen always applies its native chat
template with `enable_thinking=False`. Both adapters return the existing
call/respond/invalid actions and use the same tool validation and execution.
No additional model server or agent framework is needed.

- [x] Add caller settings and compatibility resolution in `speech_contracts`.
- [x] Share model loading/generation/telemetry, add Qwen formatting/output
  handling, and select the adapter in the pipeline. Preserve model-specific
  trace names and record generic caller provenance and thinking mode.
- [x] Add a shadcn selector and caller configuration fields to study settings;
  update tool-designer wording and package documentation for both callers.
- [x] Verify settings persistence, frozen requests, parser rejection paths,
  Qwen generation arguments, tool execution and existing Granite behavior on
  the CPU. Frontend settings/tool-design tests pass as well.
- [ ] Build the frontend where npm/dependencies are available (unavailable in
  this local environment; downloading them is blocked by DNS access).
- [ ] Validate actual model quality, combined GPU memory use and latency on
  the remote GPU machine.

## Qwen 4-bit loading (2026-10-28)

Use bitsandbytes NF4 with double quantization and FP16 computation. Add
`caller_quantization: "none" | "nf4"`, defaulting to `none` so existing frozen
requests preserve their precision. NF4 requires Qwen and a CUDA caller device.
Load through Transformers with an explicit single-device map; never load a
full FP16 GPU copy first or silently fall back to another precision/device.

- [x] Add contract validation, a Settings precision selector, and persistence
  coverage through frozen requests.
- [x] Implement quantized loading and retain actual loading configuration,
  model footprint and bitsandbytes version in runtime evidence.
- [x] Include a constrained bitsandbytes dependency in GPU installation/update
  and document activation and memory limits in existing guides.
- [x] Run CPU contract/loader/lifecycle/frontend checks.
- [ ] Validate actual GPU memory, inference and quality remotely; no 12 GB fit
  guarantee is implied. Local production frontend build still requires npm and
  dependencies that are unavailable in this environment.

## Triton Python development headers (2026-10-28)

The NF4 dependency imports Triton, which compiles a Python C extension. The
bootstrap previously installed Python/venv but omitted development headers.
Install distro-default headers and check the actual runtime interpreter; if
needed, install its matching major/minor development package. Use Triton's
Debian include scheme and fail with the missing path before importing model
packages. Do not treat a generic compiler exit status as proof of missing
headers; driver-linking errors require their own diagnosis.

## Qwen bare JSON call handling (2026-10-28)

GPU evidence showed a valid bare name/arguments object rejected by the shared
tag-oriented parser. The Qwen adapter accepts this exact single-object shape
and preserves raw output and arguments, while rejecting duplicate keys,
multiple objects, extra fields and mixed prose. Tool validation remains in the
executor. The recorded argument `robotic` is not expanded to `robotic seminar`;
argument quality must be evaluated separately from format handling.

## Deferred tasks

- [ ] **Low priority — reuse Kokoro across preparation jobs.** Deferred at the
  user's request on 2026-10-28. Replace per-question process/model initialization
  with a persistent preparation worker that reuses Kokoro and voice data. Keep
  cold-load and per-question synthesis timings separate, and preserve inference
  isolation during benchmark runs. Evidence from runtime job
  `8e476b09a20645daa8dba4f64907a234` on RTX 3060: model loading 29.333 s,
  synthesis 0.650 s, total worker time 37.490 s. These are one job's measurements,
  not a general performance guarantee.

## Acceptance

- Keep the study backend independent of model execution and tool injection.
- Preserve saved input audio, settings, model revisions, events, telemetry and
  outputs for each attempt; represent unavailable measurements explicitly.
- Verify installer rejection paths, reuse of a complete toolkit, generated
  launch commands, and existing update/native-launch behavior on the CPU.
- Validate actual package installation, compilation, model initialization and
  short B0/B1/B2 speech runs on the selected GPU machine before collecting results.
  CPU fixtures do not establish GPU or model readiness.
