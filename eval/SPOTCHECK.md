# Spot check of the QA dataset (plan Step 2.5)

Blind check of 20 seeded items (`python -m eval.spotcheck sheet`, seed 7): the answers were derived from the PDFs
**before** the dataset answers were revealed. It was an **AI-assisted** check, not a human audit; the checker saw the
item types and the "unanswerable" label, but not the gold answers, evidence or pages.

| Result | Count |
|---|---|
| Dataset answer agrees with the independent answer | 20 / 20 (17 answerable, 3 correctly unanswerable) |
| Wrong answer | 0 |
| Strictly "ok" under the rubric | 9 |
| "Ambiguous" (rubric: same fact in two places or years) | 11 |

Nearly all of the 11 flags were the same fact appearing on several pages (opening/closing balances, key-figures page,
repeated mission statements, parent vs group accounts). That would undercount retrieval, so instead of dropping the items
the dataset now lists those pages as `alt_pages` (automatic scan + 13 manually verified extras, see
`eval/candidates/amendments.json`); retrieval treats a hit on a gold **or** alternate page as relevant.
One question (q013, BCGE auditor statement on other information) was reworded because its original phrasing could also
ask whether that information is audited.

Not done: the optional re-audit of the 20 parsed tables (the journal keeps "at least 3 of 20").
Limits: 20 of 150 items is a sample, not a guarantee; unanswerable items were checked only against the same bank's two reports.
