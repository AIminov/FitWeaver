# FitWeaver → local LLM fine-tuning: next steps

Context: `SCHEMA_V1.md` (audit + target schema) and `golden_examples_v1.yaml`
now have **51 groups / 64 text variants** — this satisfies step 1-3 of your
plan's point 20 ("Audit → Schema v1 → ~50 initial golden examples"). Made up
of:
- 13 seed groups (v1): 8 VALID promoted from
  `src/garmin_fit/llm/strict_examples.yaml` + paraphrases, 1
  hallucination-trap, 2 `NEEDS_CLARIFICATION`, 2 `UNSUPPORTED`.
- 10 groups promoted from real confirmed-on-watch structures out of the
  marathon-cycle chat ("Структура тренировочного плана на три забега",
  `fitweaver_golden_dataset.zip`) — 9 `VALID`, 1 reclassified to
  `NEEDS_CLARIFICATION` (see `REAL_DATASET_NOTES.md` for why, and for the
  `back_to_offset` finding from that chat re-verified against current code).
- 28 new synthetic groups closing the structural gaps the v1 file had
  (nested repeat, standalone `open_step`/`time_hr`, pace-based variants of
  HR-based patterns, more `NEEDS_CLARIFICATION`/`UNSUPPORTED` variety),
  using the real marathon-cycle HR zones/paces for domain-consistent
  numbers.

All 38 `VALID` canonical structures are re-validated against
`WorkoutPlanSchema` + `validate_plan_data_detailed()` on every regeneration
(see the check command below) — 0 errors as of this version. Nothing here
has touched `src/garmin_fit/` or the production pipeline.

## Still-open gaps before calling the dataset "done enough" for baseline

The structural gaps are closed, but coverage is still thin in a few places
worth another pass before or during baseline analysis (point 20, step 5):

1. **Paraphrase depth is uneven.** The 10 real groups have exactly 1 text
   variant each (the original coach/user note) — no paraphrases yet. The 28
   new synthetic groups mostly have 1-2. Only the original 8 promoted groups
   have 2-3. If the baseline shows the model is sensitive to phrasing style
   rather than domain content, that's the first place to add more variants
   — don't do it speculatively first.
2. **No genuinely long/multi-day input** (a whole week of sessions in one
   text block, like `tests/fixtures/llm_benchmark/plan_10workouts_2026_03.yaml`'s
   source). Every current group is single-workout-per-text. Worth adding a
   couple of multi-workout groups once you decide whether FunctionGemma's
   training examples should be single- or multi-workout (probably
   single-workout, matching per-example golden pairs — but confirm before
   spending time on it).
3. **`NEEDS_CLARIFICATION`/`UNSUPPORTED` still outnumbered by `VALID`**
   (7 and 6 vs. 38) — realistic for a "correct classification is easy"
   sanity check, but your point 15 wants `clarification_accuracy` and
   `unsupported_classification_accuracy` as real metrics; a handful more of
   each, sourced from actual ambiguous coach notes as they arrive, will
   make those numbers less noisy.

Every new example must pass the same check used above:
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

Now that the dataset has 50+ groups, pick the function-call framing per §4 of
`SCHEMA_V1.md` (single `create_workout_plan(workouts=[...])`, JSON Schema
derived from `get_plan_json_schema()`) and write a small converter:
`golden_examples_v1.yaml` group → FunctionGemma chat-turn training example
(system/user/assistant-function-call triple). Keep this converter separate
from `plan_schema.py`/`plan_domain.py` — it should *read* those, never
duplicate their field lists (that's exactly the `llm_contract.yaml`
duplication risk flagged in `SCHEMA_V1.md` §1, don't repeat it for
FunctionGemma).

## Step 5: baseline (point 20, step 5)

Run the 51 groups' 64 text variants through FunctionGemma 270M zero-shot (no
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
