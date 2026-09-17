# FitWeaver → local LLM fine-tuning: next steps

Context: `SCHEMA_V1.md` (audit + target schema) and `golden_examples_v1.yaml`
now have **62 groups / 77 text variants** — comfortably past step 1-3 of
your plan's point 20 ("Audit → Schema v1 → ~50 initial golden examples").
Made up of:
- 13 seed groups (v1): 8 VALID promoted from
  `src/garmin_fit/llm/strict_examples.yaml` + paraphrases, 1
  hallucination-trap, 2 `NEEDS_CLARIFICATION`, 2 `UNSUPPORTED`.
- 10 groups promoted from real confirmed-on-watch structures out of the
  marathon-cycle chat ("Структура тренировочного плана на три забега",
  `fitweaver_golden_dataset.zip`) — 9 `VALID`, 1 reclassified to
  `NEEDS_CLARIFICATION` (see `REAL_DATASET_NOTES.md` for why, and for the
  `back_to_offset` finding from that chat re-verified against current code).
- 28 synthetic groups (v2) closing the structural gaps the v1 file had
  (nested repeat, standalone `open_step`/`time_hr`, pace-based variants of
  HR-based patterns, more `NEEDS_CLARIFICATION`/`UNSUPPORTED` variety),
  using the real marathon-cycle HR zones/paces for domain-consistent
  numbers.
- 11 groups (v3, `source: web_inspired`) added from public running-coaching
  terminology confirmed via web search — see "Web-search expansion" below.

All 44 `VALID` canonical structures are re-validated against
`WorkoutPlanSchema` + `validate_plan_data_detailed()` on every regeneration
(see the check command below) — 0 errors as of this version. Nothing here
has touched `src/garmin_fit/` or the production pipeline.

## Web-search expansion (v3, 11 new groups)

Searched for how Russian/English running coaching content actually describes
workouts, to pull in structures and terminology the two source chats hadn't
produced yet. Text is original — written for this dataset in the found
style/terminology, not copied from any source. Group IDs use
`source: web_inspired`.

What came out of it:
- **Yasso 800s** (`yasso_800_10x_marathon_pace`) — 10x800m at a pace derived
  from the marathon goal time (h:mm → m:ss), equal-time jog recovery. Chose
  numbers consistent with this project's own LT pace from `REAL_DATASET_NOTES.md`'s
  context (goal 3:45 marathon → ~4:40/km), so it also cross-checks against
  the real data rather than being an arbitrary example.
- **Run/walk intervals** (`beginner_run_walk_intervals_6x5_1`) — a structural
  variant not covered before: alternating *running* (not a rest) with a
  *walking* recovery, common in beginner plans.
- **Relative-pace long run** (`long_run_relative_to_race_pace`) — pace stated
  only as an offset from another stated pace ("30-60 sec/km slower than my
  race pace of 4:30"), not as absolute numbers. Tests whether the model can
  resolve one pace through another rather than pattern-matching a bare
  MM:SS.
- **Mile repeats** and **cruise intervals** (`mile_repeats_5x1600_short_rest`,
  `cruise_intervals_4x1600_short_rest`) — same rough pace zone as existing
  threshold groups but different terminology and very different recovery
  length (60s vs 2min), to decouple "recognizes threshold pace" from
  "recognizes recovery duration" as separate model behaviors.
- **Taper-week shakeout** (`taper_week_easy_short_20min`).
- **3 new `NEEDS_CLARIFICATION`**: fartlek "by feel" with a stated total time
  but no rep count/pace (`fartlek_by_feel_no_targets`), tempo defined only by
  perceived effort ("hard to talk") with no number at all
  (`tempo_effort_only_no_numbers`), and landmark-based surges ("to the next
  lamppost") that don't resolve to km/seconds without knowing the route
  (`landmark_based_fartlek_unknown_distance`).
- **2 new `UNSUPPORTED`**: circuit/strength training
  (`unsupported_circuit_training_strength` — deliberately phrased with
  rounds+rest, structurally close to a running repeat block, to check the
  model classifies by *content* not by *shape*) and a core-only session
  (`unsupported_core_workout_only`).

Sources consulted (for terminology/structure, not copied text):
- [Марафонец — Что такое тест Яссо](https://marathonec.ru/test-yasso/)
- [Марафонец — Что такое фартлек](https://marathonec.ru/fartlek/)
- [T-Ж — Что такое фартлек](https://t-j.ru/what-is-fartlek/)
- [T-Ж — План тренировок для бега](https://t-j.ru/running-training-plan/)
- [Академия марафона — Беговые тренировки](https://academymarathon.ru/blog/begovye-trenirovki)

## Still-open gaps before calling the dataset "done enough" for baseline

The structural gaps are closed, but coverage is still thin in a few places
worth another pass before or during baseline analysis (point 20, step 5):

1. **Paraphrase depth is uneven.** The 10 real groups and most v2/v3
   synthetic groups have only 1-2 text variants; only the original 8
   promoted groups have 2-3. If the baseline shows the model is sensitive to
   phrasing style rather than domain content, that's the first place to add
   more variants — don't do it speculatively first.
2. **No genuinely long/multi-day input** (a whole week of sessions in one
   text block, like `tests/fixtures/llm_benchmark/plan_10workouts_2026_03.yaml`'s
   source). Every current group is single-workout-per-text. Worth adding a
   couple of multi-workout groups once you decide whether FunctionGemma's
   training examples should be single- or multi-workout (probably
   single-workout, matching per-example golden pairs — but confirm before
   spending time on it).
3. **`NEEDS_CLARIFICATION`/`UNSUPPORTED` still outnumbered by `VALID`**
   (10 and 8 vs. 44) — realistic for a "correct classification is easy"
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

Now that the dataset has 60+ groups, pick the function-call framing per §4 of
`SCHEMA_V1.md` (single `create_workout_plan(workouts=[...])`, JSON Schema
derived from `get_plan_json_schema()`) and write a small converter:
`golden_examples_v1.yaml` group → FunctionGemma chat-turn training example
(system/user/assistant-function-call triple). Keep this converter separate
from `plan_schema.py`/`plan_domain.py` — it should *read* those, never
duplicate their field lists (that's exactly the `llm_contract.yaml`
duplication risk flagged in `SCHEMA_V1.md` §1, don't repeat it for
FunctionGemma).

## Step 5: baseline (point 20, step 5) — `run_baseline.py` is ready

`docs/llm_finetune/run_baseline.py` runs every VALID group's text variants
through the model and scores the result with a real semantic-exact-match
comparator (order-independent, `MM:SS` pace constants resolved via
`plan_domain.PACE_CONSTANT_VALUES`, int/float normalized) against the
group's canonical structure — closing the §5 gap in `SCHEMA_V1.md` (no
second validator: it reuses `WorkoutPlanSchema`/`validate_plan_data_detailed`
indirectly through `UnifiedLLMClient.generate_yaml_draft`, which already
runs them). `NEEDS_CLARIFICATION`/`UNSUPPORTED` groups are skipped for now —
the current prompt pipeline has no way to emit or grade that status yet
(§3).

It deliberately reuses the **existing production prompt**
(`garmin_fit.llm.prompt`/`UnifiedLLMClient`) rather than a function-calling
one — the first real measurement should be "can this model follow
FitWeaver's existing YAML contract at all, zero-shot, in Russian" before
committing to the §4 function-call framing decision.

**Self-test first** (no LLM server needed — proves the comparator itself is
sound: scores each canonical structure against itself, 44/44 must match,
and against a deliberately mutated copy, 44/44 mutations must be caught):

```bash
python docs/llm_finetune/run_baseline.py --dry-run
```

**Real run**, once FunctionGemma 270M is loaded and serving in LM Studio
(search "functiongemma" in LM Studio's model search, load `functiongemma-270m-it`,
start the local server — same workflow this project already uses for Qwen):

```bash
python docs/llm_finetune/run_baseline.py \
  --api openai --url http://127.0.0.1:1234/v1 --model functiongemma-270m-it
```

`--retries 1` is the default on purpose — this is a *zero-shot* baseline,
not the production retry-corrected pipeline; raising it would measure the
retry loop's ability to paper over mistakes, not the model's raw
understanding. Report (schema-valid rate, semantic-exact-match rate,
per-variant diffs) prints to stdout and saves to
`Build_artifacts/llm_finetune_baseline.<model>.json` (gitignored).

Explicitly separate, when reading results: whether failures are
call-shape problems (not applicable yet — this baseline doesn't use
function-calling), genuine domain misunderstanding, or Russian-language
comprehension (flagged as the top risk in the earlier discussion — check
the per-variant diffs for `coach_shorthand`/`conversational` style variants
specifically; if the model's raw output doesn't even approximate the right
numbers there while doing fine on `formal_plan` style, that's a language
problem, not a domain one).

Do **not** treat a bad zero-shot score as disqualifying (per your point 14) —
only compare base vs. fine-tuned on the same benchmark, using this same
script (point it at the fine-tuned model's LM Studio/server endpoint later).

## Step 6+: only after the baseline exists

Dataset scaling (point 12/13), Unsloth LoRA fine-tune (point 6), and the
`NEEDS_CLARIFICATION`/`UNSUPPORTED` + semantic-exact-match benchmark metrics
(point 15, §5 of `SCHEMA_V1.md`) all build on a baseline number existing
first — don't parallelize this with dataset expansion; you won't know if
50 or 500 groups are enough until you've seen how far zero-shot already gets
you (this is why the plan's step 20 orders them baseline-before-expand).
