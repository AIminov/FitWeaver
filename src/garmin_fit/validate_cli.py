from __future__ import annotations

import argparse
from typing import Sequence

from .workflow import workflow_validate_yaml

from ._shared_cli import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate YAML plans using SDK rules.")
    parser.add_argument("--plan", metavar="YAML_PATH", help="Validate a specific YAML plan")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    return workflow_validate_yaml(plan_path=args.plan)
