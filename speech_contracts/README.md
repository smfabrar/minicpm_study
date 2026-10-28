# Speech Contracts

Dependency-free shared request and configuration types for two independently installable applications: `speech-study` and `tool-pipeline`.

This package contains no model loading, inference, tool execution, FastAPI, SQLite, filesystem storage or study-service code.

```bash
python -m pip install -e ./speech_contracts
```

- `RunSettings`: validated frozen configuration dataclass, serialized to JSON in studies and requests.
- `RunRequest`: audio input and B0/B1/B2 configuration. `to_payload()` omits oracle fields for B0/B1; B1 cannot accept oracle data.
- `SynthesisRequest`: textual question and TTS settings, with a deterministic cache identity and serialized job payload.
- `validate_definition` and `function_schema`: validate declarative tool metadata and build the OpenAI function schema used by Granite and Qwen. They never execute tools.

Install this project separately before installing either application. Both distributions declare `speech-contracts==0.1.0`. To deploy from wheels, build this wheel alongside the chosen application's wheel; neither application requires the other's wheel.
