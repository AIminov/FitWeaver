# Golden dataset

`golden_examples_v1.yaml` — 62 groups / 77 source-text variants of running workouts, each with
its expected outcome:

- `status: VALID` + canonical `workouts:` (valid against `WorkoutPlanSchema`);
- `status: NEEDS_CLARIFICATION` — source lacks facts, expected clarifying question;
- `status: UNSUPPORTED` — cannot be expressed as a Garmin workout.

Keep all variants of one group in the same train/val/test split (leakage rule).

Use it to evaluate plan parsing: the deterministic marked parser (`marked_plan.py`) and the
local LLM path (`garmin-fit-llm-eval`). It is not wired into the production pipeline.

- `SCHEMA_V1.md` — audit of the workout schema and the target contract. Its sections about a
  FunctionGemma function-call representation are historical: the FunctionGemma 270M fine-tune
  experiment did not work and its scripts were removed on 2026-09-26 (see git history).
- `REAL_DATASET_NOTES.md` — provenance of the groups promoted from real, confirmed-on-watch plans.

The decision pilot (`decision_pilot.yaml`) tests selection among manually provided
interpretations, including `clarify`, independently of candidate generation.
Run `python -m garmin_fit.decision_eval docs/golden_dataset/decision_pilot.yaml`
for the always-clarify baseline. Append a JSON file mapping each case ID to a choice
ID to score exported predictions. A missed clarification also counts as a wrong
selection. Keep this pilot out of training and use a separate larger set for final evaluation.

Run `python -m garmin_fit.decision_eval docs/golden_dataset/decision_pilot.yaml --rules`
to score candidates generated from text. The rules were developed against this pilot,
so the score checks wiring, not generalization. Candidates represent individual
interpretation decisions, not complete workout plans.
