"""Agent evaluation (Phase 6.5): routed sub-agents vs one agent with all tools.

python -m eval.run_agent_eval [--modes routed single] [--runs 1] [--limit N] [--max-cost 1.0]
  -> results/agent.csv (per mode), results/agent_by_kind.csv, results/agent_items.csv
Run 0 uses the normal LLM cache; runs 1.. use a cache salt so each repeat is a fresh API call.
"""

from __future__ import annotations

import argparse
import json
import re

import anyio
import pandas as pd

from eval.build_agent_tasks import BANK_KEYWORDS
from eval.rag_metrics import numeric_match
from finagent.agent.loop import AgentConfig, AgentRun, mcp_session
from finagent.agent.router import ask
from finagent.config import ROOT

TASKS = ROOT / "eval/datasets/agent_tasks.jsonl"
ABSTAIN = re.compile(r"cannot answer|can't answer|unable to answer|ne peux pas|do not have|"
                     r"don't have|not available|outside", re.I)  # fmt: skip


def first_bank(answer: str) -> str | None:
    pos = {b: min((i for k in kws if (i := answer.lower().find(k.lower())) >= 0), default=None)
           for b, kws in BANK_KEYWORDS.items()}  # fmt: skip
    found = {b: p for b, p in pos.items() if p is not None}
    return min(found, key=found.get) if found else None


def check(task: dict, run: AgentRun) -> bool:
    c, a = task["check"], run.answer
    abstained = run.stopped_reason == "abstained" or bool(ABSTAIN.search(a))
    if c.get("abstain"):
        return abstained
    if "numbers" in c:
        return all(numeric_match(a, g)["em_any"] == 1.0 for g in c["numbers"])
    if "first_bank" in c:
        return first_bank(a) == c["first_bank"]
    return any(k.lower() in a.lower() for k in c.get("keywords", []))


def failure(task: dict, run: AgentRun, mode: str, ok: bool) -> str:
    if ok:
        return ""
    called = {s.tool for s in run.steps if s.ok}
    if mode == "routed" and run.route != task["expected_route"]:
        return "wrong_route"
    if task["check"].get("abstain"):
        return "missed_abstention"
    if run.stopped_reason == "max_steps":
        return "max_steps"
    if run.stopped_reason == "error":
        return "error"
    if not set(task["expected_tools"]) <= called:
        return "false_abstention" if run.stopped_reason == "abstained" else "wrong_tool"
    if any(not s.ok for s in run.steps):
        return "tool_error_then_wrong"
    return "false_abstention" if run.stopped_reason == "abstained" else "wrong_answer"


def row(task: dict, run: AgentRun, mode: str, run_idx: int) -> dict:
    ok = check(task, run)
    exp = set(task["expected_tools"])
    called = {s.tool for s in run.steps if s.decision == "allow"} - {"calculate"}
    return {
        "id": task["id"], "kind": task["kind"], "mode": mode, "run": run_idx, "success": ok,
        "route": run.route, "route_ok": run.route == task["expected_route"],
        "tool_precision": len(called & exp) / len(called) if called else float(not exp),
        "tool_recall": len(called & exp) / len(exp) if exp else float(not called),
        "n_calls": len(run.steps), "n_valid_calls": sum(s.ok for s in run.steps),
        "latency_ms": run.latency_ms, "cost_usd": run.cost_usd, "tokens_in": run.tokens_in,
        "tokens_out": run.tokens_out, "stopped": run.stopped_reason,
        "failure": failure(task, run, mode, ok), "answer": run.answer[:500],
        "tools": json.dumps([s.tool for s in run.steps]),
    }  # fmt: skip


async def evaluate(tasks, modes, runs, max_cost) -> list[dict]:
    rows, spent = [], 0.0
    async with mcp_session() as session:  # one server for all tasks
        for run_idx in range(runs):
            salt = f"agent-run-{run_idx}" if run_idx else None
            for mode in modes:
                for t in tasks:
                    cfg = AgentConfig(cache_salt=salt)
                    run = await ask(t["task"], mode, cfg, None, session)
                    spent += run.cost_usd
                    rows.append(row(t, run, mode, run_idx))
                    if spent > max_cost:
                        print(f"STOP: cost cap ${max_cost} reached")
                        return rows
            print(f"run {run_idx} done, spent ${spent:.3f}", flush=True)
    return rows


def summarise(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    g = df.groupby(by)
    out = g.agg(n=("id", "size"), success=("success", "mean"), routing_acc=("route_ok", "mean"),
                tool_precision=("tool_precision", "mean"), tool_recall=("tool_recall", "mean"),
                calls_per_task=("n_calls", "mean"), cost_per_task=("cost_usd", "mean"),
                latency_p50_ms=("latency_ms", "median"),
                latency_p95_ms=("latency_ms", lambda x: x.quantile(0.95)))  # fmt: skip
    calls = g[["n_calls", "n_valid_calls"]].sum()
    out["arg_validity"] = calls["n_valid_calls"] / calls["n_calls"].clip(lower=1)
    return out.round(4).reset_index()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", nargs="+", default=["routed", "single"])
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--max-cost", type=float, default=1.0)
    args = ap.parse_args()
    tasks = [json.loads(ln) for ln in TASKS.read_text().splitlines()][: args.limit]
    df = pd.DataFrame(anyio.run(evaluate, tasks, args.modes, args.runs, args.max_cost))
    res = ROOT / "results"
    df.to_csv(res / "agent_items.csv", index=False)
    summary = summarise(df, ["mode"])
    if df["run"].nunique() > 1:  # share of tasks solved in every run
        allruns = df.groupby(["mode", "id"])["success"].all().groupby("mode").mean()
        summary["solved_all_runs"] = summary["mode"].map(allruns).round(4)
    summary["failures"] = summary["mode"].map(
        lambda m: json.dumps(df[(df["mode"] == m) & (df["failure"] != "")]["failure"]
                             .value_counts().to_dict()))  # fmt: skip
    summary.to_csv(res / "agent.csv", index=False)
    summarise(df, ["mode", "kind"]).to_csv(res / "agent_by_kind.csv", index=False)
    print(summary.drop(columns=["failures"]).to_string(index=False))
    print(summary[["mode", "failures"]].to_string(index=False))


if __name__ == "__main__":
    main()
