"""Compatibility shim. Use `garmin_fit.logging_utils` instead."""

import sys
from importlib import import_module


_impl = import_module("garmin_fit.logging_utils")
sys.modules[__name__] = _impl
