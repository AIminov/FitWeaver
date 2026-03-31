#!/bin/bash
# Full pipeline for FIT generation from a YAML plan
# Usage: ./run_pipeline.sh [path/to/plan.yaml]

set -e

echo "====================================="
echo " GARMIN FIT GENERATION PIPELINE"
echo "====================================="

# Use argument or auto-detect latest YAML in Plan/
if [ -n "$1" ]; then
  YAML_SOURCE="$1"
else
  YAML_SOURCE=$(ls -t Plan/*.yaml Plan/*.yml 2>/dev/null | head -1)
fi

if [ -z "$YAML_SOURCE" ] || [ ! -f "$YAML_SOURCE" ]; then
  echo "[ERROR] No YAML plan found. Place a .yaml file in Plan/ or pass path as argument."
  echo "Usage: ./run_pipeline.sh [path/to/plan.yaml]"
  exit 1
fi

echo "Using plan: $YAML_SOURCE"
echo ""

echo "[1/2] Generating workout templates..."
python get_fit.py --templates-only --plan "$YAML_SOURCE"

echo "[2/2] Building and validating FIT files..."
python get_fit.py --build-only

echo "====================================="
echo " DONE"
echo "====================================="
echo "FIT files are in: Output_fit/"
