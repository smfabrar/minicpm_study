"""Locate the reference package in a checkout or an installed environment."""

import importlib
import os
import sys
from pathlib import Path


def reference_module(name):
    try:
        return importlib.import_module("duplex_tools." + name)
    except ModuleNotFoundError as exc:
        if exc.name and not exc.name.startswith("duplex_tools"):
            raise
        configured = os.environ.get("DUPLEX_TOOLS_SOURCE")
        repository = Path(__file__).resolve().parents[3]
        candidates = [repository / "minicpm_tool/src", repository.parent / "minicpm_tool/src"]
        source = Path(configured) if configured else next(
            (path for path in candidates if (path / "duplex_tools").is_dir()), candidates[-1]
        )
        if not (source / "duplex_tools").is_dir():
            raise RuntimeError(
                "Install the minicpm_tool reference package or set DUPLEX_TOOLS_SOURCE to its src directory"
            ) from exc
        sys.path.insert(0, str(source))
        return importlib.import_module("duplex_tools." + name)
