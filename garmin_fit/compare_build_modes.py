"""Compatibility alias for local package execution."""

import sys
from importlib import import_module


_impl = import_module("src.garmin_fit.compare_build_modes")
sys.modules[__name__] = _impl
