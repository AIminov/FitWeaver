# LLM evaluation harness

Harness evaluates saved model replies offline or runs a suite against a live
Ollama/OpenAI-compatible endpoint. It writes each run under
`Build_artifacts/llm_eval/<run-id>/`:

- `manifest.json` — configuration and run identity;
- `results.json` — per-case raw-output checks, production-pipeline result,
  expectation checks, source hash, and runtime metrics;
- `summary.md` — readable scorecard;
- `trace.jsonl` — append-only requests/responses and stage events, so an
  interrupted live run still leaves a trace.

Raw and post-pipeline scores are kept separate. Raw checks measure whether the
model itself returned parseable, schema-valid, structurally faithful YAML and
whether deterministic target repairs were needed. Pipeline checks run the
same candidate preparation and source-fact checks used by FitWeaver, then
parse and validate the serialized YAML again. Strict pass also requires no
source-format errors, no workout step without a distance or duration, and no
failed hard expectations from the suite.

## Suite format

Paths are resolved relative to the suite file first, then the repository root.
Offline cases point to the original model response as plain text or JSON from
Ollama/OpenAI-compatible APIs. Keep source/YAML datasets and response payloads
outside Git when they contain personal training data.

```yaml
suite: golden-plans-v1
cases:
  - id: intervals-01
    input_path: inputs/intervals-01.txt
    raw_response_path: responses/qwen3-intervals-01.json
    expected_workout_count: 1
    tags: [intervals, repeat]
    checks:
      # Optional checks supported by llm.benchmark.evaluate_case_expectations.
      - kind: step_field
        workout: N01_Intervals
        step_index: 1
        field: type
        equals: dist_repeat
```

## Golden suite

Build a suite from the golden dataset (`docs/golden_dataset/golden_examples_v1.yaml`): one input
per valid single-workout text variant, each with `expected_steps` from the reference YAML.

```powershell
garmin-fit-llm-eval --suite-from-golden            # -> Build_artifacts/llm_eval/golden_suite/suite.yaml
garmin-fit-llm-eval --suite Build_artifacts\llm_eval\golden_suite\suite.yaml --mode live `
  --api ollama --url http://localhost:11434 --model "qwen3:8b"
```

Для парного сравнения короткого ответа используйте тот же suite, модель и параметры,
но добавьте `--output-format compact`. Этот ответ разбирает
[`compact_plan.py`](../src/garmin_fit/llm/compact_plan.py), затем обычный marked-парсер;
`strict_pass` считается по итоговому Garmin YAML. В `raw_candidate` записан формат и
результат проверки синтаксиса. Чтобы сравнить число потоков CPU, можно задать
`--num-thread 8`; это поддерживаемый параметр `options.num_thread` в
[Ollama API](https://github.com/ollama/ollama/blob/main/docs/api.md). Меняйте один
параметр за прогон и сопоставляйте одинаковые case/trial.

Живые результаты сохраняют `prompt_eval_cached_count` и отдельную медиану задержки
для запросов с попаданием и без попадания в KV-кэш. Время включает генерацию и
обработку подсказки; без разделения cache hit/miss сравнение может вводить в заблуждение.
`distance_diagnostic` разворачивает вложенные повторы и показывает сумму только явно
заданных дистанций шагов. Это информационная метрика: дистанция временных шагов не
угадывается, общий итог тренировки не становится дополнительным строгим условием.

`expected_steps` is checked fact by fact (`llm/golden.py`): measures, repeat structure and
targets must match, and differing explicit step intensities fail. A reference target may be
omitted only when the source states fewer occurrences of that target than the reference uses;
an explicitly stated target must appear in the generated steps. The `hr_low: 60` encoding of
an upper-only HR cap may differ from an older reference's lower bound only when the source
actually says `до N` / `не выше N`. An explicit HR range is compared exactly. The harness
also checks which step owns each explicit target when the conservative free-text parser can
parse the source. It does not use that parser to produce model output, so scores still
measure the model.

## Commands

Score saved responses without calling a model:

```powershell
garmin-fit-llm-eval --suite path\to\suite.yaml --mode offline --model "qwen3:8b"
```

Run the same suite live against Ollama; use at least two trials for unstable
models and compare models against the exact same suite and trial count:

```powershell
garmin-fit-llm-eval --suite path\to\suite.yaml --mode live --api ollama `
  --url http://localhost:11434 --model "qwen3:8b" --trials 2
```

Compare two generated `results.json` files. The command refuses to compare
different case/trial sets or different source hashes:

```powershell
garmin-fit-llm-eval --compare path\to\run-a\results.json path\to\run-b\results.json
```

The comparison writes JSON and Markdown artifacts with pass counts, per-pair
wins/ties, and median latency. It is descriptive rather than a significance
test; small suites should be treated as directional evidence only.

## Trace and privacy

Trace files contain raw model responses and may contain workout details. They
are local build artifacts, not intended for source control or automatic upload.
Requests are represented with hashes and metadata; prompt/source text is not
copied into the trace. Model replies are stored to make failures inspectable.

## Current limits

- The strict pass is a deterministic acceptance signal, not a full measure of
  coaching quality.
- Add suite checks for semantic facts that matter in a dataset, especially
  repeat body/count/order and target-to-step alignment when the same target
  appears on several reference steps.
- Live runs currently identify the model by the configured name. Record the
  Ollama model digest/size alongside each run when `/api/tags` is available.
- Comparison reports require the same paired cases/trials and source text;
  they do not yet estimate confidence intervals.
