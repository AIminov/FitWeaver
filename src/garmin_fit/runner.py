#!/usr/bin/env python3
"""Interactive wrapper for common Garmin FIT workflows."""

from __future__ import annotations

import argparse
import importlib


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description="Interactive runner for common Garmin FIT workflows."
    )


def run_module(module: str, args: list[str]) -> int:
    print(f"\n>> {module} {' '.join(args)}\n")
    mod = importlib.import_module(module)
    return mod.main(args) or 0


def ask_mode() -> str:
    value = input("Validation mode [soft/strict, default=soft]: ").strip().lower()
    if value in {"strict", "s"}:
        return "strict"
    return "soft"


def ask_restore_name() -> str:
    return input("Archive name to restore: ").strip()


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)

    print("=" * 60)
    print(" Garmin FIT Runner")
    print("=" * 60)
    print("1) Full workflow (primary CLI)")
    print("2) Templates only (legacy/debug)")
    print("3) Build only (legacy/debug)")
    print("4) Validate FIT files only (primary CLI)")
    print("5) Validate YAML plan (primary CLI)")
    print("6) Archive current set (primary CLI)")
    print("7) List archives (primary CLI)")
    print("8) Restore from archive (primary CLI)")
    print("9) Compare direct vs legacy build (legacy/debug)")
    print("G) Upload plan to Garmin Calendar (cloud, no USB)")
    print("D) Garmin Calendar dry run (preview only)")
    print("0) Exit")

    choice = input("\nSelect option [0-9 / G / D]: ").strip().upper()

    if choice == "0":
        print("Exit.")
        return 0
    if choice == "1":
        mode = ask_mode()
        return run_module("garmin_fit.cli", ["run", "--validate-mode", mode])
    if choice == "2":
        return run_module("garmin_fit.legacy_cli", ["templates"])
    if choice == "3":
        mode = ask_mode()
        return run_module("garmin_fit.legacy_cli", ["build", "--validate-mode", mode])
    if choice == "4":
        mode = ask_mode()
        return run_module("garmin_fit.cli", ["validate-fit", "--validate-mode", mode])
    if choice == "5":
        return run_module("garmin_fit.validate_cli", [])
    if choice == "6":
        return run_module("garmin_fit.cli", ["archive"])
    if choice == "7":
        return run_module("garmin_fit.cli", ["list-archives"])
    if choice == "8":
        archive_name = ask_restore_name()
        if not archive_name:
            print("Archive name cannot be empty.")
            return 1
        return run_module("garmin_fit.cli", ["restore", archive_name])
    if choice == "9":
        mode = ask_mode()
        return run_module("garmin_fit.legacy_cli", ["compare", "--validate-mode", mode])
    if choice == "G":
        return run_module("garmin_fit.cli", ["garmin-calendar"])
    if choice == "D":
        return run_module("garmin_fit.cli", ["garmin-calendar", "--dry-run"])

    print("Invalid choice.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
