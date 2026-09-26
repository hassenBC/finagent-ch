"""Blind spot check of the QA dataset (plan Step 2.5).

python -m eval.spotcheck sheet    # writes eval/spotcheck/sheet.md: questions only, no answers
python -m eval.spotcheck reveal   # prints the dataset's answer, evidence and page for the same 20
"""

from __future__ import annotations

import json
import random
import sys

from finagent.config import ROOT
from finagent.ingest.download import read_sources

DS = ROOT / "eval" / "datasets"
OUT = ROOT / "eval" / "spotcheck"
SEED = 7


def items() -> list[dict]:
    rows = [json.loads(ln) for n in ("dev", "test") for ln in open(DS / f"qa_{n}.jsonl")]
    rows.sort(key=lambda r: r["id"])
    return random.Random(SEED).sample(rows, 20)


def pdf_of(item: dict) -> str:
    names = {
        r["sha256"]: f"data/raw/{r['bank']}_{r['year']}_{r['doc_type']}.pdf" for r in read_sources()
    }
    return ", ".join(names[g["sha256"]] for g in item["gold_pages"]) or f"data/raw/{item['bank']}_*"


def sheet() -> None:
    lines = ["# Spot check: answer each question yourself from the PDFs, then run `reveal`\n"]
    for k, it in enumerate(items(), 1):
        where = (
            "(unanswerable? search the bank's two reports)"
            if not it["answerable"]
            else "(find it yourself in the report named in the question)"
        )
        lines += [
            f"## {k}. {it['id']}  [{it['type']}, {it['lang']}]",
            it["question"],
            f"- bank/year: {it['bank']} {it['year']} {where}",
            "- my answer: ",
            "- found on page: ",
            "- verdict (ok / ambiguous / wrong answer / not answerable): ",
            "",
        ]
    OUT.mkdir(exist_ok=True)
    (OUT / "sheet.md").write_text("\n".join(lines))
    print(f"wrote {OUT / 'sheet.md'}")


def reveal() -> None:
    for k, it in enumerate(items(), 1):
        print(f"\n## {k}. {it['id']} [{it['type']}] {it['question']}")
        print(f"   dataset answer : {it['answer'] or '(unanswerable)'}")
        print(f"   evidence       : {it['evidence'][:200]}")
        print(f"   gold page(s)   : {[g['page'] for g in it['gold_pages']]} in {pdf_of(it)}")


if __name__ == "__main__":
    {"sheet": sheet, "reveal": reveal}[sys.argv[1]]()
