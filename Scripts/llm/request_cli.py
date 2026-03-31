"""Compatibility shim. Use `garmin_fit.llm.request_cli` instead."""

import sys
from importlib import import_module


_impl = import_module("garmin_fit.llm.request_cli")
sys.modules[__name__] = _impl
