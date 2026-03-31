"""Compatibility shim. Use `garmin_fit.orchestrator` instead."""

import sys
from importlib import import_module


_impl = import_module("garmin_fit.orchestrator")
sys.modules[__name__] = _impl
