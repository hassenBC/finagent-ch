"""Select 150 reviewed candidates, balance them, split 100 dev / 50 test, write the datasets."""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections import defaultdict

from eval.build_candidates import TARGETS
from finagent.config import ROOT
from finagent.ingest.text import normalise_numbers

CAND = ROOT / "eval" / "candidates" / "candidates.jsonl"
REJECTED = ROOT / "eval" / "candidates" / "rejected.txt"  # one candidate key per line
OUT = ROOT / "eval" / "datasets"
SEED = 20261107
PARAPHRASE_BELOW = 0.2  # question/evidence word overlap under this counts as paraphrased
TEST_SIZE = 50


def key(row: dict) -> str:
    return hashlib.sha1(row["question"].encode()).hexdigest()[:8]


def tolerance(row: dict) -> float:
    decimals = max(
        (len(n.split(".")[1]) if "." in n else 0 for n in _numstr(row)),
        default=0,
    )
    return 0.5 * 10**-decimals


def _numstr(row: dict) -> list[str]:
    src = row["calculation"] or row["evidence"]
    return re.findall(r"\d+(?:\.\d+)?", normalise_numbers(src))


_YEAR = re.compile(r"\b(?:19|20)\d\d\b")


def rejection(r: dict) -> str | None:
    """Systematic quality rules applied on top of the machine checks and the manual reject list."""
    years = set(_YEAR.findall(r["question"]))
    if r["answerable"] and years and str(r["year"]) not in years:
        return "question names only other fiscal years than the gold document"
    if r["type"] == "comparison":
        pages = {(p["sha256"], p["page"]) for p in r["gold_pages"]}
        if len(pages) < 2:
            return "comparison needs two distinct gold pages"
        if re.match(r"\s*(0\b|no difference|both|neither|the same|equal)", r["answer"], re.I):
            return "degenerate comparison (no difference)"
    if r["answerable"] and r["type"] in {
        "table_lookup",
        "table_compute",
        "french",
        "cross_lingual",
    }:
        q = normalise_numbers(r["question"])
        leaked = {
            n
            for n in re.findall(r"\d[\d.]{2,}", normalise_numbers(r["evidence"]))
            if n in q and not _YEAR.fullmatch(n)
        }
        if leaked:
            return f"question contains evidence numbers {sorted(leaked)}"
    return None


def load() -> list[dict]:
    rejected = set(REJECTED.read_text().split()) if REJECTED.exists() else set()
    rows = []
    for line in CAND.read_text().splitlines():
        r = json.loads(line)
        if not r["checks"]["ok"] or key(r) in rejected or rejection(r):
            continue
        r["paraphrased"] = r["checks"].get("overlap", 0.0) < PARAPHRASE_BELOW
        rows.append(r)
    return rows


def select(rows: list[dict], rng: random.Random) -> list[dict]:
    """Per type: round-robin over (bank, year), alternating paraphrased/literal, unique pages."""
    chosen: list[dict] = []
    used_pages: set[tuple] = set()
    for typ, n in TARGETS.items():
        pool = [r for r in rows if r["type"] == typ]
        rng.shuffle(pool)
        pools = {
            True: [r for r in pool if r["paraphrased"]],
            False: [r for r in pool if not r["paraphrased"]],
        }
        picked: list[dict] = []
        want = True
        seen_docs: defaultdict[tuple, int] = defaultdict(int)
        while len(picked) < n and (pools[True] or pools[False]):
            side = pools[want] or pools[not want]
            side.sort(key=lambda r: seen_docs[(r["bank"], r["year"])])
            r = side.pop(0)
            pages = {(p["sha256"], p["page"]) for p in r["gold_pages"]}
            if pages & used_pages:
                continue
            used_pages |= pages
            seen_docs[(r["bank"], r["year"])] += 1
            picked.append(r)
            want = not want
        chosen += picked
    return chosen


def split(rows: list[dict], rng: random.Random) -> dict[str, str]:
    """Stratified by type (and language within type): ~1/3 of each stratum goes to test."""
    split_of: dict[str, str] = {}
    strata: defaultdict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        strata[(r["type"], r["lang"])].append(r)
    test_n = {s: round(len(v) / 3) for s, v in strata.items()}
    order = sorted(strata)
    i = 0
    while sum(test_n.values()) > TEST_SIZE:
        s = order[i % len(order)]
        if test_n[s] > 0:
            test_n[s] -= 1
        i += 1
    while sum(test_n.values()) < TEST_SIZE:
        s = order[i % len(order)]
        if test_n[s] < len(strata[s]):
            test_n[s] += 1
        i += 1
    for s, v in strata.items():
        rng.shuffle(v)
        for j, r in enumerate(v):
            split_of[key(r)] = "test" if j < test_n[s] else "dev"
    return split_of


def to_item(r: dict, qid: str) -> dict:
    numeric = None
    if r["answer_value"] is not None and r["answer_unit"] != "none":
        numeric = {"value": r["answer_value"], "unit": r["answer_unit"], "tolerance": tolerance(r)}
    return {
        "id": qid,
        "question": r["question"],
        "lang": r["lang"],
        "type": r["type"],
        "bank": r["bank"],
        "year": r["year"],
        "answerable": r["answerable"],
        "gold_pages": r["gold_pages"],
        "evidence": r["evidence"],
        "answer": r["answer"],
        "answer_numeric": numeric,
        "paraphrased": r["paraphrased"],
        "notes": "",
    }


def main(show: bool = False) -> None:
    rng = random.Random(SEED)
    rows = select(load(), rng)
    split_of = split(rows, rng)
    rng.shuffle(rows)  # ids must not reveal the type
    out: dict[str, list[dict]] = {"dev": [], "test": []}
    for i, r in enumerate(rows, 1):
        item = to_item(r, f"q{i:03d}")
        item["_key"] = key(r)
        out[split_of[key(r)]].append(item)
    if show:
        for item in out["dev"] + out["test"]:
            print(
                item["_key"],
                item["id"],
                item["type"],
                item["bank"],
                item["year"],
                "|",
                item["question"],
                "=>",
                item["answer"][:80],
            )
        return
    for name, items in out.items():
        for it in items:
            del it["_key"]
        with open(OUT / f"qa_{name}.jsonl", "w") as f:
            for it in sorted(items, key=lambda x: x["id"]):
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
    for name, items in out.items():
        print(name, len(items), {t: sum(i["type"] == t for i in items) for t in TARGETS})


if __name__ == "__main__":
    import sys

    main(show="--show" in sys.argv)
