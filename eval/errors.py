"""Dump the questions a retrieval config misses, for hand-labelling the failure cause (Step 3.4).

python -m eval.errors <config name> [--k 5] [--n 20]   -> results/errors_<config>.md
"""

from __future__ import annotations

import argparse
import json
import random

from finagent.config import ROOT
from finagent.db import pool

CAUSES = [
    "table split badly",
    "header lost",
    "wrong year retrieved",
    "wrong bank retrieved",
    "number format mismatch",
    "cross-lingual gap",
    "question ambiguous",
    "parse error",
    "gold too narrow (answer also on an unlisted page)",
    "other",
]


def misses(config: str, k: int) -> list[dict]:
    with pool().connection() as conn:
        rows = conn.execute(
            """WITH latest AS (
                   SELECT run_id FROM eval_runs WHERE kind = 'retrieval' AND config->>'name' = %s
                   ORDER BY started_at DESC LIMIT 1)
               SELECT r.item_id, r.output FROM eval_results r JOIN latest USING (run_id)
               WHERE (r.metrics->>%s)::float = 0 ORDER BY r.item_id""",
            (config, f"recall@{k}"),
        ).fetchall()
    return [{"id": i, **o} for i, o in rows]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--n", type=int, default=20)
    args = ap.parse_args()

    items = {}
    for name in ("dev", "test"):
        for ln in (ROOT / "eval" / "datasets" / f"qa_{name}.jsonl").read_text().splitlines():
            it = json.loads(ln)
            items[it["id"]] = it
    missed = misses(args.config, args.k)
    sample = sorted(
        random.Random(0).sample(missed, min(args.n, len(missed))), key=lambda m: m["id"]
    )

    with pool().connection() as conn:
        docs = {
            d: (b, y, sha)
            for d, b, y, sha in conn.execute("SELECT doc_id, bank, year, sha256 FROM documents")
        }
        sha_doc = {sha: d for d, (_, _, sha) in docs.items()}
        out = [
            f"# Misses of `{args.config}` at recall@{args.k}: {len(sample)} of {len(missed)}\n",
            "Label each with one cause: " + ", ".join(CAUSES) + ".\n",
        ]
        for m in sample:
            it = items[m["id"]]
            gold = [(sha_doc[g["sha256"]], g["page"]) for g in it["gold_pages"]]
            out.append(f"## {it['id']} [{it['type']}, {it['lang']}] {it['bank']} {it['year']}")
            out.append(f"**Q:** {it['question']}\n\n**Evidence:** {it['evidence'][:300]}")
            out.append(f"**Gold:** {[(docs[d][0], docs[d][1], p) for d, p in gold]}")
            for d, p in gold[:2]:
                text = conn.execute(
                    "SELECT left(text, 500) FROM pages WHERE doc_id = %s AND page_no = %s", (d, p)
                ).fetchone()[0]
                out.append(f"> gold page {p}: {' '.join(text.split())[:400]}")
            out.append("**Top hits:**")
            for h in m["hits"][:3]:
                b, y, _ = docs[h["doc_id"]]
                content = conn.execute(
                    "SELECT left(content, 220) FROM chunks WHERE chunk_id = %s", (h["chunk_id"],)
                ).fetchone()[0]
                out.append(
                    f"- {b} {y} p{h['pages'][0]}-{h['pages'][1]}: {' '.join(content.split())}"
                )
            out.append("\n**Cause:** \n")
    path = ROOT / "results" / f"errors_{args.config}.md"
    path.write_text("\n".join(out))
    print(f"wrote {path} ({len(sample)} of {len(missed)} misses)")


if __name__ == "__main__":
    main()
