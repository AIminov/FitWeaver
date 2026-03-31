"""
CLI for LLM-based YAML generation from training plan text.

Usage:
    python -m garmin_fit.llm.request_cli
    python -m garmin_fit.llm.request_cli --plan Plan/plan.txt --output Plan/plan.yaml
    python -m garmin_fit.llm.request_cli --api openai --url http://localhost:1234/v1
    python -m garmin_fit.llm.request_cli --api openai --openai-mode completions
"""

import argparse
import logging
import sys
from pathlib import Path

from ..config import PLAN_DIR
from .client import UnifiedLLMClient

logging.basicConfig(level=logging.INFO, format="%(message)s")
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
        help="Model name (default: gemma2:2b for ollama, local-model for openai)"
    )
    parser.add_argument(
        "--retries", type=int, default=3,
        help="Max retry attempts for validation"
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
            else "http://localhost:1234/v1"
        )
    if args.model is None:
        args.model = (
            "gemma2:2b" if args.api == "ollama"
            else "local-model"
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

    # Resolve expected workout count
    workouts_hint = args.workouts
    if workouts_hint == 0:
        from ..plan_processing import normalize_source_text
        analysis = normalize_source_text(plan_text)
        if analysis.expected_workouts > 0:
            logger.info(f"Auto-detected workout count: {analysis.expected_workouts}")
            workouts_hint = analysis.expected_workouts
        else:
            logger.info("Could not auto-detect workout count from plan structure.")
            try:
                raw = input("How many workouts does the plan contain? (Enter to skip): ").strip()
                if raw.isdigit() and int(raw) > 0:
                    workouts_hint = int(raw)
                    logger.info(f"Using user-supplied workout count: {workouts_hint}")
            except EOFError:
                pass  # non-interactive context — proceed without hint

    # Generate YAML
    client = UnifiedLLMClient(
        model=args.model,
        base_url=args.url,
        api_type=args.api,
        openai_mode=args.openai_mode,
        request_timeout_sec=args.timeout_sec,
    )

    yaml_output = client.generate_yaml_from_plan(
        plan_text, max_retries=args.retries, workouts_hint=workouts_hint
    )

    if not yaml_output:
        logger.error("Failed to generate valid YAML")
        return False

    # Save output
    output_path = Path(args.output) if args.output else DEFAULT_OUTPUT
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml_output, encoding="utf-8")

    logger.info(f"\nSaved: {output_path}")
    logger.info(f"Next step: python get_fit.py --plan {output_path}")
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
