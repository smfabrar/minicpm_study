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
