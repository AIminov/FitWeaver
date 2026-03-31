"""Source-checkout bridge for the real package in ``src/garmin_fit``."""

from pathlib import Path

from src.garmin_fit import __version__


_SRC_PACKAGE_DIR = Path(__file__).resolve().parent.parent / "src" / "garmin_fit"
if _SRC_PACKAGE_DIR.is_dir():
    __path__.append(str(_SRC_PACKAGE_DIR))

__all__ = ["__version__"]
