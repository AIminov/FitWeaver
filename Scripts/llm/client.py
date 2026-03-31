"""Compatibility shim. Use `garmin_fit.llm.client` instead."""

import sys
from importlib import import_module


_impl = import_module("garmin_fit.llm.client")
sys.modules[__name__] = _impl
