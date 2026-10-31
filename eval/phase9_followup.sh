#!/usr/bin/env bash
# Runs after phase9_night.sh: the 4B q4 attack suite (its first attempt failed on a missing --model flag).
set -uo pipefail
cd "$(dirname "$0")/.."
export CUDA_VISIBLE_DEVICES=
while pgrep -f "bash eval/phase9_night.sh" >/dev/null; do sleep 60; done
LOG=results/phase9/night.log
echo "=== $(date '+%H:%M:%S') followup: 4B q4 attacks" >> "$LOG"
uv run python -m eval.run_security --model local_qwen4b_q4 --suite attack --modes single routed \
  --defences none policy --tag local_qwen4b_q4 --out-dir results/phase9 --max-cost 0.05 >> "$LOG" 2>&1 \
  || echo "!!! failed: followup security" >> "$LOG"
echo "=== $(date '+%H:%M:%S') followup done" >> "$LOG"
