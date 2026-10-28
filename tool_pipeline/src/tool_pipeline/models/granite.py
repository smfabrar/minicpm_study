"""Granite adapter for the shared native tool caller."""

from .caller import NativeToolCaller


class GraniteCaller(NativeToolCaller):
    family = "granite"
