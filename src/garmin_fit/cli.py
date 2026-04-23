from __future__ import annotations

import argparse
from typing import Sequence

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

    gc_parser = subparsers.add_parser(
        "garmin-calendar",
        help="Upload plan to Garmin Connect Calendar (no USB required)",
    )
    gc_parser.add_argument("--plan", metavar="YAML_PATH", help="Path to YAML plan file")
    gc_parser.add_argument("--email", metavar="EMAIL", help="Garmin account email (or GARMIN_EMAIL env)")
    gc_parser.add_argument("--password", metavar="PASSWORD", help="Garmin account password (or GARMIN_PASSWORD env)")
    gc_parser.add_argument("--token-dir", metavar="DIR", help="Directory for token storage (default: ~/.garminconnect)")
    gc_parser.add_argument("--year", type=int, metavar="YEAR", help="Override year for date extraction")
    gc_parser.add_argument("--no-schedule", action="store_true", help="Upload workouts without scheduling to calendar")
    gc_parser.add_argument("--dry-run", action="store_true", help="Build payloads but make no API calls")
    gc_parser.add_argument("--week-pause", type=float, default=3.0, metavar="SECS",
                           help="Extra pause between calendar weeks (default: 3.0 s)")
    gc_parser.add_argument("--skip-past", action="store_true",
                           help="Skip workouts whose date is before today")
    gc_parser.add_argument("--from-date", metavar="YYYY-MM-DD",
                           help="Only upload workouts on or after this date")
    gc_parser.add_argument("--to-date", metavar="YYYY-MM-DD",
                           help="Only upload workouts on or before this date")

    gcd_parser = subparsers.add_parser(
        "garmin-calendar-delete",
        help="Delete uploaded FitWeaver workouts from Garmin Connect",
    )
    gcd_parser.add_argument("--email", metavar="EMAIL", help="Garmin account email (or GARMIN_EMAIL env)")
    gcd_parser.add_argument("--password", metavar="PASSWORD", help="Garmin account password (or GARMIN_PASSWORD env)")
    gcd_parser.add_argument("--token-dir", metavar="DIR", help="Directory for token storage (default: ~/.garminconnect)")
    gcd_parser.add_argument("--year", type=int, metavar="YEAR", help="Year used to interpret workout names")
    gcd_parser.add_argument("--from-date", metavar="YYYY-MM-DD",
                            help="Only delete workouts on or after this date")
    gcd_parser.add_argument("--to-date", metavar="YYYY-MM-DD",
                            help="Only delete workouts on or before this date")
    gcd_parser.add_argument("--limit", type=int, default=200, metavar="N",
                            help="Max workouts to inspect from Garmin Connect (default: 200)")
    gcd_parser.add_argument("--all", action="store_true",
                            help="Delete all inspected workouts, including non-FitWeaver names")
    gcd_parser.add_argument("--dry-run", action="store_true",
                            help="Show matched workouts but do not delete them")
    gcd_parser.add_argument("--confirm", action="store_true",
                            help="Required for live deletion")

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
    from . import workflow as workflow_module

    if command == "run":
        return workflow_module.workflow_full(
            validate_strict=validate_strict,
            run_id=run_id,
            plan_path=args.plan,
        )
    if command == "validate-yaml":
        return workflow_module.workflow_validate_yaml(plan_path=args.plan)
    if command == "validate-fit":
        return workflow_module.workflow_validate_only(
            validate_strict=validate_strict,
            run_id=run_id,
        )
    if command == "doctor":
        doctor_url = args.url or ("http://localhost:11434" if args.api == "ollama" else "http://127.0.0.1:1234/v1")
        doctor_model = args.model or ("gemma2:2b" if args.api == "ollama" else "qwen/qwen3.5-9b")
        return workflow_module.workflow_doctor(
            llm_check=args.llm,
            llm_api=args.api,
            llm_url=doctor_url,
            llm_model=doctor_model,
            llm_openai_mode=args.openai_mode,
            llm_timeout_sec=args.timeout_sec,
        )
    if command == "archive":
        return workflow_module.workflow_archive(run_id=run_id)
    if command == "list-archives":
        return workflow_module.workflow_list_archives()
    if command == "restore":
        return workflow_module.workflow_restore(args.archive_name)
    if command == "garmin-calendar":
        return workflow_module.workflow_garmin_calendar(
            plan_path=args.plan,
            email=args.email,
            password=args.password,
            token_dir=args.token_dir,
            year=args.year,
            schedule=not args.no_schedule,
            dry_run=args.dry_run,
            week_pause=args.week_pause,
            skip_past=args.skip_past,
            from_date=args.from_date,
            to_date=args.to_date,
        )
    if command == "garmin-calendar-delete":
        return workflow_module.workflow_garmin_calendar_delete(
            email=args.email,
            password=args.password,
            token_dir=args.token_dir,
            year=args.year,
            from_date=args.from_date,
            to_date=args.to_date,
            limit=args.limit,
            delete_all=args.all,
            dry_run=args.dry_run,
            confirm=args.confirm,
        )

    parser.error(f"Unsupported command: {command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
