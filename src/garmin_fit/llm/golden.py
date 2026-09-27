"""Golden dataset helpers: fact-level comparison and suite generation.

The golden dataset (``docs/golden_dataset/golden_examples_v1.yaml``) pairs
workout texts with a reference ("canonical") Garmin YAML. Comparison works on
facts -- step kind, distance/duration, repeat structure and target -- so key
order or equivalent spellings do not matter.

An upper-only heart-rate cap is encoded as ``hr_low: 60`` here and as
``hr_low: 80`` in the reference; both compare as the same cap (by hr_high).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_GOLDEN_PATH = Path(__file__).resolve().parents[3] / "docs" / "golden_dataset" / "golden_examples_v1.yaml"
_CAP_FLOORS = (60, 80)


def step_facts(step: dict[str, Any]) -> tuple:
    """(kind, measure..., target) of one YAML step; target is None when absent."""
    kind = step.get("type")
    if kind == "repeat":
        return ("repeat", step.get("back_to_offset"), step.get("count"), None)
    if kind == "sbu_block":
        drills = tuple(
            (d.get("name"), d.get("seconds"), d.get("reps")) for d in step.get("drills") or []
        )
        return ("sbu", drills, None)
    target = None
    if step.get("hr_low") in _CAP_FLOORS:
        target = ("hr_cap", step.get("hr_high"))
    elif step.get("hr_low") is not None:
        target = ("hr", step.get("hr_low"), step.get("hr_high"))
    elif step.get("pace_fast") is not None:
        target = ("pace", str(step.get("pace_fast")), str(step.get("pace_slow")))
    elif step.get("cad_low") is not None:
        target = ("cadence", step.get("cad_low"), step.get("cad_high"))
    km = round(float(step["km"]), 3) if step.get("km") is not None else None
    seconds = int(step["seconds"]) if step.get("seconds") is not None else None
    return ("step", km, seconds, target)


def compare_to_canonical(
    steps: list[dict[str, Any]], canonical: list[dict[str, Any]], *, allow_missing_targets: bool = True
) -> list[str]:
    """Differences between generated steps and the reference; empty list when they agree.

    With ``allow_missing_targets`` a generated step may omit a target the
    reference has (the reference sometimes adds targets the text does not
    state); a *different* target is always a difference.
    """
    got = [step_facts(step) for step in steps]
    want = [step_facts(step) for step in canonical]
    if len(got) != len(want):
        return [f"expected {len(want)} steps (incl. repeats), got {len(got)}"]
    problems: list[str] = []
    for index, (ours, reference) in enumerate(zip(got, want)):
        if ours[:-1] != reference[:-1]:
            problems.append(f"step {index}: expected {reference[:-1]}, got {ours[:-1]}")
        elif ours[-1] != reference[-1] and not (
            allow_missing_targets and (ours[-1] is None or _cap_of_reference_range(ours[-1], reference[-1]))
        ):
            problems.append(f"step {index}: expected target {reference[-1]}, got {ours[-1]}")
    return problems


def _cap_of_reference_range(ours: tuple | None, reference: tuple | None) -> bool:
    """Our upper-only cap vs a reference range with the same top: the reference
    invented the lower bound ("не выше 138" -> 120-138), the cap is the fact."""
    return (
        ours is not None and reference is not None
        and ours[0] == "hr_cap" and reference[0] == "hr" and ours[1] == reference[2]
    )


def build_suite_from_golden(golden_path: Path, out_dir: Path, *, suite_name: str = "golden-v1") -> Path:
    """Write one input file per VALID single-workout variant and a suite manifest.

    The suite runs with ``garmin-fit-llm-eval --suite <out_dir>/suite.yaml --mode live``;
    each case carries ``expected_steps`` for a fact-level check.
    """
    data = yaml.safe_load(Path(golden_path).read_text(encoding="utf-8"))
    inputs = Path(out_dir) / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    for group in data.get("groups", []):
        workouts = (group.get("canonical") or {}).get("workouts") or []
        if group.get("status") != "VALID" or len(workouts) != 1:
            continue
        for variant in group.get("variants", []):
            case_id = str(variant["id"])
            (inputs / f"{case_id}.txt").write_text(variant["text"], encoding="utf-8")
            cases.append({
                "id": case_id,
                "input_path": f"inputs/{case_id}.txt",
                "expected_workout_count": 1,
                "expected_steps": workouts[0]["steps"],
                "tags": [group["group_id"], str(variant.get("style", ""))],
            })
    suite_path = Path(out_dir) / "suite.yaml"
    suite_path.write_text(
        yaml.safe_dump({"suite": suite_name, "cases": cases}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return suite_path
