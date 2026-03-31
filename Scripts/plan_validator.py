"""Compatibility shim. Use `garmin_fit.plan_validator` instead."""

import sys
from importlib import import_module


_impl = import_module("garmin_fit.plan_validator")
sys.modules[__name__] = _impl
