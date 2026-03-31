"""Compatibility shim. Use `garmin_fit.generate_from_yaml` instead."""

import sys
from importlib import import_module


_impl = import_module("garmin_fit.generate_from_yaml")
sys.modules[__name__] = _impl
