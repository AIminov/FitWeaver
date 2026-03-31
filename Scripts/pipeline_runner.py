"""Compatibility shim. Use `garmin_fit.pipeline_runner` instead."""

import sys
from importlib import import_module


_impl = import_module("garmin_fit.pipeline_runner")
sys.modules[__name__] = _impl
