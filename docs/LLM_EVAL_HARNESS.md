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
  repeat body/count/order, target preservation, and expected step types.
- Live runs currently identify the model by the configured name. Record the
  Ollama model digest/size alongside each run when `/api/tags` is available.
- Comparison reports require the same paired cases/trials and source text;
  they do not yet estimate confidence intervals.
