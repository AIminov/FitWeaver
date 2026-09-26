# Examples

## Marked plan text (recommended)

`marked_plan_example.txt` — a training plan in the marked format. It compiles to YAML without an
LLM, instantly:

```bash
python -m garmin_fit.cli parse-marked examples/marked_plan_example.txt --output Plan/plan.yaml
python -m garmin_fit.cli run --plan Plan/plan.yaml
```

The format is described in [docs/MARKED_PLAN_FORMAT.md](../docs/MARKED_PLAN_FORMAT.md). In the
desktop GUI, paste the text into the LLM tab and press "Генерировать YAML".

## Python API examples

`example_*.py` show the low-level FIT step builders in `garmin_fit.workout_utils`
(`dist_hr`, `time_step`, `repeat_step`, `sbu_block`, …). Each file builds one workout and can be
run on its own:

```bash
python examples/example_intervals.py   # writes Output_fit/test_intervals.fit
```

They are reference material for the step helpers. Normal plans go through YAML (see
[docs/YAML_GUIDE.md](../docs/YAML_GUIDE.md)); the old pipeline that generated and executed such
Python templates from YAML was removed on 2026-09-26.
