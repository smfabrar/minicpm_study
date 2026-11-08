# Speech Study

A FastAPI study application with a React/TypeScript shadcn interface. Model execution lives in the separately installable sibling [tool_pipeline](../tool_pipeline/README.md) project. This backend communicates with it through HTTP and does not import it. With Atlas configured, MongoDB stores metadata and GridFS stores audio, traces and logs; local files are a cache. Without Atlas configuration, the app uses SQLite and local artifacts.

B0 runs native MiniCPM-o 4.5 without tools. B1 duplicates the audio to Whisper Tiny, routes the transcript through the selected caller (Granite 4.0 350M or Qwen3-1.7B with thinking disabled), validates and executes a declared tool, then injects its result into the native session. B2 injects the configured reference (a saved oracle fact or fresh server-clock value) through the same adapter. Native MiniCPM produces the actual speech in all three conditions.

Live evaluation is deferred. The non-live protocol commits the full recording to the sidecar **after audio replay finishes**. It therefore does not measure incremental Whisper streaming or early tool selection. Paced replay is the default. Final silence is bounded by audio units, including a full post-injection drain budget. Unpaced runs are explicitly configured and should be analyzed separately.

## Local application

Use Python 3.11 or 3.12 and Node 22.12+ with npm. The platform does not need a
GPU, CUDA, model weights or the GPU installation script. It can create/edit
studies, record/upload voice, play collected recordings, review results and export
studies while the GPU runtime is offline. TTS preparation, inference and output
transcription need the separate runtime.

On an Apple Silicon Mac with Homebrew installed, install Node/npm before building
the frontend if `npm` is missing:

```bash
/opt/homebrew/bin/brew install node@22
export PATH="/opt/homebrew/opt/node@22/bin:$PATH"
node --version
npm --version
```

The versioned Homebrew package is keg-only, so its `bin` directory must be in
`PATH` ([Homebrew explanation](https://docs.brew.sh/FAQ#what-does-keg-only-mean)).
Repeat the export in terminals used for frontend work, or add that line to your
shell configuration. Node/npm are needed to build or develop the UI; the Python
backend serves the built files afterward.

```bash
# From the repository root on your laptop:
python3.11 -m venv study_platform/.venv
source study_platform/.venv/bin/activate
python -m pip install -e ./speech_contracts -e ./study_platform
cd study_platform/frontend
npm install
npm run build
cd ../..
```

### Connect your existing Atlas account

In your Atlas project, select or create a cluster. Create a **database user**
with `readWrite` access to the `minicpm_study` database; this is separate from your
Atlas website login. Add your laptop's current public IP to the project's IP
access list. Select **Connect → Drivers → Python** and copy the connection URI.
These are Atlas's [connection prerequisites](https://www.mongodb.com/docs/atlas/connect-to-database-deployment/).
Use the same database name as your existing deployment if its records are already
in Atlas. A Free cluster currently allows [0.5 GB of storage](https://www.mongodb.com/docs/atlas/reference/free-shared-limitations/);
audio and logs count toward that allowance.

From the repository root, create a private environment file:

```bash
touch study_platform/.env
chmod 600 study_platform/.env
nano study_platform/.env
```

Enter the real database credentials and cluster host in the file:

```bash
SPEECH_MONGODB_URI='mongodb+srv://DB_USER:URL_ENCODED_PASSWORD@YOUR_CLUSTER.mongodb.net/?retryWrites=true&w=majority'
SPEECH_MONGODB_DATABASE='minicpm_study'
```

Use the connection string supplied by Atlas, replacing its placeholders. Percent
encode special characters in the password. Keep the URI private; do not put it
in frontend configuration or study settings. `.env` is ignored by Git. The local
CLI does not load this file automatically, so start it as follows each time:

```bash
cd /Users/fahim/Desktop/projects/minicpm_study
source study_platform/.venv/bin/activate
set -a
source study_platform/.env
set +a
speech-study --host 127.0.0.1 --port 8765 --data ./study_platform/data/platform
```

Adjust the repository path if you clone elsewhere. Open **http://127.0.0.1:8765**
and leave this terminal running. FastAPI serves `frontend/dist`; `/docs` provides
the API reference. If a configured Atlas connection fails, startup fails instead
of silently switching to SQLite. Omitting `SPEECH_MONGODB_URI` selects SQLite.

Only one study backend should use this Atlas database at a time. Before moving
from a remote study backend to this laptop, stop the remote **study** service;
its GPU runtime/native services can remain running. Platform startup recovers
operation history and marks interrupted work, so running two study backends is
unsupported.

### Record voice and verify cloud storage

Create a draft study and add a question. Select **Record voice**, allow microphone
access, stop, preview and choose **Use recording**. Alternatively upload a PCM WAV.
Localhost supports browser microphone access without an HTTPS certificate. Saving
uploads the original recording and its normalized 16 kHz version to GridFS and
attaches the normalized input to the case. Metadata goes to MongoDB collections;
voice files go to `artifacts.files` and `artifacts.chunks`. Operation evidence uses
the `operations` GridFS bucket. No separate audio storage account is needed.

To verify recovery, stop the platform with Ctrl+C and restart against an empty
local cache, with the same loaded Atlas environment:

```bash
speech-study --host 127.0.0.1 --port 8765 --data ./study_platform/data/atlas-recovery-check
```

Check that the study appears and its voice recording plays. This verifies that
the records and WAV are recoverable without the first local cache. Keep the
original data directory until verification succeeds.

Visit `http://127.0.0.1:8765/api/health` to confirm the active storage mode:
`"storage": "mongodb-atlas-gridfs"`. If it says `local-sqlite`, the Atlas
environment was not loaded into the process that started the backend.

Existing SQLite studies do not move automatically when Atlas is enabled. To copy
them, stop the study backend, load the Atlas environment above, then run from the
repository root:

```bash
python installation/migrate_to_atlas.py --data ./study_platform/data/platform
```

Use the directory actually containing `studies.sqlite`, `artifacts/` and
`operations/`. Run this on the old GPU server instead if that is where the data
lives, before destroying it. The migration preserves the source and refuses to
overwrite differing destination records. Downloaded study ZIPs are exports; this
script migrates a platform data directory, not a ZIP.

### Delete question audio

In a draft study, select **Delete audio** beside the question's audio player and
confirm **Delete audio and artifacts**. It removes the attached recording's
original and normalized WAVs, preparation traces, TTS results/manifests, worker
logs and matching synthesis-operation records/logs from managed Atlas/GridFS and
local storage. The question remains available for recording or upload again.
Deleting a question also cleans up its attached audio bundle first.

Files referenced by another question, study or clone are retained until the last
reference is removed. Frozen studies and audio referenced by saved run requests
or snapshots cannot be changed this way; use permanent study deletion to remove
that run history and its artifacts. Queued/running work for the question must
finish first. If storage cleanup fails partway, the audio stays marked for
cleanup; choose **Retry audio deletion**. Replacing, editing or running that input
is blocked until cleanup finishes.

This action affects platform-managed files, including GridFS chunks and path
records. Independent GPU job caches and copies on other offline computers are
outside the platform's cleanup.

### Connect a GPU runtime later

On your laptop, open a separate terminal:

```bash
ssh -N -o ExitOnForwardFailure=yes -p SSH_PORT root@SSH_HOST \
  -L 8766:127.0.0.1:8766
```

Keep the study platform's runtime URL at `http://127.0.0.1:8766` and check runtime
health. For an authenticated runtime, export its `SPEECH_RUNTIME_TOKEN` before
starting the local backend. The GPU server needs only native and runtime services
for this arrangement. Native URL, model devices and the reference WAV in study
settings still refer to that server. Runtime outputs become durable in Atlas
when the local platform collects them; keep it running until collection finishes.

For a frontend development session, run `npm run dev` in `study_platform/frontend`
while FastAPI runs; Vite proxies `/api`. An installed wheel can use
`SPEECH_STUDY_FRONTEND=/absolute/path/to/frontend/dist`.

The frontend includes editable shadcn component source under `frontend/src/components/ui`, `components.json`, and `npm run ui:add -- component-name`. Run `npm run format` for Prettier formatting.

## Independent GPU pipeline

Follow the [setup guide](../installation/README.md) to install and start both applications
on the GPU server. The pipeline owns Whisper, the caller, tool execution, native
MiniCPM injection, Kokoro and output transcription. The generated
`run-settings.json` supplies server paths and GPU placement for study settings.

For local website development against a remote pipeline, use the optional
[local development connection](../installation/README.md#local-website-development) in that
guide. The study backend communicates with the pipeline over HTTP and has no
model dependencies.

Runtime → Check health connects to `http://127.0.0.1:8766`. Each inference submission sends one audio recording and its saved configuration. The pipeline executes every inference step and returns output audio, events and telemetry. The study backend polls jobs and collects artifacts; it does not advance inference, execute tools or inject results.

Both projects depend on the small [speech_contracts](../speech_contracts/README.md) package for request dataclasses, settings and function schema validation. It has no third-party dependencies or execution code. The study backend's upload-normalization trace is local preparation telemetry, separate from the pipeline's inference trace.

## Conduct a study

1. Create a study. Configure native endpoint, remote reference WAV, device placement, time limits, and model revisions. Prefer immutable model revision hashes for collection.
2. Add development and evaluation cases, or load the revised 48-case starter template. It contains filename-location, room, date/time, web and no-tool prompts, not collected human recordings. The document tool searches an editable virtual file index for filenames and returns their folders/paths. Web cases require independently verified B2 answers before freezing.
3. Edit tool function names, descriptions, required string parameter, lookup fixtures, aliases, delays, and failure behavior. The displayed schema matches the OpenAI function schema used by both callers.
4. Prepare missing inputs using Kokoro, or upload PCM WAV recordings (up to 50 MiB and five minutes). Synthesis jobs appear under Operations. Inputs retain their origin, provenance, and checksum. Changing question text clears the prepared input.
5. Try individual conditions during development. Freeze when all evaluation inputs and B2 oracle facts are ready. Freezing preserves the case/tool/settings snapshot; subsequent edits require cloning.
6. Run the full randomized B0/B1/B2 matrix. With both callers selected, the 48-case template produces 288 attempts per repetition (48 × 3 conditions × 2 caller sets); single-caller mode produces 144. Work is serialized to avoid sidecar GPU contention. A disconnected platform preserves the remote job ID; resume collection without creating a new inference attempt.
7. Listen to generated output in each run inspector, optionally transcribe it, then save the listening verdict. Output ASR is a separate analysis job. Review relevant-fact timing is relative to the output recording's start.
8. Inspect nested spans, actual tool events, exact injected text, evaluation acknowledgements, and memory samples. Export the ZIP with snapshots, audio, JSON traces, Chrome trace files, review data, and CSV.

Accuracy uses frozen evaluation-split tool-required attempts. Failed, silent, and unreviewed attempts stay in its denominator; development runs are excluded. No-tool unnecessary calls are reported separately. Latency and memory summaries use frozen evaluation attempts and should be compared only under matching pacing and configurations.

For GPU question preparation, add `"tts_device": "cuda:0"` to an editable study's settings JSON and save before queuing preparation. Existing settings without this field use CPU. Changing the device affects newly queued synthesis jobs and their cache entries; **Prepare missing inputs** keeps already attached recordings. Test with a new case, or clone a frozen study before editing. Audio provenance records the actual synthesis device. The study backend continues to submit preparation jobs to the independent pipeline service; it does not load Kokoro or CUDA.

Use the **Reference voice WAV on the pipeline server** field to set the path. Click **Save configuration** and wait for **Configuration saved and verified** before reloading or running a case. The form displays persistent save errors and verifies the server's stored values with a fresh read. Advanced settings JSON rejects duplicate keys. Frozen studies require cloning before editing.

For server updates and frontend rebuilds, follow the [update procedure](../installation/README.md#update-an-existing-installation).

### Export the input dataset before inference

Select **Export input dataset** at the top of a study. It downloads a ZIP containing
only the current questions, categories and attached input recordings. No GPU,
inference runs or frozen study are required. For a study named `study1`:

```text
study1/
  1/
    input1.wav
    input1_16khz.wav
    question.txt
    category.txt
  2/
    input2.wav
    input2_16khz.wav
    question.txt
    category.txt
  manifest.json
```

Folders follow the question order shown in the study. `inputN.wav` preserves the
original uploaded/recorded/TTS WAV bytes and its original sample rate;
`inputN_16khz.wav` is the saved mono PCM16 experiment input. Text files use UTF-8.
The manifest maps numbers to case IDs, records origins/checksums, and lists missing
audio. Questions without recordings still get their text/category files; missing
WAVs are not replaced with empty or fabricated files. Study names are sanitized
for folder paths. Historical/replaced inputs, inference outputs, traces and logs
belong to the separate full **Export ZIP** archive.

### Import or merge an input dataset

In a draft study, choose **Import input dataset**, upload an exported input ZIP
(or a partial ZIP using the same numbered folders), and review the preview.
**Add as new questions** appends selected rows. **Replace selected existing
questions** lets you choose the target question and independently keep existing
or imported question text, audio and category for every row. You can listen to
both audio versions and uncheck rows to skip them. Nothing changes in the study
until you select **Apply selected choices**.

Matching suggestions use the manifest's case ID first, then a unique matching
question text, then folder number. Folder-number matches need human review,
especially when importing from another study. A partial ZIP with just folder 12
can update one question in a 48-question study; it does not replace the other 47.
Text-only folders can append questions without audio. Audio-only folders can
replace audio while retaining an existing question. Appending requires question
text; rows without it should be skipped or used in replacement mode.

Accepted originals and 16 kHz inputs are saved through the normal artifact store
(Atlas/GridFS when configured). An existing original/normalized byte pair is reused
instead of duplicating storage. Provided normalized audio is retained byte for
byte. If only an original is supplied, the platform creates its 16 kHz copy on CPU.
If only the normalized file is supplied, it is kept without inventing an original.
No GPU runtime is needed for importing.

Imports preserve saved run snapshots. Replaced recordings are reclaimed when no
other question, study or saved run needs them. Changing question text/category
clears expected-answer, B2 fact and expected-tool annotations for manual review.
Explicitly choosing old audio with new text is allowed; verify they describe the
same spoken question. Frozen studies must be cloned before importing.

The preview detects changes to target questions made after preview and refuses
to overwrite them. Each row reports success/failure; failed rows can be retried
without duplicating rows already saved. A failed old-audio cleanup keeps the new
input and reports that cleanup needs retrying. Import provenance includes the ZIP
SHA-256 and the selected fields.

ZIP uploads are limited to 100 MiB, 250 MiB expanded, 1000 question folders and
50 MiB per WAV. Split larger datasets across partial imports. Preview files stay
in a local staging folder, are discarded when closing the preview, and expire
after 24 hours (expired files are cleaned on the next upload). They are not stored
as a second ZIP in Atlas. Refreshing abandons the preview; upload the ZIP again
to continue. Applied changes remain in the study. Permanent study deletion also
removes its staged imports.

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

Timers preserve monotonic integer nanoseconds and clock identity; the UI renders milliseconds. CUDA events measure supported caller operations, with final synchronization. Process RSS/NVML are sampled observations, not guaranteed transient peaks. Native MiniCPM is a different process: its memory and internal encoding/prefill/decode/vocoding timings are explicitly unavailable without native instrumentation. Output text and context acknowledgement do not establish spoken correctness.

```bash
python -m pip install -e '.[dev]'
python -m pytest tests -q
python -m ruff check src
python -m ruff format src
cd frontend
npm run build
```

Local validation covers study API/persistence, paired caller requests, analysis/export grouping, permanent/shared-file cleanup and package isolation. TypeScript, frontend logic checks and the Vite production build pass. Atlas adapter tests use in-memory fixtures; real Atlas deletion, GPU inference and audible correctness still require a server smoke test. A native TCP fixture is skipped when the sandbox denies listening sockets.

## Tool designer, comparisons, exports and deletion

See [the tool designer guide](../docs/TOOL_DESIGNER.md) for the Python function contract and the full tool-calling flow. The global tool library stores user-authored definitions; attaching a tool copies it into a draft study. The existing record-based fixtures remain available. Editable server-clock and Exa web-search templates use the same Python execution contract; see the guide for setup and reference scoring.

Operations has a full queue view and a detail page with requests, remote jobs, progress and captured logs. Export ZIP at the top of a study includes metadata, recorded files, historical inputs, source and execution evidence with a checksum inventory. Delete study permanently removes its metadata, run evidence, reviews, operation logs and unshared audio from Atlas/GridFS and the local cache; active work blocks deletion. Shared recordings remain until the last referencing study is deleted. Cleanup failures keep a retryable deletion entry under Show Trash; deletion cannot be undone. Older trashed studies also have a permanent-delete button.

For source, dependency, frontend, and service updates, use the [setup guide](../installation/README.md#update-an-existing-installation).

### Compare the two callers in one study

New studies configure the two currently supported callers: **IBM Granite** and
**Qwen3-1.7B with thinking disabled**. Granite is an IBM model; there is no NVIDIA
caller adapter in this project. In Settings, each caller has its own model,
revision, device and weight precision. Existing studies retain their original
single-caller configuration. Enable **Compare IBM Granite and Qwen in this study**
in an editable study, or clone a frozen study first.

Running a condition queues one attempt per configured caller. The full matrix
queues two B0/B1/B2 sets per case per repetition, sharing the exact saved input WAV
and other study settings. Only B1 executes its set's caller; B0 and B2 are repeated
controls, not caller-specific architectures. Queue execution stays sequential;
profile order within each condition is shuffled with the study seed.

Runs store their caller profile, comparison ID and repetition. Analysis groups by
model/revision/device/precision instead of pooling the callers. ZIPs include
`caller_profiles.json`, profiles in frozen snapshots/run metadata, and caller,
comparison and repetition columns in `runs.csv`. Use comparison ID plus condition
to pair the two callers' attempts. Web results and server clock values can change
between attempts; inspect the saved evidence when comparing them.

Deletion tracks newly prepared/uploaded artifact directories even after a case's
audio is replaced or cleared. Older unreferenced files whose ownership was already
lost before this tracking was introduced cannot be attributed automatically. The
cleanup affects managed Atlas data and this platform's local cache; independent
GPU runtime job caches and files on other offline laptops are outside it. No
existing study is deleted merely by installing this version.
