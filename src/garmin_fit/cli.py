from __future__ import annotations

import argparse
from typing import Sequence

from .workflow import (
    workflow_archive,
    workflow_doctor,
    workflow_full,
    workflow_list_archives,
    workflow_restore,
    workflow_validate_only,
    workflow_validate_yaml,
)

from ._shared_cli import configure_logging, generate_run_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Primary CLI for the supported Garmin FIT workflow."
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run the direct-build workflow")
    run_parser.add_argument("--plan", metavar="YAML_PATH", help="Use a specific YAML plan")
    run_parser.add_argument(
        "--validate-mode",
        choices=["soft", "strict"],
        default="soft",
        help="Validation mode for FIT output",
    )

    validate_yaml_parser = subparsers.add_parser("validate-yaml", help="Validate a YAML plan")
    validate_yaml_parser.add_argument("--plan", metavar="YAML_PATH", help="Use a specific YAML plan")

    validate_fit_parser = subparsers.add_parser("validate-fit", help="Validate FIT files in the runtime output")
    validate_fit_parser.add_argument(
        "--validate-mode",
        choices=["soft", "strict"],
        default="soft",
        help="Validation mode for FIT output",
    )

    doctor_parser = subparsers.add_parser("doctor", help="Run environment diagnostics")
    doctor_parser.add_argument("--llm", action="store_true", help="Run LLM connectivity smoke checks")
    doctor_parser.add_argument("--api", choices=["ollama", "openai"], default="openai")
    doctor_parser.add_argument("--url")
    doctor_parser.add_argument("--model")
    doctor_parser.add_argument("--openai-mode", choices=["auto", "chat", "completions"], default="completions")
    doctor_parser.add_argument("--timeout-sec", type=int, default=120)

    subparsers.add_parser("archive", help="Archive the current runtime artifacts")
    subparsers.add_parser("list-archives", help="List available archives")

    restore_parser = subparsers.add_parser("restore", help="Restore a named archive")
    restore_parser.add_argument("archive_name")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command

    if command is None:
        parser.print_help()
        return 0

    run_id = generate_run_id()
    validate_strict = getattr(args, "validate_mode", "soft") == "strict"

    if command == "run":
        return workflow_full(validate_strict=validate_strict, run_id=run_id, plan_path=args.plan)
    if command == "validate-yaml":
        return workflow_validate_yaml(plan_path=args.plan)
    if command == "validate-fit":
        return workflow_validate_only(validate_strict=validate_strict, run_id=run_id)
    if command == "doctor":
        doctor_url = args.url or ("http://localhost:11434" if args.api == "ollama" else "http://127.0.0.1:1234/v1")
        doctor_model = args.model or ("gemma2:2b" if args.api == "ollama" else "qwen/qwen3.5-9b")
        return workflow_doctor(
            llm_check=args.llm,
            llm_api=args.api,
            llm_url=doctor_url,
            llm_model=doctor_model,
            llm_openai_mode=args.openai_mode,
            llm_timeout_sec=args.timeout_sec,
        )
    if command == "archive":
        return workflow_archive(run_id=run_id)
    if command == "list-archives":
        return workflow_list_archives()
    if command == "restore":
        return workflow_restore(args.archive_name)

    parser.error(f"Unsupported command: {command}")
    return 2
