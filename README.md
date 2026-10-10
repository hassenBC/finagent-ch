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

## Retrieval results (Phase 3)

`qa_dev` holds 90 answerable questions and `qa_test` 45; unanswerable items are excluded from retrieval metrics. Relevance
is page-level (gold or alternate page). Intervals are 95 % bootstrap CIs; "A beats B" is claimed only when the paired
bootstrap CI of the per-question difference excludes 0. All runs: `results/retrieval*.csv`, chart `results/retrieval.png`.

**Held-out test set (run once):**

| Configuration | recall@5 [95 % CI] | MRR@10 | p50 latency |
|---|---|---|---|
| Naive baseline: fixed 512-token chunks, e5-small, vector | 0.44 [0.29, 0.58] | 0.27 | 14 ms |
| bge-m3 vector + bank/year filters | 0.80 [0.67, 0.91] | 0.71 | 25 ms |
| bge-m3 hybrid (vector + FTS, RRF) + filters + cross-lingual translation | 0.80 [0.67, 0.91] | 0.74 | 54 ms (p95 2.2 s) |

Both final configurations beat the baseline (recall@5 +0.36, CI [+0.18, +0.51]; MRR +0.44 to +0.47); they are not
distinguishable from each other on test (recall@5 +0.00 [-0.09, +0.09], MRR +0.03 [-0.06, +0.11]). On dev the hybrid
configuration scored 0.87 recall@5, so part of its dev advantage was selection on dev.

**Findings (dev unless stated):**

1. **The context header, not table isolation, drove the chunker result.** Table-aware chunking beat structure-based
   chunking by +0.18 recall@5, but removing its one-line `Bank | Year | Section` header erased the gain (table-aware without
   header vs structure: -0.01, n.s.), and adding the header to structure chunks gave the same score as table-aware (+0.01, n.s.).
2. **bge-m3 ranks better than the e5 models; size alone does not.** On table-aware chunks, bge-m3 improved MRR by +0.11
   [+0.03, +0.20] over e5-small; e5-large was no better than e5-small (+0.00).
3. **Metadata filters are the cheapest win; reranking and LLM expansion add latency, not accuracy.** Bank/year filters:
   +0.09 recall@5 [+0.03, +0.14] at no latency cost. A cross-encoder reranker (+1 s) and 3-query LLM expansion (+2.6 s) were
   not significant alone and added nothing on top of filters.
4. **Postgres full-text search needs `ts_rank` for OR queries.** With `ts_rank_cd` (cover density) the OR query ranked almost
   arbitrarily (recall@5 0.26); `ts_rank` with length normalisation reached 0.71, on par with dense retrieval, and made
   hybrid retrieval useful (e5-small hybrid vs vector: MRR +0.09 [+0.03, +0.16]). My first conclusion that "FTS is weak and
   hybrid does not help" was an artefact of that ranking choice.
5. **Cross-lingual questions were the top failure cause, and translation fixed most of them.** Of 15 misses of the best dev
   configuration, 5 were English questions about the French-language BCGE report; translating the question when its language
   differs from the named bank's report raised cross-lingual recall@5 from 0.50 to 0.80 (n = 10) and overall MRR by +0.03
   [+0.01, +0.06]. Other misses: 3 ambiguous or wrong items (one corrected), 2 gold labels too narrow, 1 lost table header,
   4 other (`results/error_analysis.csv`).

Caveats: 90 dev questions give wide intervals; many configurations were compared on the same dev set; approximate (HNSW)
search cost up to 0.04 recall@5 for unfiltered queries because one index serves five chunkers.
