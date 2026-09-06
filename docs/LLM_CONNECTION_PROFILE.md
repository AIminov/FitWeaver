# LLM connection and generation

Updated: 2026-09-06.

The source plan is arbitrary human text: paragraphs, lists, tables, abbreviations,
undated sessions and references to other days are supported inputs. No input
schema is required. The complete original text is sent to the model together.
Date/header detection supplies non-binding hints; it does not split the request
or impose a workout count. Only an explicitly supplied `workouts_hint` is binding.

Output YAML is validated against the workout schema and repeat index rules.
Invalid output gets one correction attempt by default, including the previous
answer and validation errors. Missing repeats and invalid repeat anchors are not
invented or guessed. Regex comparisons with source facts are diagnostic warnings,
not proof of semantic equivalence or grounds to reject arbitrary prose.

## Current defaults

- OpenAI-compatible URL: `http://127.0.0.1:1234/v1` (machine-specific example).
- Model: `qwen3.8-27b@iq3_xxs`.
- GUI, doctor, benchmark and client use `auto`: detected LM Studio uses
  `/api/v1/chat` with `reasoning: off` and `store: false`. Generic servers use
  OpenAI-compatible chat, then completions when chat is unusable. Older LM Studio
  without the native endpoint falls back to the compatibility API.
- Loopback SDK connections bypass Windows proxy settings; remote endpoints keep
  their configured proxies.
- `openai` is a declared dependency. SDK retries are disabled; the generation
  loop controls attempts. Two attempts per plan by default; `--retries 1`
  explicitly selects a one-shot run.
- Client output ceiling: 16384 tokens (configurable with `max_output_tokens`).
  Native LM Studio caps this to half the loaded context (4096 for context 8192).
  `finish_reason=length` rejects a truncated answer even if its prefix parses.
- CLI request tool still defaults to `--api ollama`; specify `--api openai`
  for LM Studio. CLI/benchmark timeout is 1800 seconds, API 900 seconds,
  standalone client 300 seconds; GUI passes its timeout setting.
- Telegram bot uses its `bot_config.yaml` Ollama configuration.

On 2026-09-06 the user selected `http://127.0.0.1:1234`. The loaded model is
`qwen3.8-27b@iq3_xxs`, context 8192; `qwen3.8-27b@q4_k_xl` is available but unloaded.
A free-form three-run plan passed live generation on the first attempt with zero
reasoning tokens, preserving a cross-day reference and 6 x 800 m intervals.
All-distance workout summaries are recomputed from validated steps and repeats.
Input prose is not constrained by regex counts, including in the CLI.

Native API reference: https://lmstudio.ai/docs/developer/rest/chat

## Generate and diagnose

Replace the URL/model ID with your server values (`/v1/models` lists IDs):

```powershell
.\.venv\Scripts\python.exe -m garmin_fit.llm.request_cli --api openai --url http://127.0.0.1:1234/v1 --model YOUR_MODEL_ID --openai-mode auto --plan Plan/plan.txt --retries 2
.\.venv\Scripts\python.exe -m garmin_fit.cli doctor --llm --api openai --url http://127.0.0.1:1234/v1 --model YOUR_MODEL_ID --openai-mode auto --timeout-sec 120
```

## Windows Python and tests

If `python` opens the Store, it is the App Installer alias, not an interpreter.
Install Python, then disable the App Installer `python.exe`/`python3.exe` entries
in **Manage app execution aliases** if they still intercept the command. Open a
new terminal. Do not disable aliases belonging to an installed Python manager.

This checkout has a Python 3.12 environment. Activation is optional:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m ruff check src fitweaver_gui.py tests
```

On a new checkout, create `.venv` with an installed interpreter and run
`.\.venv\Scripts\python.exe -m pip install -e ".[dev,api]"`.
