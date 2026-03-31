#!/usr/bin/env python3
"""Backward-compatible wrapper for the package validation CLI."""

from garmin_fit.validate_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
