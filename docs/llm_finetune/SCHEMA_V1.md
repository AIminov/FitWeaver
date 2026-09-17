# FitWeaver Workout Schema v1 — audit + LLM fine-tuning contract

Status: draft, v1. Produced for the FunctionGemma/Unsloth fine-tuning experiment
(see `README.md` in this folder). Not wired into the runtime pipeline — this is
a stable target contract for training data and benchmark, layered on top of the
existing production schema without changing it.

## 1. Source of truth (do not duplicate)

The canonical workout representation already exists and is exercised in
production. Schema v1 below is a documentation + additive layer over it, not a
new model.

| Concern | File | Notes |
|---|---|---|
| Structural/type validation | `src/garmin_fit/plan_schema.py` | Pydantic v2, discriminated union on `type`. `WorkoutPlanSchema.model_json_schema()` is already exported for prompts (`get_plan_json_schema()` in `llm/prompt.py`). |
| Shared constants / aliases | `src/garmin_fit/plan_domain.py` | `ALLOWED_INTENSITY`, `INTENSITY_ALIASES`, `KNOWN_PACE_CONSTANTS`, `PACE_CONSTANT_VALUES`, `STEP_TYPE_ALIASES`, `STEP_REQUIRED_FIELDS`. |
| Semantic/positional validation | `src/garmin_fit/plan_validator.py` | `back_to_offset` ordering, repeat-range crossing, HR/pace ordering, drill name length. Cannot be expressed as pure per-field Pydantic rules because it needs step position. |
| FIT-index translation | `src/garmin_fit/workout_utils.py::build_yaml_to_fit_index()` | YAML step index → FIT runtime index, accounting for `sbu_block` expansion. **The LLM never sees or produces FIT indices.** |
| SBU expansion | `src/garmin_fit/sbu_block.py` | Each drill → `reps × 2` FIT steps (active + open recovery). LLM only emits `drills: [{name, seconds, reps}]`. |
| Existing prompt contract | `src/garmin_fit/llm/llm_contract.yaml` + `llm/prompt.py` | Hand-maintained restatement of the Pydantic schema for the current Qwen prompt pipeline. **Partially duplicates `plan_schema.py`** — flagged as a risk below. |
| Existing golden examples | `src/garmin_fit/llm/strict_examples.yaml` | 11 positive + 10 negative (failure) few-shot examples, already Russian-input → YAML-output pairs. This is the de-facto golden dataset seed — reused in `docs/llm_finetune/golden_examples_v1.yaml`. |
| Existing benchmark harness | `src/garmin_fit/llm/benchmark.py` + `tests/fixtures/llm_benchmark/*.yaml` | `input_path` (source text) → `yaml_path` (expected) → declarative `checks` (`step_field`, `workout_field`) + count/filename checks. Runs against a live LLM (`--mode generate`) or validates a fixture (`--mode existing`). This is the shape to extend for FunctionGemma benchmark metrics (§5). |

**Do not build a second schema.** Everything below is a name for what already
exists in `plan_schema.py`, plus one additive extension (§3) that the current
pipeline does not have yet.

## 2. Canonical structure

```
WorkoutPlan
  workouts: list[Workout]      # min 1

Workout
  filename: str                # must equal `name`
  name: str
  desc: str | null
  type_code: str | null        # one of allowed_type_codes (llm_contract.yaml)
  distance_km: float | null    # never invent — null if unknown
  estimated_duration_min: float | null
  steps: list[Step]            # min 1, ordered — order is semantic

Step (discriminated union on `type`)
  dist_hr    {km>0, hr_low, hr_high, intensity?}
  time_hr    {seconds>0, hr_low, hr_high, intensity?}
  dist_pace  {km>0, pace_fast, pace_slow, intensity?}
  time_pace  {seconds>0, pace_fast, pace_slow, intensity?}
  dist_open  {km>0, intensity?}          # distance, no target
  time_step  {seconds>0, intensity?}     # duration, no target
  open_step  {intensity?}                # lap-button step, no duration/target
  repeat     {back_to_offset>=0, count>0}
  sbu_block  {drills?: list[Drill]}      # drill = {name<=12chars, seconds>0, reps>0}
```

Business rules an LLM output must satisfy (all enforced downstream by
`plan_schema.py` + `plan_validator.py` — a fine-tuned model should internalize
them, but Python remains the last line of defense, per your point 17):

- `hr_low < hr_high`; both in `30..240`.
- `pace_fast`/`pace_slow` are **quoted strings** `"MM:SS"` (or one of the 8
  symbolic constants `EASY_F/EASY_S/AERO_F/AERO_S/LONG_F/LONG_S/TEMPO_F/TEMPO_S`
  — never invent new symbolic names, and never expand them yourself; the
  numeric value they map to lives only in `plan_domain.PACE_CONSTANT_VALUES`).
  `pace_fast` must be numerically faster (lower MM:SS) than `pace_slow`.
- `km` / `seconds` strictly `> 0`.
- `intensity` ∈ `{active, warmup, cooldown, recovery}` only — never
  `easy/hard/fast/slow/main/work/light` even if that's the source wording
  (`plan_domain.INTENSITY_ALIASES` documents the mapping, but the *output*
  must always be the canonical 4 values).
- `back_to_offset` is a **0-based YAML step index**, always `< current step
  index`, pointing at the first step of the repeating group (not the last).
  Nested repeat ranges are allowed only if one fully contains the other —
  crossing ranges are rejected by `plan_validator.py`.
- `drills[].name` ≤ 12 characters (Garmin watch display limit); drills have
  **only** `name/seconds/reps`, never a `type` field.
- Single upper-bound HR cap in the source (e.g. "пульс до 140") → emit
  `hr_low=80` (the project's fixed floor for cap-only ranges), `hr_high=<cap>`.
  This is a **designed convention**, not the model inventing a value — codify
  it as a rule, not as a number the model has to "guess".
- `distance_km` / `estimated_duration_min` at the workout level are optional
  and must be `null` when not explicitly derivable — never invented to fill
  the field.
- Rest/non-running days (strength, sauna, stretching, plank...) produce **no**
  workout entry unless explicit running content is present.

These are exactly the rules already encoded in `llm_contract.yaml`'s
`validation_rules`/`forbidden_patterns` and in `strict_examples.yaml`'s
`failure_examples` — reuse those files as the rule source, don't re-derive.

## 3. Gap: no machine-checkable `NEEDS_CLARIFICATION` / `UNSUPPORTED` status

Your plan's point 10 requires this as a first-class output state. Today the
closest equivalent is `plan_processing.detect_source_ambiguities()`, which
returns free-text warning strings (approximate values, "или", "?", "по
самочувствию", ...) folded into repair notes — it **never blocks generation
or produces a structured status**; the current pipeline always tries to
produce a best-effort `workouts:` YAML.

For the fine-tuning target schema, add one additive top-level wrapper not
present in `plan_schema.py` today:

```yaml
status: VALID | NEEDS_CLARIFICATION | UNSUPPORTED
# VALID:
workouts: [...]                 # exactly today's WorkoutPlanSchema
# NEEDS_CLARIFICATION:
question: "4:30 — продолжительность интервала или темп 4:30/км?"
# UNSUPPORTED:
reason: "strength/gym session, not a running workout"
```

This is additive and backward compatible: `status: VALID` + `workouts:` is a
strict superset of what `plan_schema.py` already validates, so existing
fixtures need zero changes. Do not wire this into the production Qwen
pipeline yet — it is the target contract for the FunctionGemma dataset and
benchmark only, until proven out.

## 4. Function-call representation for FunctionGemma (your point 18)

Recommendation: **one `create_workout_plan(workouts: [...])` call**, mirroring
`WorkoutPlanSchema` directly, rather than incremental `add_step`/`add_repeat`
calls. Reasons:
- `steps` is already a flat, order-significant list — FIT semantics are
  positional (`back_to_offset` is an index into that exact list). Splitting
  into stateful incremental calls reintroduces exactly the kind of
  index-bookkeeping problem `back_to_offset` already causes for humans (see
  the "CRITICAL" section of `CLAUDE.md`) — now for the model instead of a UI.
- `get_plan_json_schema()` (`llm/prompt.py:282`) already emits a JSON Schema
  generated from the same Pydantic models — that can be handed to
  FunctionGemma's function-calling format mechanically, keeping one source of
  truth (extend it, don't fork it).

Caveat, don't decide from first principles: FunctionGemma's own fine-tuning
examples may lean toward smaller, granular calls. Treat this as a hypothesis
to check in the baseline step (your point 20, step 5), not a fixed decision —
if flat nested JSON scores poorly zero-shot specifically due to call shape
(not domain knowledge), revisit before investing in the dataset.

## 5. Benchmark metrics gap vs. your point 15

`llm/benchmark.py` today gives you: schema/pydantic validity, per-field
`step_field`/`workout_field` checks, filename/count checks, and a source-fact
cross-check (`_extract_workout_facts_from_source_text` /
`_evaluate_workouts_against_source_fact` in `llm/client.py` — this is already
a rough hallucination/omission detector: it re-derives expected date/km/hr/pace
facts from the source text via regex and checks the generated workout doesn't
contradict them). Missing for your point 15/16: a true
**workout-semantic-exact-match** normalizer (order-independent key
comparison, `120 == 120.0`, canonical pace-constant resolution) and
`clarification_accuracy` / `unsupported_classification_accuracy` (need §3's
status field to exist before these are measurable). Build these as new
`evaluate_case_expectations` check kinds in `benchmark.py` rather than a
parallel evaluator.

## 6. What Schema v1 is, concretely

**Schema v1 = `plan_schema.py` (unchanged) + the `status` wrapper in §3.**
No changes needed to `plan_schema.py`, `plan_validator.py`, or the FIT
builders. The dataset and benchmark work (next: `golden_examples_v1.yaml`)
target this wrapped schema; production YAML files stay exactly as they are
today (implicitly `status: VALID`, wrapper omitted).
