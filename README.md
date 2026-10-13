# finagent-ch

[![ci](https://github.com/hassenBC/finagent-ch/actions/workflows/ci.yml/badge.svg)](https://github.com/hassenBC/finagent-ch/actions/workflows/ci.yml)

Retrieval-augmented question answering over 12 Swiss bank annual reports (6 banks, FY2024–FY2025, French and
English, table-heavy PDFs), **measured** on a 150-question page-level evaluation set built before any tuning. An MCP
agent with a deterministic tool-permission layer is in progress (see [Roadmap](#roadmap)).

**Headline results (held-out test set, run once):**

| | Naive baseline | Final system |
|---|---|---|
| Retrieval recall@5 (n = 45) | 0.44 | **0.80** |
| Answer numeric match (n = 50) | 0.25 | **0.78** |
| Citation precision / recall | 0.48 / 0.44 | **0.85 / 0.87** |
| Faithful answers among those answered (LLM judge; n = 17 / 41, CIs overlap) | 0.76 | **0.98** |
| Cost per question | $0.0013 | $0.0014 |

![Retrieval: recall@5 for each cumulative change, dev bars with 95 % CI and held-out test markers](results/retrieval_ladder.png)

The biggest single gain came from a one-line `Bank | Year | Section` header on each chunk, not from table isolation;
metadata filters were the cheapest win; a cross-encoder reranker and LLM query expansion added latency but no
measurable accuracy. Details and caveats below.

## How to reproduce

Needs Docker, [uv](https://docs.astral.sh/uv/), a DeepSeek API key in `.env`, and ideally a CUDA GPU (4 GB is enough).

```bash
make setup && make download ingest     # Postgres + pgvector, fetch the 12 PDFs, parse (docling), chunk, load
make embed-small && uv run python -m finagent.ingest.embed bge_m3   # embeddings (e5-small, bge-m3)
make eval-retrieval-grid report && make eval-rag report-rag         # all retrieval + RAG runs on dev (~$0.5)
```

LLM calls are cached in `.cache/llm/`, so re-runs are free; every LLM runner takes a `--max-cost` cap.
`make judge NAMES="rag_best_k10"` adds the faithfulness judge.

## Retrieval results (Phase 3)

`qa_dev` holds 90 answerable questions and `qa_test` 45; unanswerable items are excluded from retrieval metrics. Relevance
is page-level (gold or alternate page). Intervals are 95 % bootstrap CIs; "A beats B" is claimed only when the paired
bootstrap CI of the per-question difference excludes 0. All runs: `results/retrieval*.csv`, full chart of all
60 dev runs `results/retrieval.png`.

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

## RAG results (Phase 4)

Generator `deepseek-flash` (temperature 0, structured output with citations; it may abstain). Numeric match = some
number in the answer equals the gold value within its tolerance, after unit normalisation (numeric questions only);
citation precision/recall are page-level against gold pages; abstention metrics treat "unanswerable" as the positive
class, and false abstentions are refusals on answerable questions. Intervals are 95 % bootstrap CIs; "A beats B" needs
the paired bootstrap CI of the difference to exclude 0. Files: `results/rag_dev.csv`, `results/rag_test.csv`.

**Held-out test set (run once, n = 50):**

| Configuration | numeric match [95 % CI] | citation precision | citation recall | abstention F1 | false abstentions | faithful answers | p50 latency | cost / question |
|---|---|---|---|---|---|---|---|---|
| Naive baseline retrieval, k = 5 | 0.25 [0.13, 0.41] | 0.48 | 0.44 | 0.26 | 0.62 | 13/17 = 0.76 | 2.1 s | $0.0013 |
| Best retrieval (bge-m3 hybrid + filters + translation), k = 10 | 0.78 [0.63, 0.91] | 0.85 | 0.87 | 0.71 | 0.09 | 40/41 = 0.98 | 2.2 s | $0.0014 |

**Findings (dev unless stated):**

1. **Better retrieval carries through to answers.** At k = 5, the best retrieval configuration vs the baseline gives
   +0.34 numeric match [+0.24, +0.46] and +0.41 citation recall [+0.29, +0.52], for a +0.41 recall@5 gap in retrieval.
   The baseline mostly fails by refusing: 54 % false abstentions on dev, 62 % on test.
2. **More context helps up to k = 10.** Numeric match 0.62 → 0.69 → 0.75 and false abstentions 0.29 → 0.21 → 0.13 for
   k = 3 → 5 → 10 (each step significant); citation precision peaks at k = 5 (0.76 vs 0.71). Cost per question rises
   from $0.0006 to $0.0014.
3. **When the system answers, it rarely says more than its cited sources.** An LLM judge (`deepseek-v4-pro`) splits
   each non-abstained answer into atomic claims and checks them against the cited chunks only; an answer is faithful
   when every claim is supported. Test: best 0.98 [0.87, 1.00] (n = 41) vs baseline 0.76 [0.53, 0.90] (n = 17); dev:
   0.96 vs 0.93 (n = 78 / 40). Intervals overlap, and the baseline is judged only on the few questions it does not
   refuse, so this is not a significant difference; the baseline's main failure is refusing, not inventing.
4. **The judge needed a rubric fix before it could be trusted.** Against 50 hand-labelled dev answers (human labels,
   4 unfaithful), the first rubric reached only κ = 0.09: it rated correct arithmetic ("the difference is CHF 8,480.8m")
   as only partially supported, and accepted numbers whose unit appeared only in the question. After stating both
   rules explicitly, the judge agreed on 50/50 (κ = 1.00). This is in-sample — the rubric was revised after seeing
   these disagreements — and 4 positives make κ fragile, so treat it as "no known disagreement", not as a held-out
   accuracy.

Caveats: 100 dev / 50 test questions give wide intervals; k was chosen on dev; the generator and judge are different
DeepSeek models but from the same family; dev k = 3 / 5 were not judged (budget); 1 baseline dev answer got no
judge verdict (empty output twice) and is excluded.

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

## Development

```bash
cp .env.example .env   # add DEEPSEEK_API_KEY
make setup             # uv sync, Postgres+pgvector in Docker, migrations
make test
make llm-smoke         # run twice: second call is cached and free
```

Embeddings, reranking and parsing run on a local CUDA GPU (`uv sync --extra gpu`, check with `make gpu-smoke`);
without one, use `uv sync --extra cpu`.

## Roadmap

Done: corpus and parsing, evaluation set, retrieval lab (Phase 3), RAG with citations and abstention, validated LLM
judge (Phase 4). Next: extracted key figures with a guarded text-to-SQL tool, an MCP server and routed agent, a
deterministic permission layer measured against a prompt-injection suite, CI regression tiers, and a self-hosted vs
API model comparison.
