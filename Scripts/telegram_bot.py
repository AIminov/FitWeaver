"""Compatibility shim. Use `garmin_fit.telegram_bot` instead."""

import sys
from importlib import import_module


_impl = import_module("garmin_fit.telegram_bot")
sys.modules[__name__] = _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
