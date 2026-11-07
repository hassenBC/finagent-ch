"""Validate the faithfulness judge against hand labels (plan Step 4.4).

python -m eval.judge_validation sheet   -> eval/judge_validation/sheet.md + label template
                                            (the sheet shows no judge verdicts)
python -m eval.judge_validation score   -> judges the 50 answers, Cohen's kappa vs your labels
"""

from __future__ import annotations

import json
import random
import sys

from eval.judge import judge, scores
from eval.run_judge import chunk_text, latest_rag_run
from eval.run_rag import Budget
from finagent.config import ROOT, load_config
from finagent.llm.client import LLMClient

RUNS = ["rag_best_k3", "rag_best_k5", "rag_best_k10", "rag_baseline_k5"]
DATASET = "eval/datasets/qa_dev.jsonl"
OUT = ROOT / "eval" / "judge_validation"
LABELS = ROOT / "eval" / "datasets" / "faithfulness_labels.jsonl"
N, SEED = 50, 4

INSTRUCTIONS = """# Judge validation: is each answer faithful to the sources it cites?

Faithful = every factual claim in the answer is stated in the cited sources (numbers with the right
unit and period). Judge only against the cited sources, not against what you know or the report.
Fill `eval/datasets/faithfulness_labels.jsonl`: `faithful` true/false;
for false, the unsupported claim.
"""


def load_items() -> dict[str, dict]:
    rows = (json.loads(x) for x in (ROOT / DATASET).read_text().splitlines())
    return {r["id"]: r for r in rows}


def sample() -> list[dict]:
    """50 judge-able answers (not abstained, >= 1 citation), one per question, spread over runs."""
    rng = random.Random(SEED)
    pools = {}
    for name in RUNS:
        _, rows = latest_rag_run(name, DATASET)
        pools[name] = [(i, o) for i, m, o in rows if not m["abstain"] and o["citations"]]
        rng.shuffle(pools[name])
    picked, used = [], set()
    while len(picked) < N and any(pools.values()):
        for name in RUNS:
            while pools[name] and len(picked) < N:
                item_id, o = pools[name].pop()
                if item_id not in used:
                    used.add(item_id)
                    picked.append({"key": f"{name}:{item_id}", "item_id": item_id, **o})
                    break
    return sorted(picked, key=lambda p: p["key"])


def sheet() -> None:
    items, picks = load_items(), sample()
    texts = chunk_text([c["chunk_id"] for p in picks for c in p["citations"]])
    lines = [INSTRUCTIONS]
    for k, p in enumerate(picks, 1):
        lines += [
            f"## {k}. `{p['key']}`",
            f"**Q:** {items[p['item_id']]['question']}",
            f"**Answer:** {p['answer']}",
            "**Cited sources:**",
        ]
        for c in p["citations"]:
            pages = f"pages {c['page_start']}-{c['page_end']}"
            lines.append(f"- [{c['sid']}] {pages}:\n\n```\n{texts[c['chunk_id']]}\n```")
        lines.append("")
    OUT.mkdir(exist_ok=True)
    (OUT / "sheet.md").write_text("\n".join(lines))
    if not LABELS.exists():
        rows = [{"key": p["key"], "faithful": None, "unsupported_claim": ""} for p in picks]
        LABELS.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"wrote {OUT / 'sheet.md'} and {LABELS} ({len(picks)} answers)")


def score() -> None:
    from sklearn.metrics import cohen_kappa_score

    labels = {r["key"]: r for r in (json.loads(x) for x in LABELS.read_text().splitlines())}
    if any(r["faithful"] is None for r in labels.values()):
        sys.exit("some labels are still null")
    items = load_items()
    picks = [p for p in sample() if p["key"] in labels]
    texts = chunk_text([c["chunk_id"] for p in picks for c in p["citations"]])
    llm, budget = LLMClient.from_config(load_config().llm.judge), Budget(0.5)
    human, model = [], []
    for p in picks:
        it = items[p["item_id"]]
        cited = [texts[c["chunk_id"]] for c in p["citations"]]
        j, cost = judge(it["question"], p["answer"], cited, it["answer"], llm)
        budget.charge(cost)
        human.append(bool(labels[p["key"]]["faithful"]))
        model.append(bool(scores(j)["faithful"]))
    kappa = cohen_kappa_score(human, model)
    pairs = list(zip(human, model, strict=True))
    tp = sum(1 for h, m in pairs if not h and not m)  # the judge's job: catch UNfaithful answers
    fp = sum(1 for h, m in pairs if h and not m)
    fn = sum(1 for h, m in pairs if not h and m)
    print(
        f"n={len(pairs)} agreement={sum(h == m for h, m in pairs)}/{len(pairs)} kappa={kappa:.3f}"
        f" | unfaithful: human={human.count(False)} judge={model.count(False)}"
        f" precision={tp / max(1, tp + fp):.2f} recall={tp / max(1, tp + fn):.2f}"
        f" | judge cost ${budget.spent:.4f}"
    )


if __name__ == "__main__":
    {"sheet": sheet, "score": score}[sys.argv[1]]()
