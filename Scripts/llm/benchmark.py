"""Compatibility shim. Use `garmin_fit.llm.benchmark` instead."""

import sys
from importlib import import_module


_impl = import_module("garmin_fit.llm.benchmark")
sys.modules[__name__] = _impl
