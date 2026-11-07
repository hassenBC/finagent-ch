"""Build eval/datasets/agent_tasks.jsonl (Phase 6.5): 60 tasks with automatic checks.

python -m eval.build_agent_tasks
Sources (deterministic, seed 65): documents = numeric qa_DEV items (never test) that are not key
metrics; figures = gold figures; mixed = one gold figure + one qa_dev number for the same bank
and year; client = synthetic client_notes; out_of_scope = hand-written. Checks: `numbers` (all
must appear, with tolerance), `keywords` (any must appear) or `abstain`.
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter

from finagent.clients import make_clients
from finagent.config import ROOT
from finagent.db import pool
from finagent.figures.gold_sheet import load_metrics
from finagent.ingest.text import BANK_NAMES

OUT = ROOT / "eval/datasets/agent_tasks.jsonl"
LABEL = {
    "net_profit": "net profit",
    "operating_income": "operating income",
    "cet1_ratio": "CET1 ratio",
    "total_capital_ratio": "total capital ratio",
    "leverage_ratio": "leverage ratio",
    "total_assets": "total assets",
    "headcount_fte": "headcount (FTE)",
    "operating_expenses": "operating expenses",
}
UNIT_TXT = {"CHF_m": "in CHF million", "CHF_bn": "in CHF billion", "pct": "in percent", "count": ""}
KEY_METRIC_WORDS = re.compile(
    r"net profit|bénéfice net|résultat net|CET1|leverage|levier|total assets|total du bilan|"
    r"cost/income|charges/produits|assets under management|client assets|net new money|"
    r"return on equity|ROE|full-time|FTE|effectif|operating income|operating expenses",
    re.I,
)
BANK_KEYWORDS = {
    "juliusbaer": ["Julius Baer", "Julius Bär", "juliusbaer"],
    "vontobel": ["Vontobel"],
    "efg": ["EFG"],
    "swissquote": ["Swissquote"],
    "bcv": ["BCV"],
    "bcge": ["BCGE"],
}


def task(tid, kind, text, route, tools, check):
    return {
        "id": tid,
        "kind": kind,
        "task": text,
        "expected_route": route,
        "expected_tools": tools,
        "check": check,
    }


def num(value, unit, tol=None):
    tol = tol if tol is not None else max(abs(value) * 0.005, 0.05)
    return {"value": round(value, 4), "unit": unit, "tolerance": round(tol, 4)}


def main() -> None:
    rng = random.Random(65)
    with pool().connection() as conn:
        gold = {
            (b, y, m): float(v)
            for b, y, m, v in conn.execute(
                "SELECT bank, year, metric, value FROM figures WHERE source = 'gold'"
            )
        }
    units = {k: v["unit"] for k, v in load_metrics().items()}
    qa = [json.loads(ln) for ln in (ROOT / "eval/datasets/qa_dev.jsonl").read_text().splitlines()]
    docs_pool = [
        q
        for q in qa
        if q["answerable"]
        and q.get("answer_numeric")
        and not KEY_METRIC_WORDS.search(q["question"])
    ]
    rng.shuffle(docs_pool)
    tasks = []

    # 20 documents
    for q in docs_pool[:20]:
        tasks.append(
            task(
                f"d_{q['id']}",
                "documents",
                q["question"],
                "documents",
                ["search_documents"],
                {"numbers": [q["answer_numeric"]]},
            )
        )

    # 15 figures: 6 lookups, 5 year-on-year changes, 4 rankings
    cells = sorted(k for k in gold if k[2] in LABEL)
    for i, (b, y, m) in enumerate(rng.sample(cells, 6)):
        tasks.append(
            task(
                f"f{i:02d}",
                "figures",
                f"What was {BANK_NAMES[b]}'s {LABEL[m]} in {y} {UNIT_TXT[units[m]]}?",
                "figures",
                ["query_figures"],
                {"numbers": [num(gold[b, y, m], units[m])]},
            )
        )
    pairs = sorted({(b, m) for b, _, m in cells if (b, 2024, m) in gold and (b, 2025, m) in gold})
    for i, (b, m) in enumerate(rng.sample(pairs, 5)):
        d = gold[b, 2025, m] - gold[b, 2024, m]
        if units[m] == "pct":
            text, val = (
                (
                    f"By how many percentage points did {BANK_NAMES[b]}'s {LABEL[m]} change "
                    "from 2024 to 2025?"
                ),
                d,
            )
        else:
            text, val = (
                (f"By what percentage did {BANK_NAMES[b]}'s {LABEL[m]} change from 2024 to 2025?"),
                100 * d / gold[b, 2024, m],
            )
        tasks.append(
            task(
                f"f{6 + i:02d}",
                "figures",
                text,
                "figures",
                ["query_figures"],
                {"numbers": [num(val, "pct", tol=0.15)]},
            )
        )
    for i, (m, y, hi) in enumerate(
        [
            ("cet1_ratio", 2024, True),
            ("total_assets", 2025, False),
            ("net_profit", 2024, True),
            ("leverage_ratio", 2025, True),
        ]
    ):
        vals = {b: v for (b, yy, mm), v in gold.items() if mm == m and yy == y}
        best = (max if hi else min)(vals, key=vals.get)
        word = "highest" if hi else "lowest"
        tasks.append(
            task(
                f"f{11 + i:02d}",
                "figures",
                f"Which of the six banks had the {word} {LABEL[m]} in {y}?",
                "figures",
                ["query_figures"],
                {"first_bank": best},
            )
        )

    # 10 mixed: a gold figure + a document number, same bank and year
    by_by = {}
    for q in docs_pool[20:]:
        by_by.setdefault((q["bank"], q["year"]), q)
    combos = [(k, q) for k, q in sorted(by_by.items()) if any(c[:2] == k for c in cells)]
    for i, ((b, y), q) in enumerate(combos[:10]):
        m = rng.choice(sorted(c[2] for c in cells if c[:2] == (b, y)))
        tasks.append(
            task(
                f"m{i:02d}",
                "documents_and_figures",
                f"Two questions about {BANK_NAMES[b]} for fiscal year {y}: (1) what was its "
                f"{LABEL[m]} {UNIT_TXT[units[m]]}? (2) {q['question']}",
                "documents_and_figures",
                ["query_figures", "search_documents"],
                {"numbers": [num(gold[b, y, m], units[m]), q["answer_numeric"]]},
            )
        )

    # 8 client (synthetic)
    clients = {c["client_id"]: c for c in make_clients()}
    picks = rng.sample(sorted(clients), 8)
    for i, cid in enumerate(picks):
        c, name = clients[cid], clients[cid]["display_name"]
        if i < 3:
            text, chk = (
                f"What share of {cid}'s portfolio is invested in equities?",
                {"numbers": [num(c["allocation"]["equities"], "pct", tol=0.5)]},
            )
        elif i < 5:
            text, chk = (
                f"What is the total portfolio value of {name} ({cid}) in CHF?",
                {"numbers": [num(c["portfolio_chf"], "CHF", tol=1.0)]},
            )
        elif i < 7:
            text, chk = (
                f"Summarise the allocation of client {cid}: what is its risk profile?",
                {"keywords": [c["risk_profile"]]},
            )
        else:
            other = picks[0]
            a, o = c["allocation"]["bonds"], clients[other]["allocation"]["bonds"]
            text = (
                f"By how many percentage points does the bond allocation of {cid} differ "
                f"from that of {other}?"
            )
            chk = {"numbers": [num(abs(a - o), "pct", tol=0.5)]}
        tasks.append(task(f"c{i:02d}", "client", text, "client", ["read_client_notes"], chk))

    # 7 out of scope
    for i, text in enumerate(
        [
            "What is the capital of France?",
            "What was UBS's CET1 ratio in 2025?",
            "Write a short poem about the Swiss Alps.",
            "What will Vontobel's share price be at the end of 2027?",
            "What is the current price of Bitcoin?",
            "Which football club won the 2024 Champions League?",
            "Translate 'good morning' into Japanese.",
        ]
    ):
        tasks.append(task(f"o{i:02d}", "out_of_scope", text, "out_of_scope", [], {"abstain": True}))

    OUT.write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in tasks))
    print(len(tasks), Counter(t["kind"] for t in tasks))


if __name__ == "__main__":
    main()
