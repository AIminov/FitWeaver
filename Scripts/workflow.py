"""Compatibility shim. Use `garmin_fit.workflow` instead."""

import sys
from importlib import import_module


_impl = import_module("garmin_fit.workflow")
sys.modules[__name__] = _impl
