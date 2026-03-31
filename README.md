# Garmin FIT Workout Generator

Р“РµРЅРµСЂР°С†РёСЏ С‚СЂРµРЅРёСЂРѕРІРѕС‡РЅС‹С… `.fit`-С„Р°Р№Р»РѕРІ РґР»СЏ С‡Р°СЃРѕРІ Garmin РёР· С‚РµРєСЃС‚РѕРІС‹С… РїР»Р°РЅРѕРІ СЃ РїРѕРјРѕС‰СЊСЋ Р»РѕРєР°Р»СЊРЅРѕР№ LLM.

## Pipeline

```text
РўРµРєСЃС‚ РїР»Р°РЅР° -> LLM -> YAML -> direct build -> .fit -> Garmin
```

РџРѕР»РЅС‹Р№ workflow Р±РѕР»СЊС€Рµ РЅРµ С‚СЂРµР±СѓРµС‚ РїСЂРѕРјРµР¶СѓС‚РѕС‡РЅС‹С… Python-С€Р°Р±Р»РѕРЅРѕРІ. Р РµР¶РёРјС‹ `--templates-only` Рё `--build-only` СЃРѕС…СЂР°РЅРµРЅС‹ РєР°Рє legacy/debug РёРЅСЃС‚СЂСѓРјРµРЅС‚С‹.

## Р‘С‹СЃС‚СЂС‹Р№ СЃС‚Р°СЂС‚

1. РџРѕР»РѕР¶РёС‚Рµ РїР»Р°РЅ С‚СЂРµРЅРёСЂРѕРІРѕРє РІ `Plan/plan.txt` РёР»Рё `Plan/plan.md`.
2. РЎРіРµРЅРµСЂРёСЂСѓР№С‚Рµ YAML (С‚РµРєСѓС‰РёР№ СЂР°Р±РѕС‡РёР№ РїСЂРѕС„РёР»СЊ LM Studio):
   `python -m garmin_fit.llm.request_cli --api openai --url http://127.0.0.1:1234/v1 --model qwen/qwen3.5-9b --openai-mode completions --timeout-sec 1800`
3. РЎРѕР±РµСЂРёС‚Рµ FIT: `python -m garmin_fit.cli run`
4. РЎРєРѕРїРёСЂСѓР№С‚Рµ С„Р°Р№Р»С‹ РёР· `Output_fit/` РЅР° С‡Р°СЃС‹ Garmin.

РўР°РєР¶Рµ РјРѕР¶РЅРѕ Р·Р°РїСѓСЃС‚РёС‚СЊ РІРµСЃСЊ workflow С‡РµСЂРµР· `run_pipeline.bat` РёР»Рё `run_pipeline.sh`.

## РљРѕРјР°РЅРґС‹

```bash
python -m garmin_fit.llm.request_cli --api openai --url http://127.0.0.1:1234/v1 --model qwen/qwen3.5-9b --openai-mode completions --timeout-sec 1800
python -m garmin_fit.cli run               # РџРѕР»РЅС‹Р№ С†РёРєР»: YAML -> FIT -> validation -> archive
python -m garmin_fit.legacy_cli compare --plan Plan/plan.yaml
python -m garmin_fit.cli doctor
python -m garmin_fit.cli doctor --llm --api openai --url http://127.0.0.1:1234/v1 --model qwen/qwen3.5-9b --openai-mode completions --timeout-sec 120
python -m garmin_fit.legacy_cli templates --plan Plan/plan.yaml
python -m garmin_fit.legacy_cli build
python -m garmin_fit.validate_cli --plan Plan/plan.yaml
python -m garmin_fit.check_fit --strict Output_fit
python -m garmin_fit.check_fit --strict --no-sdk-python-check Output_fit
python get_fit.py --archive                # Legacy compatibility entry point
python get_fit.py --list-archives          # Legacy compatibility entry point
python get_fit.py --restore <name>         # Legacy compatibility entry point
python -m garmin_fit.llm.benchmark --suite tests/fixtures/llm_benchmark/plan_week_2026_03_02.yaml --mode generate --api openai --url http://127.0.0.1:1234/v1 --model qwen/qwen3.5-9b --openai-mode completions --timeout-sec 1800
python run.py                              # РРЅС‚РµСЂР°РєС‚РёРІРЅРѕРµ РјРµРЅСЋ
python -m garmin_fit.bot                   # Telegram-Р±РѕС‚
```

## Build Artifacts

- `Build_artifacts/` С…СЂР°РЅРёС‚ `*.repaired.yaml`, `*.build_report.json` Рё `*.build_mode_compare.json`.
- `repaired.yaml` РїРѕРєР°Р·С‹РІР°РµС‚, РєР°Рє pipeline РЅРѕСЂРјР°Р»РёР·РѕРІР°Р» Рё РїРѕС‡РёРЅРёР» РёСЃС…РѕРґРЅС‹Р№ YAML РїРµСЂРµРґ СЃР±РѕСЂРєРѕР№.
- `build_report.json` СЃРѕРґРµСЂР¶РёС‚ machine-readable СЃРІРѕРґРєСѓ: mode, repairs, warnings, counts, validation Рё errors.
- `build_mode_compare.json` СЃРІРѕРґРёС‚ result direct builder Рё legacy templates builder РґР»СЏ РѕРґРЅРѕРіРѕ YAML.
- РђСЂС…РёРІС‹ Рё Telegram ZIP РІРєР»СЋС‡Р°СЋС‚ СЌС‚Рё Р°СЂС‚РµС„Р°РєС‚С‹ РІРјРµСЃС‚Рµ СЃ РїР»Р°РЅРѕРј Рё FIT-С„Р°Р№Р»Р°РјРё.

## РђСЂС…РёРІС‹ Рё debug export

- РђСЂС…РёРІ Рё Telegram ZIP Р±РѕР»СЊС€Рµ РЅРµ С‚СЂРµР±СѓСЋС‚ Р·Р°СЂР°РЅРµРµ СЃРѕР·РґР°РЅРЅРѕР№ РїР°РїРєРё `Workout_templates/`.
- Р•СЃР»Рё С€Р°Р±Р»РѕРЅРѕРІ РІ workspace РЅРµС‚, РЅРѕ РµСЃС‚СЊ YAML-РїР»Р°РЅ, СЃРёСЃС‚РµРјР° СЌРєСЃРїРѕСЂС‚РёСЂСѓРµС‚ debug templates РїСЂСЏРјРѕ РІ Р°СЂС…РёРІ РёР»Рё ZIP.
- Р­С‚Рё С€Р°Р±Р»РѕРЅС‹ РѕСЃС‚Р°СЋС‚СЃСЏ РѕРїС†РёРѕРЅР°Р»СЊРЅС‹РјРё Р°СЂС‚РµС„Р°РєС‚Р°РјРё РґР»СЏ РѕС‚Р»Р°РґРєРё Рё СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё, Р° РЅРµ РѕР±СЏР·Р°С‚РµР»СЊРЅРѕР№ СЃС‚Р°РґРёРµР№ pipeline.

## РЎС‚СЂСѓРєС‚СѓСЂР°

```text
get_fit.py
Scripts/
Plan/
Output_fit/
Workout_templates/   # optional debug/legacy templates
Build_artifacts/     # repaired YAML + machine-readable build reports
Archive/
docs/
tests/
```

## Р”РѕРєСѓРјРµРЅС‚Р°С†РёСЏ

- [РџРѕР»РЅР°СЏ РґРѕРєСѓРјРµРЅС‚Р°С†РёСЏ](docs/README.md)
- [Р“Р°Р№Рґ РїРѕ YAML](docs/YAML_GUIDE.md)
- [Project Flow](docs/PROJECT_FLOW.md)
- [LLM Connection Profile](docs/LLM_CONNECTION_PROFILE.md)
- [Telegram Setup](docs/TELEGRAM_SETUP.md)

## CLI Update

Primary supported CLI:

```bash
python -m garmin_fit.cli --help
python -m garmin_fit.cli run
python -m garmin_fit.cli validate-yaml --plan Plan/plan.yaml
python -m garmin_fit.cli validate-fit
python -m garmin_fit.cli doctor --llm
```

Legacy/debug CLI:

```bash
python -m garmin_fit.legacy_cli --help
python -m garmin_fit.legacy_cli templates --plan Plan/plan.yaml
python -m garmin_fit.legacy_cli build
python -m garmin_fit.legacy_cli compare --plan Plan/plan.yaml
```

Runtime bootstrap:

```bash
python -m garmin_fit.runtime_cli --runtime-root runtime --copy-existing
```


## Compatibility Status

- src/garmin_fit/ is the primary source tree.
- Scripts/ is retained as a legacy compatibility layer for older entry points and tests.
- For new automation and new code, prefer python -m garmin_fit.cli, python -m garmin_fit.llm.request_cli, and python -m garmin_fit.bot.
- See docs/LEGACY_COMPAT.md for the current compatibility contract.

