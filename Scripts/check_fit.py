"""Compatibility shim. Use `garmin_fit.check_fit` instead."""

import sys
from importlib import import_module


_impl = import_module("garmin_fit.check_fit")
sys.modules[__name__] = _impl
