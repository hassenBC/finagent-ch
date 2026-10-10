# finagent-ch

[![ci](https://github.com/hassenBC/finagent-ch/actions/workflows/ci.yml/badge.svg)](https://github.com/hassenBC/finagent-ch/actions/workflows/ci.yml)

A measured, permission-aware LLM agent over Swiss financial documents.

## Quick start

```bash
cp .env.example .env   # add DEEPSEEK_API_KEY
make setup             # uv sync, Postgres+pgvector in Docker, migrations
make test
make llm-smoke         # run twice: second call is cached and free
```

Embeddings, reranking and parsing run on a local CUDA GPU (`uv sync --extra gpu`, check with `make gpu-smoke`);
without one, use `uv sync --extra cpu`.

## Evaluation dataset

`eval/datasets/qa_dev.jsonl` (100 questions, tuned on) and `qa_test.jsonl` (50 questions, run once per final
configuration). `sha256(qa_test.jsonl) = 7ee5209fcd11fa9846fd0c761766f1db040d24db8b79f474ad9c45dc195bc339`.

**How the dataset was built.** Pages were sampled with a fixed seed, round-robin over the 12 reports (6 banks x
FY2024/FY2025) so every document contributes. An LLM (`deepseek-flash`) proposed one question per page for a requested
type and wording style (literal or paraphrased); `eval/build_candidates.py` then machine-checks each proposal: the evidence
words and numbers must occur on the gold page, and numeric answers and calculations must be consistent with the page.
`eval/assemble.py` filters ambiguous items (questions that name only a different fiscal year than the gold document,
that leak the numbers they ask for, or comparisons with a "no difference" answer), balances banks and years, uses each gold
page at most once, and splits stratified by type and language. Gold labels are **pages**, not chunks, so the dataset is
independent of the chunker. About 58 % of items are paraphrased (question/evidence word overlap below 0.2).

**Changes after the split (before any test-set run).** Numeric tolerances are now half a unit of the answer's last digit
with a 0.1 % relative floor (they were derived from unit-converted calculations and were far too tight). One dev item
(q128) was corrected during the retrieval error analysis: its gold used Swissquote's standalone holding-company balance
sheet instead of the consolidated one.

**Limits you should know about.**

- The questions are model-proposed and machine-checked, not written by hand. The machine check is that the evidence and
  the numbers occur on the gold page. An AI-assisted blind spot check of 20 items re-derived all 20 answers from the PDFs
  and agreed with the dataset (details and caveats in `eval/SPOTCHECK.md`); it is a sample, not a human audit.
- Facts repeated on several pages are listed in `alt_pages`; a retrieved page counts as relevant if it is a gold or an
  alternate page.
- "Unanswerable" items were screened by looking at the nearest passages in the same bank's reports, not by an exhaustive search,
  and most ask about 2026 forecasts.
- Random page sampling yields many detail questions (governance, notes) and few headline KPIs.
