"""finagent ask "question" [--single]  — answer with the routed agent and print the trace."""

from __future__ import annotations

import argparse
import json
import os
import uuid

import anyio
from psycopg.types.json import Jsonb
from rich.console import Console
from rich.markup import escape
from rich.tree import Tree

from finagent import tracing
from finagent.agent.loop import AgentRun
from finagent.agent.router import ask
from finagent.db import pool


def save_trace(question: str, run: AgentRun) -> None:
    if not run.trace_id:
        return
    with pool().connection() as conn, conn.transaction():
        conn.execute(
            "INSERT INTO traces (trace_id, query, started_at, total_ms, tokens_in, tokens_out,"
            " cost_usd) VALUES (%s, %s, now(), %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (run.trace_id, question, run.latency_ms, run.tokens_in, run.tokens_out, run.cost_usd),
        )
        for i, s in enumerate(run.steps):
            conn.execute(
                "INSERT INTO tool_calls (trace_id, step, tool, args, decision, rule_id, reason,"
                " latency_ms) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    run.trace_id,
                    i,
                    s.tool,
                    Jsonb(s.args),
                    s.decision,
                    s.rule_id,
                    s.result[:200] if s.decision != "allow" else None,
                    s.latency_ms,
                ),
            )


def print_run(question: str, run: AgentRun, console: Console) -> None:
    tree = Tree(f"[bold]{question}[/]  route=[cyan]{run.route}[/]")
    for i, s in enumerate(run.steps, 1):
        style = "green" if s.ok else ("red" if s.decision != "allow" else "yellow")
        args = escape(json.dumps(s.args, ensure_ascii=False)[:120])
        node = tree.add(f"[{style}]{i}. {s.tool}[/] {args}  ({s.decision}, {s.latency_ms} ms)")
        if s.labels:
            node.add(escape(f"labels: {s.labels}"))
        node.add(escape(s.result[:200].replace("\n", " ")))
    console.print(tree)
    console.print("\n" + escape(run.answer) + "\n")
    console.print(
        f"[dim]{run.stopped_reason} · {len(run.steps)} tool calls · {run.latency_ms} ms ·"
        f" ${run.cost_usd:.4f} · finagent trace {run.trace_id or '-'}[/]"
    )


def trace_tree(trace_id: str) -> Tree:
    """Spans as a tree; MCP-server spans (other process, no parent id) go under the tool call
    whose time window contains them."""
    with pool().connection() as conn:
        rows = conn.execute(
            "SELECT span_id, parent_id, name, process, started_at, ms, attrs FROM spans"
            " WHERE trace_id = %s ORDER BY started_at",
            (trace_id,),
        ).fetchall()
    if not rows:
        raise SystemExit(f"no spans for trace {trace_id} (run `finagent ask` with tracing on)")
    spans = {
        r[0]: {
            "id": r[0],
            "parent": r[1],
            "name": r[2],
            "proc": r[3],
            "t0": r[4],
            "ms": r[5],
            "attrs": r[6] or {},
            "kids": [],
        }
        for r in rows
    }
    for sp in spans.values():
        sp["t1"] = sp["t0"].timestamp() + sp["ms"] / 1000
    tools = [s for s in spans.values() if s["name"].startswith("tool.")]
    roots = []
    for sp in spans.values():
        parent = spans.get(sp["parent"]) if sp["parent"] else None
        if parent is None and sp["proc"] == "mcp_server":
            holders = [t for t in tools if t["t0"].timestamp() <= sp["t0"].timestamp() <= t["t1"]]
            parent = max(holders, key=lambda t: t["t0"]) if holders else None
        (parent["kids"] if parent else roots).append(sp)
    total = sum(s["ms"] for s in roots)
    cost = sum(float(s["attrs"].get("cost_usd", 0) or 0) for s in spans.values())
    tree = Tree(f"[bold]trace {trace_id}[/]  {total:.0f} ms, ${cost:.4f}")

    def add(node: Tree, sp: dict) -> None:
        a = {k: v for k, v in sp["attrs"].items() if k not in ("query",)}
        label = f"[cyan]{escape(sp['name'])}[/] {sp['ms']:.0f} ms"
        if sp["proc"] == "mcp_server":
            label += " [dim](server)[/]"
        if a:
            label += "  " + escape(json.dumps(a, ensure_ascii=False, default=str)[:160])
        child = node.add(label)
        for k in sorted(sp["kids"], key=lambda x: x["t0"]):
            add(child, k)

    for r in roots:
        add(tree, r)
    return tree


def main() -> None:
    ap = argparse.ArgumentParser(prog="finagent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask", help="answer a question with the agent")
    a.add_argument("question")
    a.add_argument("--single", action="store_true", help="one agent with all tools, no router")
    a.add_argument("--policy", action="store_true", help="enforce the Phase 7 policy engine")
    t = sub.add_parser("trace", help="print the spans of a trace as a tree")
    t.add_argument("trace_id")
    args = ap.parse_args()
    if args.cmd == "trace":
        Console().print(trace_tree(args.trace_id))
        return
    trace_id = str(uuid.uuid4())
    os.environ["FINAGENT_TRACING"] = "1"  # inherited by the MCP server process
    tracing.start(trace_id)
    policy = None
    if args.policy:
        from finagent.policy.engine import PolicyEngine

        def confirm(tool, call_args, reason):
            print(f"\n[policy] {tool} needs confirmation: {reason}\n  args: {call_args}")
            return input("  allow? [y/N] ").strip().lower() == "y"

        policy = PolicyEngine(confirm=confirm)
    mode = "single" if args.single else "routed"
    run = anyio.run(lambda: ask(args.question, mode, None, policy, trace_id=trace_id))
    save_trace(args.question, run)
    print_run(args.question, run, Console())


if __name__ == "__main__":
    main()
