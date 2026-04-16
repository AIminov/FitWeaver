# Garmin Connect Calendar — Setup & Usage

Upload FitWeaver workouts directly to **Garmin Connect Calendar** — no USB
cable or manual file transfer required.  After upload the workouts appear on
your watch automatically on the next Garmin Connect sync.

---

## How it works

1. FitWeaver converts your YAML plan to Garmin workout-service API payloads.
2. Each workout is uploaded to your Garmin Connect account via the REST API.
3. If calendar scheduling is enabled, the workout is also pinned to its date
   (extracted automatically from the filename pattern `W{week}_{MM-DD}_…`).
4. Your watch picks up the scheduled workouts on the next WiFi / BT sync.

---

## Requirements

Install the optional dependency group:

```bash
pip install "garmin-fit-generator[garmin-calendar]"
```

Or individually:

```bash
pip install garminconnect garmin-auth
```

---

## Credentials

Provide your Garmin Connect email and password in one of three ways:

### Option 1 — Environment variables (recommended)

```bash
# Windows PowerShell
$env:GARMIN_EMAIL    = "your@email.com"
$env:GARMIN_PASSWORD = "yourpassword"

# Linux / macOS
export GARMIN_EMAIL="your@email.com"
export GARMIN_PASSWORD="yourpassword"
```

### Option 2 — CLI flags

```bash
python -m garmin_fit.cli garmin-calendar \
  --email your@email.com \
  --password yourpassword
```

### Option 3 — `.env` file (not loaded automatically — set env manually)

---

## First-time authentication (MFA)

If your account uses two-factor authentication, the CLI will prompt:

```
Garmin MFA code: ______
```

Enter the code from your authenticator app.  Tokens are saved to
`~/.garminconnect/` (or the path you supply with `--token-dir`), so you
won't need to log in again until the tokens expire.

---

## Usage

### Interactive menu (recommended)

```bash
python -m garmin_fit.runner
```

Select **G** to upload with scheduling, or **D** for a dry-run preview.

---

### CLI — full upload

```bash
python -m garmin_fit.cli garmin-calendar --plan Plan/my_plan.yaml
```

### CLI — dry run (no API calls, just shows what would happen)

```bash
python -m garmin_fit.cli garmin-calendar --plan Plan/my_plan.yaml --dry-run
```

### CLI — upload without calendar scheduling

```bash
python -m garmin_fit.cli garmin-calendar --plan Plan/my_plan.yaml --no-schedule
```

### CLI — override year for date extraction

```bash
python -m garmin_fit.cli garmin-calendar --plan Plan/my_plan.yaml --year 2026
```

### CLI — custom token storage directory

```bash
python -m garmin_fit.cli garmin-calendar --token-dir /path/to/tokens
```

### CLI - upload only a date range

```bash
python -m garmin_fit.cli garmin-calendar \
  --plan Plan/my_plan.yaml \
  --year 2026 \
  --from-date 2026-05-01 \
  --to-date 2026-05-17
```

Use `--dry-run` with the same filters first to verify which workouts will be
uploaded.

---

## All flags

| Flag | Default | Description |
|------|---------|-------------|
| `--plan YAML_PATH` | auto-detect | Path to YAML plan |
| `--email EMAIL` | `$GARMIN_EMAIL` | Garmin account email |
| `--password PASSWORD` | `$GARMIN_PASSWORD` | Garmin account password |
| `--token-dir DIR` | `~/.garminconnect` | Token storage directory |
| `--year YEAR` | auto (current/next) | Override year for date extraction |
| `--no-schedule` | off | Upload without calendar scheduling |
| `--dry-run` | off | Preview only — no API calls |

---

## Filename → calendar date mapping

Additional upload filters: `--week-pause SECS`, `--skip-past`,
`--from-date YYYY-MM-DD`, and `--to-date YYYY-MM-DD`.

---

## SBU / Drill Step Notes

Garmin Calendar upload stores the Garmin Connect "workout step note" as
`ExecutableStepDTO.description`.

For `sbu_block`, FitWeaver creates one repeat group per drill:

```text
Bounds 2x [active step note "Bounds" + Recovery]
Ankling 1x [active step note "Ankling" + Recovery]
```

The active drill step preserves the YAML drill `name`, `seconds`, and `reps`.
Garmin Connect mobile shows these notes after direct Calendar upload.

---

FitWeaver extracts the workout date from the filename pattern:

```
W11_03-14_Sat_Long_14km  →  YYYY-03-14
```

Year selection:
- If the date hasn't passed yet → current year.
- If the date has already passed → next year.
- Use `--year YEAR` to override.

If the date cannot be extracted from a filename, that workout is uploaded
without scheduling (a warning is logged).

---

## Rate limiting

A 1.2-second delay is inserted between uploads to respect Garmin Connect
rate limits.  For a typical 6-day plan this adds ~7 seconds total.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `garmin-auth is not installed` | `pip install garmin-auth` |
| `Authentication failed` | Check email/password; try `--dry-run` first |
| MFA prompt appears every time | Delete `~/.garminconnect/` tokens and re-auth |
| Workouts upload but don't appear on watch | Force a Garmin Connect sync |
| Date extracted as wrong year | Use `--year 2026` |
