# Speech Study

A FastAPI study application with a React/TypeScript shadcn interface. Model execution lives in the separately installable sibling [tool_pipeline](../tool_pipeline/README.md) project. This backend communicates with it through HTTP and does not import it. SQLite stores studies, cases, tools, immutable run requests, and listening reviews. WAV files and traces live in an artifact directory.

B0 runs native MiniCPM-o 4.5 without tools. B1 duplicates the audio to Whisper Tiny, routes the transcript through Granite 4.0 350M, validates and executes a declared tool, then injects its result into the native session. B2 injects the saved oracle fact through the same adapter. Native MiniCPM produces the actual speech in all three conditions.

Live evaluation is deferred. The non-live protocol commits the full recording to the sidecar **after audio replay finishes**. It therefore does not measure incremental Whisper streaming or early tool selection. Paced replay is the default. Final silence is bounded by audio units, including a full post-injection drain budget. Unpaced runs are explicitly configured and should be analyzed separately.

## Local application

Use Python 3.11 or 3.12 and Node 22.12+.

```bash
cd study_platform
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e ../speech_contracts
python -m pip install -e .
cd frontend
npm install
npm run build
cd ..
speech-study --data ./data/platform
```

Open `http://127.0.0.1:8765`. FastAPI serves `frontend/dist`; `/docs` provides the API reference. For a frontend development session, run `npm run dev` in `frontend` while FastAPI runs; Vite proxies `/api`. An installed wheel can use `SPEECH_STUDY_FRONTEND=/absolute/path/to/frontend/dist`.

The frontend includes editable shadcn component source under `frontend/src/components/ui`, `components.json`, and `npm run ui:add -- component-name`. The optional shadcn agent skill was not installed here because package downloads were blocked; the application does not require that skill to run. Run `npm run format` for Prettier formatting.

## Independent GPU pipeline

Install and start the sibling [tool_pipeline project](../tool_pipeline/README.md) on the GPU server. That project owns Whisper, Granite, tool execution, native MiniCPM injection, Kokoro and output transcription. Clone `minicpm_study` and the `minicpm_tool` reference as adjacent repositories, as shown in the [root README](../README.md). A pipeline-only server installs `tool_pipeline` and `speech_contracts` without installing the study application.

For CUDA 12.5, follow the [server setup guide](../tool_pipeline/CUDA125_SETUP.md). Its optional `--with-platform` flag builds this website and installs this backend in a separate Python environment on the same server. Paste its generated `run-settings.json` into study settings before preparing or freezing inputs.

Open an SSH tunnel locally and start the study backend with the same bearer token:

```bash
ssh -N -L 8766:127.0.0.1:8766 your-gpu-server
# In a separate terminal, with the local study environment active:
export SPEECH_RUNTIME_TOKEN='your-shared-token'
speech-study --data ./data/platform
```

Runtime → Check health connects to `http://127.0.0.1:8766`. Each inference submission sends one audio recording and its saved configuration. The pipeline executes every inference step and returns output audio, events and telemetry. The study backend polls jobs and collects artifacts; it does not advance inference, execute tools or inject results.

Both projects depend on the small [speech_contracts](../speech_contracts/README.md) package for request dataclasses, settings and function schema validation. It has no third-party dependencies or execution code. The study backend's upload-normalization trace is local preparation telemetry, separate from the pipeline's inference trace.

## Conduct a study

1. Create a study. Configure native endpoint, remote reference WAV, device placement, time limits, and model revisions. Prefer immutable model revision hashes for collection.
2. Add development and evaluation cases, or load the 48-case proposal template. The template contains text prompts; it is **not** the proposal's collected human recording dataset.
3. Edit tool function names, descriptions, required string parameter, lookup fixtures, aliases, delays, and failure behavior. The displayed schema matches the Granite function schema.
4. Prepare missing inputs using Kokoro, or upload PCM WAV recordings (up to 50 MiB and five minutes). Synthesis jobs appear under Operations. Inputs retain their origin, provenance, and checksum. Changing question text clears the prepared input.
5. Try individual conditions during development. Freeze when all evaluation inputs and B2 oracle facts are ready. Freezing preserves the case/tool/settings snapshot; subsequent edits require cloning.
6. Run the full randomized B0/B1/B2 matrix. The 48-case template produces 144 attempts per repetition. Work is serialized to avoid sidecar GPU contention. A disconnected platform preserves the remote job ID; resume collection without creating a new inference attempt.
7. Listen to generated output in each run inspector, optionally transcribe it, then save the listening verdict. Output ASR is a separate analysis job. Review relevant-fact timing is relative to the output recording's start.
8. Inspect nested spans, actual tool events, exact injected text, evaluation acknowledgements, and memory samples. Export the ZIP with snapshots, audio, JSON traces, Chrome trace files, review data, and CSV.

Accuracy uses frozen evaluation-split tool-required attempts. Failed, silent, and unreviewed attempts stay in its denominator; development runs are excluded. No-tool unnecessary calls are reported separately. Latency and memory summaries use frozen evaluation attempts and should be compared only under matching pacing and configurations.

For GPU question preparation, add `"tts_device": "cuda:0"` to an editable study's settings JSON and save before queuing preparation. Existing settings without this field use CPU. Changing the device affects newly queued synthesis jobs and their cache entries; **Prepare missing inputs** keeps already attached recordings. Test with a new case, or clone a frozen study before editing. Audio provenance records the actual synthesis device. The study backend continues to submit preparation jobs to the independent pipeline service; it does not load Kokoro or CUDA.

## Code boundaries

```text
frontend/src/
  components/ui/      shadcn component primitives
  features/           dashboard, studies, cases, tools, runs, timeline, runtime
  hooks/              query/mutation coordination
  lib/                typed API client, domain interfaces, formatting
src/speech_study/
  domain/             dataclasses, settings and errors
  infrastructure/     SQLite, typed repositories, unit of work, HTTP client, queue
  services/           study rules, run orchestration, preparation, analysis/export
  api/                request schemas and FastAPI routers
  container.py        dependency composition
```

Repositories only persist entities. Services own business operations. Routers validate and delegate. `infrastructure/runtime_client.py` is the HTTP boundary to the pipeline. This distribution contains no model worker, inference pipeline, tool executor or model dependencies.

## Measurement limits and validation

Timers preserve monotonic integer nanoseconds and clock identity; the UI renders milliseconds. CUDA events measure supported Granite operations, with final synchronization. Process RSS/NVML are sampled observations, not guaranteed transient peaks. Native MiniCPM is a different process: its memory and internal encoding/prefill/decode/vocoding timings are explicitly unavailable without native instrumentation. Output text and context acknowledgement do not establish spoken correctness.

```bash
python -m pip install -e '.[dev]'
python -m pytest tests -q
python -m ruff check src
python -m ruff format src
cd frontend
npm run build
```

Local evidence: study API/persistence and package-isolation checks pass. The independent pipeline test suite verifies the native JSON transport with an in-memory fixture; its real TCP fixture is skipped when this sandbox denies listening sockets. TypeScript syntax and local imports were checked using the available compiler; package downloads were unavailable, so the production frontend build and browser interaction remain unverified here. No GPU model inference, Kokoro generation, or audible correctness result is claimed. Run those checks on the server before collecting study results.
