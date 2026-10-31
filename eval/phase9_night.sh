#!/usr/bin/env bash
# Phase 9 overnight run: local models (Ollama, GPU) vs deepseek-flash (API, results from Phases 4-7).
# Sequential (one model fits the 4 GB GPU at a time); every LLM call is cached, so re-running this
# script resumes where it stopped. Retrieval embeddings run on the CPU so the GPU stays with Ollama.
# Log: results/phase9/night.log
set -uo pipefail
cd "$(dirname "$0")/.."
export CUDA_VISIBLE_DEVICES=
mkdir -p results/phase9
LOG=results/phase9/night.log
step() { echo "=== $(date '+%H:%M:%S') $*" | tee -a "$LOG"; "$@" >>"$LOG" 2>&1 || echo "!!! failed: $*" | tee -a "$LOG"; }
PY="uv run python -m"

# API judge for the DeepSeek k=5 reference runs in parallel (no GPU needed)
( $PY eval.run_judge rag_best_k5 --max-cost 0.8 >> results/phase9/judge_deepseek.log 2>&1 ) &

# 1. Qwen3-4B 4-bit: fully on the GPU -> full suites
M=local_qwen4b_q4
step $PY eval.run_rag configs/rag/rag_local_qwen4b_q4_k5.yaml --max-cost 0.01  # local calls cost 0; a 0 cap counts as reached
step $PY eval.run_agent_eval --model $M --modes routed single --tag $M --max-cost 0.05
step $PY eval.run_security --model $M --suite attack --modes single routed --defences none policy \
     --tag $M --out-dir results/phase9 --max-cost 0.05
step $PY eval.run_judge rag_local_qwen4b_q4_k5 --max-cost 0.8

# 2./3. Qwen3-4B 8-bit and Qwen3-8B 4-bit: partly on the CPU -> half-size subsets
for M in local_qwen4b_q8 local_qwen8b_q4; do
  step $PY eval.run_rag configs/rag/rag_${M}_k5.yaml --dataset eval/datasets/qa_dev_half.jsonl --max-cost 0.01  # local calls cost 0; a 0 cap counts as reached
  step $PY eval.run_agent_eval --model $M --modes routed --every 2 --tag $M --max-cost 0.05
  step $PY eval.run_security --model $M --suite attack --modes single --defences none \
       --tag $M --out-dir results/phase9 --max-cost 0.05
done
wait
echo "=== $(date '+%H:%M:%S') done" | tee -a "$LOG"
