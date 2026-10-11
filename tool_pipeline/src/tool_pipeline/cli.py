"""Run an inference request independently of both HTTP applications."""

import argparse
import asyncio
import json
from pathlib import Path

from speech_contracts import RunRequest
from .pipeline import InferencePipeline


def main():
    parser = argparse.ArgumentParser(description="Run a saved audio experiment")
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    request = RunRequest.from_dict(json.loads(args.request.read_text()))
    result = asyncio.run(InferencePipeline(request, args.output).run())
    print(json.dumps({"status": result["status"], "error": result["error"], "output": str(args.output)}))
    return 0 if result["status"] in {"complete", "silent"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
