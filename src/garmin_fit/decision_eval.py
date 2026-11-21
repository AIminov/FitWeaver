"""Offline scoring of fixed parser choices, with no model dependency."""

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

CLARIFY = "clarify"


def score_decisions(cases: list[dict[str, Any]], predictions: dict[str, str]) -> dict[str, int]:
    ids = {case["id"] for case in cases}
    if len(ids) != len(cases) or not cases or set(predictions) != ids:
        raise ValueError("Expected exactly one prediction per unique case")

    counts = dict(total=len(cases), correct=0, selected=0, wrong_selection=0,
                  missed_clarification=0, unnecessary_clarification=0)
    for case in cases:
        answer, expected = predictions[case["id"]], case["expected"]
        choices = set(case["choices"]) | {CLARIFY}
        if answer not in choices or expected not in choices:
            raise ValueError(f"{case['id']}: unknown choice")
        counts["correct"] += answer == expected
        counts["selected"] += answer != CLARIFY
        counts["wrong_selection"] += answer != CLARIFY and answer != expected
        counts["missed_clarification"] += expected == CLARIFY and answer != CLARIFY
        counts["unnecessary_clarification"] += expected != CLARIFY and answer == CLARIFY
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", type=Path)
    parser.add_argument("predictions", type=Path, nargs="?",
                        help="JSON object mapping case IDs to choice IDs. Default: always clarify.")
    parser.add_argument("--rules", action="store_true", help="Evaluate text-only candidate rules.")
    args = parser.parse_args()
    if args.rules and args.predictions:
        parser.error("Choose --rules or a predictions file")
    cases = yaml.safe_load(args.suite.read_text(encoding="utf-8"))["cases"]
    predictions = (json.loads(args.predictions.read_text(encoding="utf-8")) if args.predictions
                   else {case["id"]: CLARIFY for case in cases})
    try:
        if args.rules:
            from .decision_candidates import build_decision

            generated = {case["id"]: build_decision(case["text"]) for case in cases}
            predictions = {key: item.preferred for key, item in generated.items()}
        scores = score_decisions(cases, predictions)
        if args.rules:
            scores["answerable_cases"] = sum(case["expected"] != CLARIFY for case in cases)
            scores["expected_option_generated"] = sum(
                case["expected"] != CLARIFY
                and case["expected"] in {candidate.key for candidate in generated[case["id"]].candidates}
                for case in cases
            )
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(scores, indent=2))


if __name__ == "__main__":
    main()
