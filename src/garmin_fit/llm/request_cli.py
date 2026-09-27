"""
CLI for LLM-based YAML generation from training plan text.

Usage:
    python -m garmin_fit.llm.request_cli
    python -m garmin_fit.llm.request_cli --plan Plan/plan.txt --output Plan/plan.yaml
    python -m garmin_fit.llm.request_cli --api openai --url http://localhost:1234/v1
    python -m garmin_fit.llm.request_cli --api openai --openai-mode auto
"""

import argparse
import logging
import sys
from pathlib import Path

from ..config import ARTIFACTS_DIR, PLAN_DIR
from .client import MAX_RETRIES, UnifiedLLMClient

logger = logging.getLogger(__name__)

# Default paths
DEFAULT_PLAN_FILE = PLAN_DIR / "plan.txt"
DEFAULT_OUTPUT = PLAN_DIR / "plan.yaml"


def extract_text_from_file(file_path: Path) -> str:
    """Read text from various file formats."""
    try:
        return file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return file_path.read_text(encoding="utf-16")
        except Exception as e:
            raise ValueError(f"Cannot read file {file_path}: {e}")


def find_plan_file() -> Path:
    """Find plan file, trying different extensions."""
    if DEFAULT_PLAN_FILE.exists():
        return DEFAULT_PLAN_FILE

    for ext in ['.md', '.markdown', '.txt']:
        candidate = PLAN_DIR / f"plan{ext}"
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        f"Plan file not found. Create {DEFAULT_PLAN_FILE} with your training plan."
    )


def main():
    from .._shared_cli import configure_logging

    configure_logging()  # at call time, not import time: importing must not reconfigure logging
    parser = argparse.ArgumentParser(
        description="Generate YAML workout plans from text using local LLM"
    )
    parser.add_argument("--plan", type=str, help="Path to plan text file")
    parser.add_argument("--output", type=str, help="Output YAML path")
    parser.add_argument(
        "--api", choices=["ollama", "openai"], default="ollama",
        help="LLM API type: ollama (default) or openai (LM Studio, etc.)"
    )
    parser.add_argument(
        "--url", type=str, default=None,
        help="LLM API base URL (default: auto based on --api)"
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="Model name (default: gemma2:2b for ollama, qwen3.8-27b@iq3_xxs for openai)"
    )
    parser.add_argument(
        "--retries", type=int, default=MAX_RETRIES,
        help="Maximum total attempts per workout, including the initial request (default: 2)"
    )
    parser.add_argument(
        "--openai-mode",
        choices=["auto", "chat", "completions"],
        default="auto",
        help=(
            "OpenAI-compatible request mode: auto (default), chat only, "
            "or completions only"
        ),
    )
    parser.add_argument(
        "--output-format", choices=["yaml", "compact"], default="yaml",
        help="Model response format; compact is experimental and compiles through the marked parser",
    )
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=1800,
        help="Per-request timeout in seconds for the LLM call (default: 1800)",
    )
    parser.add_argument(
        "--workouts",
        type=int,
        default=0,
        metavar="N",
        help=(
            "Expected total number of workouts in the plan. "
            "Use when auto-detection fails (e.g. phase-structured or free-form plans). "
            "If omitted and auto-detection returns 0, you will be prompted interactively."
        ),
    )
    args = parser.parse_args()

    # Resolve API defaults based on --api type
    if args.url is None:
        args.url = (
            "http://localhost:11434" if args.api == "ollama"
            else "http://127.0.0.1:1234/v1"
        )
    if args.model is None:
        args.model = (
            "gemma2:2b" if args.api == "ollama"
            else "qwen3.8-27b@iq3_xxs"
        )

    logger.info("=" * 70)
    logger.info("LLM Workout Plan → YAML Generator")
    logger.info("=" * 70)
    logger.info(f"API: {args.api} @ {args.url} (model: {args.model})")
    if args.api == "openai":
        logger.info(f"OpenAI mode: {args.openai_mode}")
    logger.info(f"Request timeout: {args.timeout_sec}s")

    # Find input file
    try:
        plan_path = Path(args.plan) if args.plan else find_plan_file()
        plan_text = extract_text_from_file(plan_path)
    except (FileNotFoundError, ValueError) as e:
        logger.error(str(e))
        return False

    logger.info(f"Plan file: {plan_path.name} ({len(plan_text)} chars)")

    # Only an explicit user hint is binding; free-form input needs no count.
    workouts_hint = args.workouts

    from ..marked_plan import is_marked_plan

    if is_marked_plan(plan_text):
        # The marked format is compiled deterministically -- no model needed.
        from ..plan_service import build_marked_plan_draft

        logger.info("Marked plan format detected: compiling without the LLM")
        draft = build_marked_plan_draft(plan_text)
        for warning in draft.warnings:
            logger.warning(f"  {warning}")
        for error in draft.validation_errors:
            logger.error(f"  {error}")
        yaml_output = draft.yaml_text
    else:
        client = UnifiedLLMClient(
            model=args.model,
            base_url=args.url,
            api_type=args.api,
            openai_mode=args.openai_mode,
            request_timeout_sec=args.timeout_sec,
            segment_cache_dir=ARTIFACTS_DIR / "llm_segment_cache",
            output_format=args.output_format,
        )
        client.use_rules = True
        draft = client.generate_yaml_draft(
            plan_text, max_retries=args.retries, workouts_hint=workouts_hint
        )
        for warning in draft.warnings:
            logger.warning(f"  {warning}")
        if draft.failed_segments:
            logger.warning(
                f"{len(draft.failed_segments)} workout(s) were not generated; the others are saved. "
                "Fix those source blocks and re-run: finished workouts come from the cache."
            )
        yaml_output = draft.yaml_text

    if not yaml_output:
        logger.error("Failed to generate valid YAML")
        return False

    # Save output
    output_path = Path(args.output) if args.output else DEFAULT_OUTPUT
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml_output, encoding="utf-8")

    logger.info(f"\nSaved: {output_path}")
    logger.info(f"Next step: python -m garmin_fit.cli run --plan {output_path}")
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
