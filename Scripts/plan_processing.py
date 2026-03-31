"""Compatibility shim. Use `garmin_fit.plan_processing` instead."""

import sys
from importlib import import_module


_impl = import_module("garmin_fit.plan_processing")
sys.modules[__name__] = _impl
