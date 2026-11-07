"""Per-item regression diff (Phase 8.3): which items went pass -> fail and fail -> pass.

python -m eval.diff A B [--md out.md]
A and B are each one of:
  <run uuid>                      a run in eval_runs (retrieval, rag or judge)
  <kind>:<config name>[@dataset]  the latest run of that config (dataset defaults to qa_dev)
  <path>.csv                      an item file (agent_items / security_items), pass = `success`
                                  (for security attacks pass = the attack FAILED)
Averages hide regressions: a change can gain three items and lose two different ones.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

from finagent.config import ROOT
from finagent.db import pool

DEV = "eval/datasets/qa_dev.jsonl"


def passed(kind: str, m: dict) -> bool:
    if kind == "retrieval":
        return float(m.get("recall@5") or 0) > 0
    if kind == "judge":
        return float(m.get("faithful") or 0) == 1.0
    if kind == "rag":
        if not m.get("answerable", True):
            return bool(m.get("abstain"))
        if "em_any" in m and m["em_any"] is not None:
            return float(m["em_any"]) == 1.0
        return bool(m.get("has_correct_citation"))
    raise ValueError(f"unknown kind {kind}")


def _types(dataset: str) -> dict[str, str]:
    p = ROOT / dataset
    if not p.exists():
        return {}
    return {r["id"]: r.get("type", "") for r in map(json.loads, p.read_text().splitlines())}


def load(spec: str) -> tuple[str, dict[str, bool], dict[str, str]]:
    """-> (label, {item: passed}, {item: type})."""
    if spec.endswith(".csv"):
        df = pd.read_csv(spec if spec.startswith("/") else ROOT / spec)
        keys = [c for c in ("suite", "mode", "defence", "run") if c in df.columns]
        df["key"] = df[keys + ["id"]].astype(str).agg("/".join, axis=1)
        ok = df["success"].astype(bool)
        if "suite" in df.columns:
            ok = ok.where(df["suite"] != "attack", ~ok)  # an attack "passes" when it fails
        typ = df.get("category", df.get("kind", pd.Series([""] * len(df))))
        return (
            Path(spec).name,
            dict(zip(df["key"], ok, strict=True)),
            dict(zip(df["key"], typ.astype(str), strict=True)),
        )
    with pool().connection() as conn:
        if ":" in spec:
            kind, rest = spec.split(":", 1)
            name, _, dataset = rest.partition("@")
            row = conn.execute(
                "SELECT run_id, kind, dataset FROM eval_runs WHERE kind = %s AND "
                "config->>'name' = %s AND dataset = %s ORDER BY started_at DESC LIMIT 1",
                (kind, name, dataset or DEV),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT run_id, kind, dataset FROM eval_runs WHERE run_id = %s", (spec,)
            ).fetchone()
        if row is None:
            raise SystemExit(f"no run for {spec!r}")
        run_id, kind, dataset = row
        items = conn.execute(
            "SELECT item_id, metrics FROM eval_results WHERE run_id = %s", (run_id,)
        ).fetchall()
    return f"{spec} ({str(run_id)[:8]})", {i: passed(kind, m) for i, m in items}, _types(dataset)


def diff(a: dict[str, bool], b: dict[str, bool], types: dict[str, str]) -> dict:
    common = sorted(set(a) & set(b))
    return {
        "n": len(common),
        "pass_a": sum(a[i] for i in common),
        "pass_b": sum(b[i] for i in common),
        "regressions": [(i, types.get(i, "")) for i in common if a[i] and not b[i]],
        "fixes": [(i, types.get(i, "")) for i in common if not a[i] and b[i]],
        "only_a": sorted(set(a) - set(b)),
        "only_b": sorted(set(b) - set(a)),
    }


def markdown(label_a: str, label_b: str, d: dict) -> str:
    out = [
        f"### Regression diff: `{label_a}` → `{label_b}`",
        "",
        f"{d['n']} common items: {d['pass_a']} → {d['pass_b']} passing; "
        f"**{len(d['regressions'])} regressions**, {len(d['fixes'])} fixes.",
        "",
    ]
    for title, items in (("Pass → fail", d["regressions"]), ("Fail → pass", d["fixes"])):
        if items:
            by = Counter(t for _, t in items)
            groups = ", ".join(f"{t or '-'}: {n}" for t, n in by.most_common())
            out.append(f"**{title}** ({groups})")
            out.append("")
            out += [f"- `{i}` ({t})" if t else f"- `{i}`" for i, t in items]
            out.append("")
    if d["only_a"] or d["only_b"]:
        out.append(f"Only in A: {len(d['only_a'])}, only in B: {len(d['only_b'])}.")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--md", help="also write the markdown here (e.g. $GITHUB_STEP_SUMMARY)")
    args = ap.parse_args()
    la, a, ta = load(args.a)
    lb, b, tb = load(args.b)
    d = diff(a, b, ta | tb)
    text = markdown(la, lb, d)
    print(text)
    if args.md:
        with open(args.md, "a") as f:
            f.write(text + "\n")
    sys.exit(1 if d["regressions"] else 0)


if __name__ == "__main__":
    main()
