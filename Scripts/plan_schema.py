"""Compatibility shim. Use `garmin_fit.plan_schema` instead."""

import sys
from importlib import import_module


_impl = import_module("garmin_fit.plan_schema")
sys.modules[__name__] = _impl
