#!/usr/bin/env python3
"""Interactive menu for common Garmin FIT workflows."""

from __future__ import annotations

import argparse
import datetime
import getpass
import importlib
import os


def build_parser() -> argparse.ArgumentParser:
	return argparse.ArgumentParser(
		description="Interactive menu for common Garmin FIT workflows."
	)


def run_module(module: str, args: list[str]) -> int:
	print(f"\n>> {module} {' '.join(args)}\n")
	mod = importlib.import_module(module)
	return mod.main(args) or 0


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def _ask(prompt: str, default: str = "") -> str:
	display = f"{prompt} [{default}]: " if default else f"{prompt}: "
	val = input(display).strip()
	return val if val else default


def _ask_mode() -> str:
	val = input("Validation mode [soft/strict, default=soft]: ").strip().lower()
	return "strict" if val in {"strict", "s"} else "soft"


def _ask_yes(prompt: str, default: bool = False) -> bool:
	hint = "Y/n" if default else "y/N"
	val = input(f"{prompt} [{hint}]: ").strip().lower()
	if not val:
		return default
	return val in {"y", "yes"}


def _ask_date(prompt: str) -> str:
	while True:
		val = input(f"{prompt} [YYYY-MM-DD, blank=skip]: ").strip()
		if not val:
			return ""
		try:
			datetime.date.fromisoformat(val)
			return val
		except ValueError:
			print("  Invalid format. Use YYYY-MM-DD.")


def _ask_email() -> str:
	env = os.environ.get("GARMIN_EMAIL", "")
	return _ask("Garmin email", env)


def _ask_password() -> str:
	env = os.environ.get("GARMIN_PASSWORD", "")
	if env:
		use = input("  Use GARMIN_PASSWORD from env? [Y/n]: ").strip().lower()
		if use != "n":
			return env
	return getpass.getpass("  Garmin password: ")


def _ask_year() -> str:
	return _ask("Year", str(datetime.date.today().year))


# ---------------------------------------------------------------------------
# Menu handlers
# ---------------------------------------------------------------------------

def _handle_llm() -> int:
	print("\n  LLM API type:")
	print("  1) OpenAI-compatible (LM Studio, default)")
	print("  2) Ollama")
	api_choice = input("  Select [1/2, default=1]: ").strip()
	api = "ollama" if api_choice == "2" else "openai"

	if api == "openai":
		url = _ask("  API URL", "http://127.0.0.1:1234/v1")
		mode = _ask("  OpenAI mode [auto/chat/completions]", "completions")
	else:
		url = _ask("  API URL", "http://localhost:11434")
		mode = "auto"

	model = input("  Model name [blank=auto]: ").strip()
	timeout = _ask("  Timeout seconds", "1800")
	workouts_raw = input("  Expected workouts [blank=auto-detect]: ").strip()

	args = ["--api", api, "--url", url, "--timeout-sec", timeout]
	if api == "openai":
		args += ["--openai-mode", mode]
	if model:
		args += ["--model", model]
	if workouts_raw.isdigit() and int(workouts_raw) > 0:
		args += ["--workouts", workouts_raw]

	return run_module("garmin_fit.llm.request_cli", args)


def _handle_garmin_calendar(dry_run: bool = False) -> int:
	email = _ask_email()
	password = _ask_password() if not dry_run else ""
	year = _ask_year()
	from_date = _ask_date("  From date (optional)")
	to_date = _ask_date("  To date (optional)")
	skip_past = _ask_yes("  Skip past workouts?", default=False)

	args = ["garmin-calendar"]
	if email:
		args += ["--email", email]
	if password:
		args += ["--password", password]
	args += ["--year", year]
	if from_date:
		args += ["--from-date", from_date]
	if to_date:
		args += ["--to-date", to_date]
	if skip_past:
		args.append("--skip-past")
	if dry_run:
		args.append("--dry-run")

	return run_module("garmin_fit.cli", args)


def _handle_garmin_delete() -> int:
	print("\n  This will DELETE workouts from Garmin Connect.")
	email = _ask_email()
	password = _ask_password()
	year = _ask_year()
	from_date = _ask_date("  From date (optional)")
	to_date = _ask_date("  To date (optional)")
	dry_run = _ask_yes("  Dry-run only (preview, no deletion)?", default=True)

	args = ["garmin-calendar-delete", "--email", email, "--password", password, "--year", year]
	if from_date:
		args += ["--from-date", from_date]
	if to_date:
		args += ["--to-date", to_date]

	if dry_run:
		args.append("--dry-run")
	else:
		print("\n  !! This will permanently delete matched workouts from Garmin Connect.")
		confirm = _ask_yes("  Are you sure?", default=False)
		if not confirm:
			print("  Cancelled.")
			return 0
		args.append("--confirm")

	return run_module("garmin_fit.cli", args)


def _handle_doctor() -> int:
	llm = _ask_yes("Include LLM connectivity check?", default=False)
	args = ["doctor"]
	if llm:
		api_choice = input("  LLM API type [openai/ollama, default=openai]: ").strip().lower()
		api = "ollama" if api_choice == "ollama" else "openai"
		if api == "openai":
			url = _ask("  API URL", "http://127.0.0.1:1234/v1")
		else:
			url = _ask("  API URL", "http://localhost:11434")
		args += ["--llm", "--api", api, "--url", url]
	return run_module("garmin_fit.cli", args)


def _handle_restore() -> int:
	name = input("Archive name to restore: ").strip()
	if not name:
		print("Archive name cannot be empty.")
		return 1
	return run_module("garmin_fit.cli", ["restore", name])


# ---------------------------------------------------------------------------
# Menu display
# ---------------------------------------------------------------------------

def _print_menu() -> None:
	print()
	print("=" * 60)
	print("  Garmin FIT Runner")
	print("=" * 60)
	print()
	print("  --- LLM Generation ---")
	print("  L) Generate YAML from plan text (local LLM)")
	print()
	print("  --- Build & Validate ---")
	print("  1) Full workflow  (YAML → FIT → validate)")
	print("  2) Validate YAML plan")
	print("  3) Validate FIT files")
	print()
	print("  --- Garmin Connect ---")
	print("  G) Upload plan to Garmin Calendar")
	print("  P) Garmin Calendar dry-run preview")
	print("  X) Delete workouts from Garmin Calendar")
	print()
	print("  --- Utilities ---")
	print("  4) Doctor  (environment diagnostics)")
	print("  5) Archive current set")
	print("  6) List archives")
	print("  7) Restore from archive")
	print()
	print("  --- Legacy / Debug ---")
	print("  8) Templates only")
	print("  9) Build from templates")
	print("  C) Compare direct vs legacy build")
	print()
	print("  0) Exit")
	print()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
	build_parser().parse_args(argv)

	while True:
		_print_menu()
		choice = input("Select option: ").strip().upper()

		if choice == "0":
			print("Exit.")
			return 0

		if choice == "L":
			ret = _handle_llm()
		elif choice == "1":
			mode = _ask_mode()
			ret = run_module("garmin_fit.cli", ["run", "--validate-mode", mode])
		elif choice == "2":
			ret = run_module("garmin_fit.cli", ["validate-yaml"])
		elif choice == "3":
			mode = _ask_mode()
			ret = run_module("garmin_fit.cli", ["validate-fit", "--validate-mode", mode])
		elif choice == "G":
			ret = _handle_garmin_calendar(dry_run=False)
		elif choice == "P":
			ret = _handle_garmin_calendar(dry_run=True)
		elif choice == "X":
			ret = _handle_garmin_delete()
		elif choice == "4":
			ret = _handle_doctor()
		elif choice == "5":
			ret = run_module("garmin_fit.cli", ["archive"])
		elif choice == "6":
			ret = run_module("garmin_fit.cli", ["list-archives"])
		elif choice == "7":
			ret = _handle_restore()
		elif choice == "8":
			ret = run_module("garmin_fit.legacy_cli", ["templates"])
		elif choice == "9":
			mode = _ask_mode()
			ret = run_module("garmin_fit.legacy_cli", ["build", "--validate-mode", mode])
		elif choice == "C":
			mode = _ask_mode()
			ret = run_module("garmin_fit.legacy_cli", ["compare", "--validate-mode", mode])
		else:
			print("Invalid choice.")
			continue

		status = "[OK]" if ret == 0 else f"[exit code {ret}]"
		input(f"\n  {status}  Press Enter to return to menu...")


if __name__ == "__main__":
	raise SystemExit(main())
