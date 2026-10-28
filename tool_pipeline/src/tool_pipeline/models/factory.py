"""Construct the configured caller without importing model dependencies eagerly."""

from .granite import GraniteCaller
from .qwen import QwenCaller


def create_caller(settings, registry, trace):
    callers = {"granite": GraniteCaller, "qwen3": QwenCaller}
    return callers[settings.caller_backend](settings, registry, trace)
