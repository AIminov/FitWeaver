"""Compatibility shim. Use `garmin_fit.config` instead."""

from importlib import import_module, reload


_impl = reload(import_module("src.garmin_fit.config"))

__all__ = [name for name in dir(_impl) if not name.startswith("_")]

for name in __all__:
    globals()[name] = getattr(_impl, name)
