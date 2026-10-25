<!-- Output of `make regression` (security skipped) on a throwaway branch whose only change is
     use_metadata_filters: false in the final retrieval config. Exit code 1. -->
## Regression check

| Metric | Value | Threshold | |
|---|---|---|---|
| retrieval.recall@5 | 0.789 | ≥ 0.82 | ❌ BREACH |
| retrieval.mrr@10 | 0.677 | ≥ 0.68 | ❌ BREACH |
| rag.numeric_em | 0.691 | ≥ 0.7 | ❌ BREACH |
| rag.citation_precision | 0.722 | ≥ 0.65 | ✅ |
| rag.false_abstention_rate | 0.211 | ≤ 0.2 | ❌ BREACH |
| agent.task_success | 0.917 | ≥ 0.85 | ✅ |
| agent.routing_accuracy | 0.967 | ≥ 0.9 | ✅ |

### Regression diff: `baseline/retrieval` → `this run/retrieval`

90 common items: 78 → 71 passing; **7 regressions**, 0 fixes.

**Pass → fail** (text_lookup: 2, cross_lingual: 2, table_compute: 1, table_lookup: 1, comparison: 1)

- `q011` (table_compute)
- `q016` (text_lookup)
- `q031` (cross_lingual)
- `q032` (table_lookup)
- `q046` (text_lookup)
- `q059` (cross_lingual)
- `q145` (comparison)


### Regression diff: `baseline/rag` → `this run/rag`

100 common items: 81 → 76 passing; **5 regressions**, 0 fixes.

**Pass → fail** (comparison: 2, text_lookup: 1, table_lookup: 1, french: 1)

- `q016` (text_lookup)
- `q032` (table_lookup)
- `q071` (comparison)
- `q096` (french)
- `q150` (comparison)


### Regression diff: `baseline/agent` → `this run/agent`

60 common items: 55 → 55 passing; **0 regressions**, 0 fixes.

