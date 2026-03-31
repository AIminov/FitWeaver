"""Compatibility shim. Use `garmin_fit.archive_manager` instead."""

import sys
from importlib import import_module


_impl = import_module("garmin_fit.archive_manager")
sys.modules[__name__] = _impl
