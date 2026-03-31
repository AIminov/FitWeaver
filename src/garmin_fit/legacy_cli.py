from __future__ import annotations

import argparse
from typing import Sequence

from ._shared_cli import configure_logging, generate_run_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Legacy/debug CLI for template-based Garmin FIT workflows."
    )
    subparsers = parser.add_subparsers(dest="command")

    templates_parser = subparsers.add_parser("templates", help="Export Python templates from YAML")
    templates_parser.add_argument("--plan", metavar="YAML_PATH", help="Use a specific YAML plan")

    build_parser = subparsers.add_parser("build", help="Build FIT files from existing templates")
    build_parser.add_argument(
        "--validate-mode",
        choices=["soft", "strict"],
        default="soft",
        help="Validation mode for legacy FIT output",
    )

    compare_parser = subparsers.add_parser("compare", help="Compare direct build against legacy templates")
    compare_parser.add_argument("--plan", metavar="YAML_PATH", help="Use a specific YAML plan")
    compare_parser.add_argument(
        "--validate-mode",
        choices=["soft", "strict"],
        default="soft",
        help="Validation mode for the comparison workflow",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    run_id = generate_run_id()
    validate_strict = getattr(args, "validate_mode", "soft") == "strict"
    from . import workflow as workflow_module

    if args.command == "templates":
        return workflow_module.workflow_templates_only(run_id=run_id, plan_path=args.plan)
    if args.command == "build":
        return workflow_module.workflow_build_only(validate_strict=validate_strict, run_id=run_id)
    if args.command == "compare":
        return workflow_module.workflow_compare_build_modes(
            validate_strict=validate_strict,
            run_id=run_id,
            plan_path=args.plan,
        )

    parser.error(f"Unsupported command: {args.command}")
    return 2
