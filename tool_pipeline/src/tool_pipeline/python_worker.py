"""Small subprocess entry point for trusted, authored Python functions.

This is process isolation with a deadline, not a security sandbox. Functions run
with the runtime account's filesystem, network and installed Python packages.
"""

import json
import sys
import traceback
from pathlib import Path


def main(request_path: Path, result_path: Path) -> int:
    try:
        request = json.loads(request_path.read_text())
        namespace = {"__name__": "study_tool", "__file__": str(request_path)}
        exec(compile(request["source"], str(request_path), "exec"), namespace)
        result = namespace["execute"](request["arguments"])
        if isinstance(result, str):
            result = {"facts": result, "sources": []}
        if not isinstance(result, dict) or not isinstance(result.get("facts"), str) or not result["facts"].strip():
            raise ValueError("execute(arguments) must return non-empty text or {'facts': text, 'sources': [text]}")
        sources = result.get("sources", [])
        if not isinstance(sources, list) or any(not isinstance(source, str) for source in sources):
            raise ValueError("sources must be a list of strings")
        if len(result["facts"]) > 32000 or len(sources) > 100:
            raise ValueError("Tool result exceeds 32000 fact characters or 100 sources")
        result_path.write_text(json.dumps({"facts": result["facts"], "sources": sources}, allow_nan=False))
        return 0
    except Exception as exc:
        traceback.print_exc()
        result_path.write_text(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2])))
