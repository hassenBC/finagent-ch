"""Sample pages (seeded, stratified) and ask an LLM to propose one candidate question per page.

Candidates are only proposals: every one is machine-checked here (evidence and numbers must occur
on the gold page) and then reviewed by hand before it enters the dataset (eval/assemble.py).
"""

from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from pydantic import BaseModel

from eval.dataset_utils import EVIDENCE_SEP, evidence_on_pages, numbers, overlap, safe_eval
from finagent.config import ROOT
from finagent.db import pool
from finagent.ingest.text import normalise_numbers
from finagent.llm.client import LLMClient

OUT = ROOT / "eval" / "candidates" / "candidates.jsonl"
SEED = 20261106
LANG = {"en": "English", "fr": "French"}

# type -> (target in the final dataset, oversampling factor)
TARGETS = {
    "text_lookup": 30,
    "table_lookup": 35,
    "table_compute": 15,
    "comparison": 20,
    "cross_lingual": 15,
    "french": 20,
    "unanswerable": 15,
}
OVERSAMPLE = 1.7
OVERSAMPLE_BY_TYPE = {
    "comparison": 5.0,
    "unanswerable": 2.6,
}  # most page pairs share no comparable metric


class Proposal(BaseModel):
    feasible: bool
    question: str = ""
    evidence: str = ""  # copied from the page(s); parts from different pages joined by ' || '
    answer: str = ""
    value: float | None = None
    unit: Literal["pct", "CHF_m", "CHF_bn", "CHF", "count", "ratio", "none"] = "none"
    calculation: str | None = None  # arithmetic over numbers that appear in the evidence


RULES = """You write evaluation questions for a retrieval system over Swiss bank annual reports.
The reader of your question has NOT seen the page, and the corpus holds 6 banks x 2 fiscal years,
so every question must be self-contained: name the bank and the fiscal year or period explicitly,
state the metric precisely, never say "the table", "above" or "this page".
Exactly one correct answer; numbers with unit and period. Copy the evidence VERBATIM from the page
(a table row with its label and numbers, or one sentence); never invent or alter numbers.
If the page cannot support the requested kind of question, return feasible=false."""

STYLE = {
    "literal": "Use the report's own wording for the metric.",
    "paraphrase": (
        "Paraphrase: do NOT reuse the report's exact terms for the metric "
        "(e.g. 'capital adequacy' instead of 'CET1 ratio', 'money clients brought in' instead of "
        "'net new money'). A reader must understand the meaning, not match keywords."
    ),
}

TASK = {
    "text_lookup": "A question whose answer is stated in running prose (not in a table).",
    "table_lookup": "A question whose answer is ONE cell of a table. Fill value and unit.",
    "table_compute": (
        "A question that needs 2+ numbers from the table and simple arithmetic (difference, "
        "ratio, sum, percentage-point change). Fill calculation with an expression over the exact "
        "numbers in the evidence, e.g. '(19.7 - 18.7)', and value with its result."
    ),
    "comparison": (
        "A question comparing two things using the TWO pages given (two banks, or two years): "
        "e.g. which is higher, or the difference. evidence = evidence from page A, then "
        f"'{EVIDENCE_SEP.strip()}', then evidence from page B. Only feasible if both pages "
        "report the same metric for the same period."
    ),
    "cross_lingual": "A question whose answer is stated in prose or in one table cell.",
    "french": "A question whose answer is stated in prose or in one table cell. Fill value and "
    "unit when the answer is a number.",
    "unanswerable": (
        "A PLAUSIBLE question about the same bank and topic that this report does NOT answer: "
        "a future period (2026 or later forecast, unless the page states it), a metric the "
        "page does not give, or a client-level detail. It must sound like a real analyst "
        "question. evidence and answer stay empty; feasible=true."
    ),
}


def load_pages() -> dict[tuple[str, int, int], dict]:
    """(bank, year, page) -> {text, tables, sha, lang}; tables are table_aware chunks."""
    pages: dict[tuple[str, int, int], dict] = {}
    with pool().connection() as conn:
        for bank, year, lang, sha, pn, text in conn.execute(
            """SELECT d.bank, d.year, d.lang, d.sha256, p.page_no, p.text
               FROM pages p JOIN documents d USING (doc_id)"""
        ):
            pages[(bank, year, pn)] = {"text": text, "tables": [], "sha": sha, "lang": lang}
        for bank, year, pn, content in conn.execute(
            """SELECT d.bank, d.year, c.page_start, c.content
               FROM chunks c JOIN documents d USING (doc_id)
               WHERE c.chunker = 'table_aware' AND c.kind = 'table'"""
        ):
            pages[(bank, year, pn)]["tables"].append(content)
    return pages


def sample_pages(pool_keys: list, n: int, rng: random.Random, used: set) -> list:
    """Round-robin over (bank, year) so every document contributes equally."""
    by_doc: dict[tuple, list] = defaultdict(list)
    for k in pool_keys:
        if k not in used:
            by_doc[k[:2]].append(k)
    for v in by_doc.values():
        rng.shuffle(v)
    docs = sorted(by_doc)
    rng.shuffle(docs)
    out: list = []
    while len(out) < n and any(by_doc.values()):
        for d in docs:
            if by_doc[d] and len(out) < n:
                out.append(by_doc[d].pop())
    used.update(out)
    return out


def render(key: tuple, p: dict, label: str = "") -> str:
    bank, year, pn = key
    tables = "\n\n".join(p["tables"])[:5000]
    return (
        f"=== PAGE {label}: {bank} annual report {year}, PDF page {pn} ===\n{p['text'][:5000]}\n"
        + (f"--- tables on this page (Markdown) ---\n{tables}\n" if tables else "")
    )


def build_jobs(pages: dict, rng: random.Random) -> list[dict]:
    has_table = lambda k: bool(pages[k]["tables"])  # noqa: E731
    ok = {k for k, p in pages.items() if len(p["text"]) > 700}
    en = {k for k in ok if pages[k]["lang"] == "en"}
    fr = {k for k in ok if pages[k]["lang"] == "fr"}
    used: set = set()
    jobs: list[dict] = []

    def add(typ: str, pool_keys: set, lang: str, partner: bool = False):
        n = round(TARGETS[typ] * OVERSAMPLE_BY_TYPE.get(typ, OVERSAMPLE))
        for i, k in enumerate(sample_pages(sorted(pool_keys), n, rng, used)):
            jobs.append(
                {
                    "type": typ,
                    "keys": [k] + ([partner_for(k)] if partner else []),
                    "lang": lang,
                    "style": "paraphrase" if i % 2 else "literal",
                }
            )

    def partner_for(k: tuple) -> tuple:
        """Nearest table chunk (e5-small) on another bank's report of the same fiscal year."""
        with pool().connection() as conn:
            row = conn.execute(
                """SELECT e.embedding FROM chunks c JOIN documents d USING (doc_id)
                   JOIN emb_e5_small e USING (chunk_id)
                   WHERE c.chunker = 'table_aware' AND c.kind = 'table' AND d.bank = %s
                     AND d.year = %s AND c.page_start = %s ORDER BY c.n_tokens DESC LIMIT 1""",
                k,
            ).fetchone()
            if not row:
                return k
            near = conn.execute(
                """SELECT d.bank, d.year, c.page_start FROM emb_e5_small e
                   JOIN chunks c USING (chunk_id) JOIN documents d USING (doc_id)
                   WHERE c.chunker = 'table_aware' AND c.kind = 'table'
                     AND d.year = %s AND d.bank <> %s AND d.lang = 'en'
                   ORDER BY e.embedding <=> %s LIMIT 1""",
                (k[1], k[0], row[0]),
            ).fetchone()
        return tuple(near) if near else k

    add("text_lookup", {k for k in en if not has_table(k)}, "en")
    add("table_lookup", {k for k in en if has_table(k)}, "en")
    add("table_compute", {k for k in en if has_table(k)}, "en")
    add("comparison", {k for k in en if has_table(k)}, "en", partner=True)
    add("cross_lingual", fr, "en")
    add("french", fr, "fr")
    add("unanswerable", ok & (en | fr), "en")
    return jobs


def run_job(llm: LLMClient, pages: dict, job: dict) -> dict | None:
    keys = job["keys"]
    src = "\n".join(render(k, pages[k], "AB"[i]) for i, k in enumerate(keys))
    src_lang = LANG[pages[keys[0]]["lang"]]
    user = (
        f"{RULES}\n\nTask type: {job['type']}. {TASK[job['type']]}\n"
        f"Write the question in {LANG[job['lang']]} (the source text is {src_lang}). "
        f"{STYLE[job['style']]}\n\n{src}"
    )
    r = llm.chat([{"role": "user", "content": user}], response_format=Proposal, max_tokens=1500)
    prop: Proposal = r.parsed
    if not prop.feasible or not prop.question.strip():
        return None
    gold = (
        [{"sha256": pages[k]["sha"], "page": k[2]} for k in keys]
        if job["type"] != "unanswerable"
        else []
    )
    row = {
        "type": job["type"],
        "lang": job["lang"],
        "question": prop.question.strip(),
        "bank": keys[0][0],
        "year": keys[0][1],
        "answerable": job["type"] != "unanswerable",
        "gold_pages": gold,
        "gold_pages_meta": [list(k) for k in keys],
        "evidence": prop.evidence.strip(),
        "answer": prop.answer.strip(),
        "answer_value": prop.value,
        "answer_unit": prop.unit,
        "calculation": prop.calculation,
        "style": job["style"],
        "checks": {},
    }
    row["checks"] = check(row, [pages[k]["text"] for k in keys])
    return row


def check(row: dict, page_texts: list[str]) -> dict:
    """Machine checks. A candidate is 'ok' only if every applicable check passes."""
    if not row["answerable"]:
        return {"ok": True}
    c: dict = {"evidence": evidence_on_pages(row["evidence"], page_texts)}
    calc_expr = normalise_numbers(row["calculation"] or "")
    val = row["answer_value"]
    if row["type"] in {"table_lookup", "table_compute"} and val is not None:
        page_nums = set().union(*(numbers(t) for t in page_texts))
        if row["type"] == "table_lookup":
            c["value_on_page"] = abs(val) in page_nums or round(abs(val), 1) in page_nums
        else:
            try:
                calc = safe_eval(calc_expr)
                used = {abs(float(n)) for n in numbers(calc_expr)}
                c["calc"] = abs(calc - val) <= 1e-6 * max(1, abs(val)) + 0.05
                c["calc_inputs_on_page"] = used <= page_nums
            except (ValueError, SyntaxError, ZeroDivisionError):
                c["calc"] = False
    elif row["type"] in {"table_lookup", "table_compute"}:
        c["value_present"] = False
    c["overlap"] = round(overlap(row["question"], row["evidence"]), 2)
    c["ok"] = all(v for k, v in c.items() if k != "overlap")
    return c


def main() -> None:
    rng = random.Random(SEED)
    pages = load_pages()
    jobs = build_jobs(pages, rng)
    print(f"{len(jobs)} jobs", flush=True)
    llm = LLMClient.from_config("deepseek_flash")

    def work(j):
        try:
            return run_job(llm, pages, j)
        except Exception as e:  # keep going; log and move on
            print("job failed:", j["type"], j["keys"][0], repr(e)[:120], file=sys.stderr)
            return None

    with ThreadPoolExecutor(8) as ex:
        rows = [r for r in ex.map(work, jobs) if r]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    by = defaultdict(lambda: [0, 0])
    for r in rows:
        by[r["type"]][0] += 1
        by[r["type"]][1] += r["checks"]["ok"]
    for t, (n, ok) in by.items():
        print(f"{t:14} candidates={n:3} machine-ok={ok:3} target={TARGETS[t]}")


if __name__ == "__main__":
    main()
