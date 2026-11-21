from pathlib import Path

import pytest
import yaml

from garmin_fit.decision_candidates import build_decision
from garmin_fit.decision_eval import score_decisions


def test_rules_preserve_number_and_abstain_on_ambiguous_clock():
    decision = build_decision("7×600 м, 4:21, отдых 90 сек.")
    assert decision.preferred == "clarify"
    assert [(item.meaning, item.value) for item in decision.candidates] == [
        ("interval_duration", "4:21"), ("pace_per_km", "4:21"),
    ]
    assert build_decision("7×600 м, каждый отрезок за 4:21.").preferred == "a"
    assert not build_decision("Пробежка по самочувствию.").candidates


def test_decision_pilot_distinguishes_wrong_choices_from_abstentions():
    path = Path(__file__).resolve().parents[1] / "docs/golden_dataset/decision_pilot.yaml"
    cases = yaml.safe_load(path.read_text(encoding="utf-8"))["cases"]
    predictions = {case["id"]: "clarify" for case in cases}
    baseline = score_decisions(cases, predictions)
    assert baseline["wrong_selection"] == 0
    assert baseline["unnecessary_clarification"] > 0

    predictions["unclear_pace"] = "a"
    result = score_decisions(cases, predictions)
    assert result["wrong_selection"] == result["missed_clarification"] == 1
    assert result["correct"] == baseline["correct"] - 1

    predictions["unclear_pace"] = "unknown"
    with pytest.raises(ValueError, match="unknown choice"):
        score_decisions(cases, predictions)
