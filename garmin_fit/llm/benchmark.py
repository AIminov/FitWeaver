"""Compatibility alias for local package execution."""

import sys
from importlib import import_module


_impl = import_module("src.garmin_fit.llm.benchmark")
sys.modules[__name__] = _impl
