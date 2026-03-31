"""Compatibility shim. Use `garmin_fit.build_fits` instead."""

import sys
from importlib import import_module


_impl = import_module("garmin_fit.build_fits")
sys.modules[__name__] = _impl
