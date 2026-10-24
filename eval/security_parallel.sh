#!/usr/bin/env bash
# Phase 7 security grid in parallel (make security). Four processes, one MCP server each:
# the two prompt-only configurations (all fresh API calls) on the GPU, the none+policy pairs on
# the CPU (policy reuses the none run's LLM cache until a call is denied). Attacks are planted
# once for all processes and always removed at the end, also on failure.
set -euo pipefail
RUN="uv run python -m eval.run_security"
rm -rf results/security_parts

run_group() {  # $1 suite, extra args...
  local suite=$1; shift
  local plant=()
  [[ $suite == attack ]] && plant=(--no-plant)
  $RUN --suite "$suite" "${plant[@]}" --modes single --defences prompt --tag "${suite}_A" --max-cost 0.8 &
  $RUN --suite "$suite" "${plant[@]}" --modes routed --defences prompt --tag "${suite}_B" --max-cost 0.8 &
  CUDA_VISIBLE_DEVICES= $RUN --suite "$suite" "${plant[@]}" --modes single --defences none policy --tag "${suite}_C" --max-cost 0.8 &
  CUDA_VISIBLE_DEVICES= $RUN --suite "$suite" "${plant[@]}" --modes routed --defences none policy --tag "${suite}_D" --max-cost 0.8 &
  local fail=0
  for job in $(jobs -p); do wait "$job" || fail=1; done
  return $fail
}

run_group benign                      # clean corpus
$RUN --plant
trap '$RUN --cleanup' EXIT            # always remove the planted attacks
run_group attack
$RUN --merge
