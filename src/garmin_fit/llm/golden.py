"""Golden dataset helpers: fact-level comparison and suite generation.

The golden dataset (``docs/golden_dataset/golden_examples_v1.yaml``) pairs
workout texts with a reference ("canonical") Garmin YAML. Comparison works on
facts -- step kind, distance/duration, repeat structure and target -- so key
order or equivalent spellings do not matter.

Some references add targets that the source text does not state. Those may be
omitted, but a target explicitly stated by the source must survive. An
upper-only heart-rate cap may use a different lower bound in an older
reference; that exception applies only when the source actually states a cap.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

DEFAULT_GOLDEN_PATH = Path(__file__).resolve().parents[3] / "docs" / "golden_dataset" / "golden_examples_v1.yaml"
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
    if step.get("hr_low") is not None:
        target = ("hr", step.get("hr_low"), step.get("hr_high"))
    elif step.get("pace_fast") is not None:
        target = ("pace", str(step.get("pace_fast")), str(step.get("pace_slow")))
    elif step.get("cad_low") is not None:
        target = ("cadence", step.get("cad_low"), step.get("cad_high"))
    km = round(float(step["km"]), 3) if step.get("km") is not None else None
    seconds = int(step["seconds"]) if step.get("seconds") is not None else None
    return ("step", km, seconds, target)


def compare_to_canonical(
    steps: list[dict[str, Any]],
    canonical: list[dict[str, Any]],
    *,
    source_text: str | None = None,
    allow_missing_targets: bool = False,
) -> list[str]:
    """Differences between generated steps and the reference; empty list when they agree.

    A missing reference target is tolerated only when explicitly requested
    and the generated workout still includes every occurrence stated by the
    source. References sometimes copy one stated target to other steps.
    Without source text, the comparison is exact.
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
            _source_cap_equivalent(ours[-1], reference[-1], source_text)
            or (
                ours[-1] is None
                and allow_missing_targets
                and source_text is not None
            )
        ):
            problems.append(f"step {index}: expected target {reference[-1]}, got {ours[-1]}")
        if ours[0] == "step" and reference[0] == "step":
            got_intensity = steps[index].get("intensity")
            expected_intensity = canonical[index].get("intensity")
            if got_intensity and expected_intensity and got_intensity != expected_intensity:
                problems.append(
                    f"step {index}: expected intensity {expected_intensity}, got {got_intensity}"
                )
    if allow_missing_targets and source_text:
        for target in {fact[-1] for fact in want if fact[0] == "step" and fact[-1] is not None}:
            stated = _stated_target_count(target, source_text)
            if not stated:
                continue
            reference_count = sum(fact[-1] == target for fact in want)
            required = min(stated, reference_count)
            actual = sum(
                fact[-1] == target or _source_cap_equivalent(fact[-1], target, source_text)
                for fact in got
            )
            if actual < required:
                problems.append(
                    f"source states target {target} {required} time(s), generated {actual}"
                )
    return problems


def _source_states_hr_cap(source_text: str | None, high: object) -> bool:
    if not source_text or not isinstance(high, int):
        return False
    return bool(re.search(
        rf"(?:\bдо\b|не\s+выше|не\s+более|\bмакс(?:имум)?\.?|<=?|≤)\s*{high}(?!\d)",
        source_text, re.IGNORECASE,
    ))


def _source_cap_equivalent(
    ours: tuple | None, reference: tuple | None, source_text: str | None
) -> bool:
    """A reference may invent the lower bound for an explicit upper-only cap."""
    return (
        ours is not None and reference is not None
        and ours[0] == reference[0] == "hr"
        and ours[1] == 60 and ours[2] == reference[2]
        and _source_states_hr_cap(source_text, ours[2])
    )


def _stated_target_count(reference: tuple, source_text: str) -> int:
    """Count numeric source targets matching this reference target."""
    kind = reference[0]
    text = source_text.replace("–", "-").replace("—", "-").replace("−", "-")
    if kind == "hr":
        low, high = reference[1:3]
        if _source_states_hr_cap(text, high):
            return len(re.findall(
                rf"(?:\bдо\b|не\s+выше|не\s+более|\bмакс(?:имум)?\.?|<=?|≤)\s*{high}(?!\d)",
                text, re.IGNORECASE,
            ))
        return len(re.findall(rf"(?<!\d){low}\s*-\s*{high}(?!\d)", text))
    if kind == "cadence":
        low, high = reference[1:3]
        return len(re.findall(rf"(?<!\d){low}\s*-\s*{high}(?!\d)", text))
    if kind == "pace":
        fast, slow = reference[1:3]
        normalized = re.sub(r"(?<=\d)\.(?=\d{2}\b)", ":", text)
        return len(re.findall(
            rf"(?<!\d){re.escape(fast)}\s*-\s*{re.escape(slow)}(?!\d)", normalized,
        ))
    return 0


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
