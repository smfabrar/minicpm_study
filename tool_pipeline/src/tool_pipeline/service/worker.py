"""Process-isolated worker for inference, preparation, or analysis."""

import argparse
import asyncio
import json
import traceback
from pathlib import Path

from speech_contracts import RunRequest, RunSettings

from ..pipeline import InferencePipeline


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.request.read_text())
    kind = payload.pop("job_kind", "inference")
    try:
        if kind == "inference":
            result = asyncio.run(InferencePipeline(RunRequest.from_dict(payload), args.output).run())
        elif kind == "synthesis":
            from ..models.preparation import synthesize

            result = synthesize(
                payload["question"], RunSettings.from_dict(payload["settings"]), args.output
            )
        elif kind == "transcription":
            from ..models.preparation import transcribe_output

            result = transcribe_output(
                Path(payload["audio_path"]), RunSettings.from_dict(payload["settings"]), args.output
            )
        else:
            raise ValueError("Unknown job kind")
    except Exception as exc:
        result = {"status": "failed", "kind": kind, "error": f"{type(exc).__name__}: {exc}"}
        traceback.print_exc()
    (args.output / "result.json").write_text(json.dumps(result, indent=2))
    return 0 if result["status"] in {"complete", "silent"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
