"""Compatibility shim. Use `garmin_fit.llm.prompt` instead."""

import sys
from importlib import import_module


_impl = import_module("garmin_fit.llm.prompt")
sys.modules[__name__] = _impl
