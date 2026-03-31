"""Compatibility shim. Use `garmin_fit.workout_utils` instead."""

import sys
from importlib import import_module


_impl = import_module("garmin_fit.workout_utils")
sys.modules[__name__] = _impl
