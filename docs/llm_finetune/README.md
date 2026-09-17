# FitWeaver → local LLM fine-tuning: next steps

Context: `SCHEMA_V1.md` (audit + target schema) and `golden_examples_v1.yaml`
(13 seed groups, 8 VALID promoted from `src/garmin_fit/llm/strict_examples.yaml`
+ paraphrases, 1 hallucination-trap, 2 `NEEDS_CLARIFICATION`, 2 `UNSUPPORTED`)
are done — this covers step 1-3 of your plan's point 20 ("Audit → Schema v1 →
~50 initial golden examples", partially: 13 groups / ~30 text variants so
far, not yet 50). Everything below is unstarted; nothing here has touched
`src/garmin_fit/` or the production pipeline.

## Immediate next step: expand to ~50-100 groups (point 20, step 3/6)

Before writing any training code, grow `golden_examples_v1.yaml`:

1. **Add 2-4 more paraphrases to each of the 8 existing VALID groups.**
   Prioritize the styles you already have (`formal_plan`, `coach_shorthand`,
   `conversational`) plus a genuinely terse trainer note like your own
   example `2р + СБУ + 5х1000 4.35-4.40 отд 2' + 2з` — none of the current
   groups have anything that dense yet.
2. **Add new canonical groups for step-type coverage gaps.** Every VALID
   group so far uses `dist_hr`/`dist_pace`/`time_pace`/`dist_open`/`repeat`/
   `sbu_block`. Missing: `time_hr`, `time_step`/`open_step` as a *standalone*
   step (not just inside `sbu_block`), and a **nested repeat** (3 sets of
   4x400m — `llm_contract.yaml`'s repeat_block rule explicitly calls this
   out; `hills_2x5x40m` has two sequential repeat blocks but not a nested
   one).
3. **Add 3-5 more `NEEDS_CLARIFICATION` groups.** Real ambiguity classes
   beyond the two seeded: mixed units ("5 кругов" — track laps or generic
   repeats of unstated distance?), missing recovery type ("5x1000 отдых 2
   мин" — jogging or standing? matters for `dist_open` vs a bare pause,
   though today both map to `intensity: recovery`, so this may turn out to
   be a non-issue — verify against the schema before writing the example),
   incomplete pace range ("быстрее 5:00" — no upper bound).
4. **Add 2-3 more `UNSUPPORTED` groups**: swimming/cycling brick sessions,
   a plan text in a third language, a request for a target FitWeaver has no
   field for (cadence, VO2max target).
5. Every new example must pass the same check used above:
   ```bash
   python3 -c "
   import yaml, sys; sys.path.insert(0, 'src')
   from garmin_fit.plan_schema import WorkoutPlanSchema
   from garmin_fit.plan_validator import validate_plan_data_detailed
   data = yaml.safe_load(open('docs/llm_finetune/golden_examples_v1.yaml', encoding='utf-8'))
   for g in data['groups']:
       if g['status'] == 'VALID':
           WorkoutPlanSchema.model_validate(g['canonical'])
           errors, _ = validate_plan_data_detailed(g['canonical'])
           assert not errors, (g['group_id'], [e.message for e in errors])
   print('ok')
   "
   ```
   Turn this into a real pytest under `tests/` once the file stabilizes
   (mirrors how `tests/fixtures/llm_benchmark/*.yaml` is already checked).

## Step 4: FunctionGemma representation

Once you have ~50 groups, pick the function-call framing per §4 of
`SCHEMA_V1.md` (single `create_workout_plan(workouts=[...])`, JSON Schema
derived from `get_plan_json_schema()`) and write a small converter:
`golden_examples_v1.yaml` group → FunctionGemma chat-turn training example
(system/user/assistant-function-call triple). Keep this converter separate
from `plan_schema.py`/`plan_domain.py` — it should *read* those, never
duplicate their field lists (that's exactly the `llm_contract.yaml`
duplication risk flagged in `SCHEMA_V1.md` §1, don't repeat it for
FunctionGemma).

## Step 5: baseline (point 20, step 5)

Run the ~50 groups' text variants through FunctionGemma 270M zero-shot (no
fine-tuning yet) and record: JSON/function-call validity rate, schema
validity rate (via the same `plan_schema.py`/`plan_validator.py` you already
have — reuse `llm/benchmark.py`'s check machinery, don't write a second
validator), and qualitatively whether failures are call-shape problems (§4
caveat) vs. genuine domain misunderstanding vs. Russian-language
comprehension (flagged as the top risk in the earlier discussion — test this
explicitly and separately: run a handful of `coach_shorthand`/`conversational`
Russian variants and check if the model's *raw* function-call arguments even
approximate the right numbers, before scoring schema validity).

Do **not** treat a bad zero-shot score as disqualifying (per your point 14) —
only compare base vs. fine-tuned on the same benchmark.

## Step 6+: only after the baseline exists

Dataset scaling (point 12/13), Unsloth LoRA fine-tune (point 6), and the
`NEEDS_CLARIFICATION`/`UNSUPPORTED` + semantic-exact-match benchmark metrics
(point 15, §5 of `SCHEMA_V1.md`) all build on a baseline number existing
first — don't parallelize this with dataset expansion; you won't know if
50 or 500 groups are enough until you've seen how far zero-shot already gets
you (this is why the plan's step 20 orders them baseline-before-expand).
