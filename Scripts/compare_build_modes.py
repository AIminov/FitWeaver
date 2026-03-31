"""Compatibility shim. Use `garmin_fit.compare_build_modes` instead."""

import sys
from importlib import import_module


_impl = import_module("garmin_fit.compare_build_modes")
sys.modules[__name__] = _impl
