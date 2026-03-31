#!/usr/bin/env python3
"""
Compatibility CLI entry point for Garmin FIT workout generation workflow.

Primary supported CLI:
    python -m garmin_fit.cli

Legacy/debug CLI:
    python -m garmin_fit.legacy_cli

This file is intended for source-checkout compatibility only.
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from uuid import uuid4

def build_parser():
    parser = argparse.ArgumentParser(
        description="Compatibility CLI for Garmin FIT workout generation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Preferred commands:
  python -m garmin_fit.cli run
  python -m garmin_fit.cli validate-yaml --plan Plan/plan.yaml
  python -m garmin_fit.cli doctor --llm
  python -m garmin_fit.legacy_cli compare --plan Plan/plan.yaml

Examples:
  python get_fit.py                    # Compatibility entry point for full workflow
  python get_fit.py --compare-build-modes  # Compare direct build against legacy templates path
  python get_fit.py --validate-only    # Only validate existing files
  python get_fit.py --build-only       # Only build from existing templates (legacy)
  python get_fit.py --templates-only   # Only export templates from YAML (debug/legacy)
        """,
    )

    parser.add_argument(
        "--compare-build-modes",
        action="store_true",
        help="Compare direct build output with the legacy templates path for one YAML plan",
    )
    parser.add_argument("--validate-only", action="store_true", help="Only validate existing FIT files")
    parser.add_argument("--build-only", action="store_true", help="Only build FIT files from existing templates (legacy)")
    parser.add_argument("--templates-only", action="store_true", help="Only export workout templates from YAML (debug/legacy)")
    parser.add_argument("--archive", action="store_true", help="Archive current plan and workouts")
    parser.add_argument("--doctor", action="store_true", help="Run environment diagnostics and exit")
    parser.add_argument("--llm", action="store_true", help="With --doctor: run LLM connectivity + smoke generation check")
    parser.add_argument("--api", choices=["ollama", "openai"], default="openai", help="LLM API type for --doctor --llm")
    parser.add_argument("--url", help="LLM base URL for --doctor --llm")
    parser.add_argument("--model", help="LLM model name for --doctor --llm")
    parser.add_argument(
        "--openai-mode",
        choices=["auto", "chat", "completions"],
        default="completions",
        help="OpenAI-compatible mode for --doctor --llm",
    )
    parser.add_argument("--timeout-sec", type=int, default=120, help="LLM request timeout seconds for --doctor --llm")
    parser.add_argument("--list-archives", action="store_true", help="List all available archives")
    parser.add_argument("--restore", metavar="ARCHIVE_NAME", help="Restore from specified archive")
    parser.add_argument(
        "--plan",
        metavar="YAML_PATH",
        help="Use specific YAML plan file for full workflow or template export",
    )
    parser.add_argument(
        "--validate-mode",
        choices=["soft", "strict"],
        default="soft",
        help="Validation mode: soft (warnings allowed) or strict (warnings fail)",
    )
    parser.add_argument(
        "--validate-yaml",
        action="store_true",
        help="Validate YAML plan by SDK rules before building FIT",
    )
    return parser


def _generate_run_id():
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run_{ts}_{uuid4().hex[:8]}"


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = build_parser().parse_args()
    run_id = _generate_run_id()
    validate_strict = args.validate_mode == "strict"
    from garmin_fit import workflow as workflow_module

    log_file = workflow_module.setup_file_logging(run_id=run_id)
    logging.getLogger(__name__).info(
        "Compatibility entry point in use from source checkout; prefer `python -m garmin_fit.cli`."
    )
    logging.getLogger(__name__).info(f"Logging to: {log_file}")
    logging.getLogger(__name__).info(f"Run ID: {run_id}")
    logging.getLogger(__name__).info(f"Validation mode: {args.validate_mode}")
    if args.plan and (
        args.validate_only
        or args.build_only
        or args.archive
        or args.list_archives
        or args.restore
        or args.doctor
    ):
        logging.getLogger(__name__).warning("--plan is ignored for selected mode")

    try:
        if args.validate_yaml:
            return workflow_module.workflow_validate_yaml(plan_path=args.plan)
        if args.compare_build_modes:
            return workflow_module.workflow_compare_build_modes(
                validate_strict=validate_strict,
                run_id=run_id,
                plan_path=args.plan,
            )
        if args.doctor:
            doctor_url = args.url
            if not doctor_url:
                doctor_url = "http://localhost:11434" if args.api == "ollama" else "http://127.0.0.1:1234/v1"
            doctor_model = args.model or ("gemma2:2b" if args.api == "ollama" else "qwen/qwen3.5-9b")
            return workflow_module.workflow_doctor(
                llm_check=args.llm,
                llm_api=args.api,
                llm_url=doctor_url,
                llm_model=doctor_model,
                llm_openai_mode=args.openai_mode,
                llm_timeout_sec=args.timeout_sec,
            )
        if args.validate_only:
            return workflow_module.workflow_validate_only(validate_strict=validate_strict, run_id=run_id)
        if args.build_only:
            return workflow_module.workflow_build_only(validate_strict=validate_strict, run_id=run_id)
        if args.templates_only:
            return workflow_module.workflow_templates_only(run_id=run_id, plan_path=args.plan)
        if args.archive:
            return workflow_module.workflow_archive(run_id=run_id)
        if args.list_archives:
            return workflow_module.workflow_list_archives()
        if args.restore:
            return workflow_module.workflow_restore(args.restore)
        return workflow_module.workflow_full(validate_strict=validate_strict, run_id=run_id, plan_path=args.plan)
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("\n\nWorkflow cancelled by user")
        return 130
    except Exception as e:
        logging.getLogger(__name__).error(f"\nWorkflow error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
