"""Compatibility shim. Use `garmin_fit.runtime_layout` instead."""

from importlib import import_module


_impl = import_module("garmin_fit.runtime_layout")

__all__ = [name for name in dir(_impl) if not name.startswith("_")]

for name in __all__:
    globals()[name] = getattr(_impl, name)
