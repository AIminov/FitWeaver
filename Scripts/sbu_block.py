"""Compatibility shim. Use `garmin_fit.sbu_block` instead."""

import sys
from importlib import import_module


_impl = import_module("garmin_fit.sbu_block")
sys.modules[__name__] = _impl
