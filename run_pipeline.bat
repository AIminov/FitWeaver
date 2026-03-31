@echo off
REM Full pipeline for FIT generation from a YAML plan
REM Usage: run_pipeline.bat [path\to\plan.yaml]

setlocal enabledelayedexpansion

echo.
echo =====================================
echo  GARMIN FIT GENERATION PIPELINE
echo =====================================
echo.

REM Use argument or auto-detect latest YAML in Plan\
set YAML_SOURCE=%~1

if "%YAML_SOURCE%"=="" (
  set YAML_SOURCE=
  for /f "delims=" %%F in ('dir /b /o-d Plan\*.yaml Plan\*.yml 2^>nul') do (
    if not defined YAML_SOURCE set "YAML_SOURCE=Plan\%%F"
  )
)

if "%YAML_SOURCE%"=="" (
  echo [ERROR] No YAML plan found. Place a .yaml file in Plan\ or pass path as argument.
  echo Usage: run_pipeline.bat [path\to\plan.yaml]
  exit /b 1
)

if not exist "%YAML_SOURCE%" (
  echo [ERROR] YAML source not found: %YAML_SOURCE%
  exit /b 1
)

echo Using plan: %YAML_SOURCE%
echo.

echo [1/2] Generating workout templates...
python get_fit.py --templates-only --plan "%YAML_SOURCE%"
if errorlevel 1 (
  echo [ERROR] Template generation failed
  exit /b 1
)

echo.
echo [2/2] Building and validating FIT files...
python get_fit.py --build-only
if errorlevel 1 (
  echo [ERROR] FIT build/validation failed
  exit /b 1
)

echo.
echo =====================================
echo  DONE
echo =====================================
echo FIT files are in: Output_fit\
echo.

pause
