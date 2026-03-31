"""Compatibility shim. Use `garmin_fit.build_from_plan` instead."""

import sys
from importlib import import_module


_impl = import_module("garmin_fit.build_from_plan")
sys.modules[__name__] = _impl
