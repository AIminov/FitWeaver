# Notes on the real-world golden pairs (marathon-cycle chat)

Source: 10 `.md`+`.yaml` pairs extracted from the "Структура тренировочного
плана на три забега" chat (`fitweaver_golden_dataset.zip`), promoted into
`golden_examples_v1.yaml` as groups `real_*`. 9 became `VALID` groups
(`01`–`08`, `10`); `09_ladder_no_repeat` became `NEEDS_CLARIFICATION`
(`real_ladder_no_explicit_targets`) instead of `VALID` — see below.

## `09_ladder_no_repeat` → `NEEDS_CLARIFICATION`, not `VALID`

The source `.yaml` for this pair ships its own comment: the coach's text
gives a starting pace ("от 4:50") and a direction ("разбегаться каждый
отрезок"), but no explicit target per rung of the ladder. The per-segment HR
bands in that `.yaml` are a *human's* interpolation, added after the fact,
not something the coach stated. Promoting it as `VALID` would train the
model to invent precise numbers it wasn't given — exactly the hallucination
failure mode your plan's point 9 warns about. Reclassified as
`NEEDS_CLARIFICATION` with a question asking for the missing per-segment
targets; the original ladder distances/structure/order are preserved in the
question's context (still useful signal), just not asserted as a `VALID`
canonical output.

## The reported `back_to_offset` bug — re-verified against current code, not reproduced

The chat's audit (and the zip's own `00_README.md`) reports that
`back_to_offset` translation depended on the *type* of the preceding step:

| Active step | Recovery step | `back_to_offset` | Reported status |
|---|---|---|---|
| `time_hr` | `time_step` | 2 | working |
| `dist_hr` | `time_step` | 2 | **broken** |
| `dist_hr` | `time_step` | 1 | working |
| `dist_hr` | `dist_hr` | 1 | working |

I re-read the current implementation of both build paths against this table:

- `workout_utils.build_yaml_to_fit_index()` (direct path, default) builds
  `{yaml_idx: fit_idx}` purely by position, advancing `fit_idx` by 1 per step
  except `sbu_block` (which expands). It never inspects the *type* of any
  step, active or otherwise.
- `build_from_plan.build_workout_steps()` calls
  `yaml_to_fit.get(step.back_to_offset, step.back_to_offset)` — same
  position-only mapping, used uniformly regardless of what step type sits at
  that offset.
- `generate_from_yaml._build_yaml_to_fit_index()` (legacy path) is the same
  logic restated for raw dicts, with the same "keep in sync" comment; it
  also only special-cases `sbu_block`.

None of the three currently contain a branch on step type for `repeat`
translation — so the specific step-type-dependent failure mode as described
is **not reproducible in the code as it stands today**. Two explanations fit
the evidence:
1. The reported failures happened against an earlier version, and commit
   `258c4c4` ("feat: allow nested repeats so sets of intervals can be
   expressed") — the most recent repeat-related change in this repo's
   history — already changed this code path and incidentally fixed it.
2. The failure was on the Garmin Connect / watch app side (how it *renders*
   or *schedules* an already-correct FIT file), not in FIT byte generation —
   which `build_yaml_to_fit_index()` cannot detect or reproduce from Python
   alone.

**Recommendation:** before trusting this as a live bug, re-run the specific
failing case (`dist_hr` active + `time_step` recovery + `back_to_offset: 2`,
e.g. group `real_aerobic_sbu_accel_9km`'s shape but with `dist_hr` instead of
`time_hr` as the active step) through the current direct build path and load
it on a watch. If it now works, this was already fixed and the table above
is historical. If it still fails, it's a live bug in the FIT-index mapping
or in Garmin's own rendering — worth a dedicated investigation in
`src/garmin_fit/`, separate from this dataset work (it's a build-time
correctness issue, not something the LLM's YAML output is responsible for:
the schema-level rule stays "`back_to_offset` = index of the first step of
the repeating group", regardless of how the FIT builder translates it).

The chat's own suggestion — replacing `back_to_offset` with a nested `repeat`
that holds its own step list — is a bigger schema change than Schema v1
should take on speculatively. If re-verification confirms a live bug, fix it
in `build_yaml_to_fit_index()`/`build_workout_steps()` first (it would be a
narrower, lower-risk fix); only revisit the schema shape if a
position-based mapping turns out to be unfixable in principle, which
nothing found here suggests.
