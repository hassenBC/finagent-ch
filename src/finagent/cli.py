"""finagent ask "question" [--single]  — answer with the routed agent and print the trace."""

from __future__ import annotations

import argparse
import json

import anyio
from psycopg.types.json import Jsonb
from rich.console import Console
from rich.markup import escape
from rich.tree import Tree

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
                (run.trace_id, i, s.tool, Jsonb(s.args), s.decision, s.rule_id,
                 s.result[:200] if s.decision != "allow" else None, s.latency_ms),
            )  # fmt: skip


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
    console.print(f"[dim]{run.stopped_reason} · {len(run.steps)} tool calls · {run.latency_ms} ms ·"
                  f" ${run.cost_usd:.4f} · trace {run.trace_id or '-'}[/]")  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser(prog="finagent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask", help="answer a question with the agent")
    a.add_argument("question")
    a.add_argument("--single", action="store_true", help="one agent with all tools, no router")
    a.add_argument("--policy", action="store_true", help="enforce the Phase 7 policy engine")
    args = ap.parse_args()
    policy = None
    if args.policy:
        from finagent.policy.engine import PolicyEngine

        def confirm(tool, call_args, reason):
            print(f"\n[policy] {tool} needs confirmation: {reason}\n  args: {call_args}")
            return input("  allow? [y/N] ").strip().lower() == "y"

        policy = PolicyEngine(confirm=confirm)
    mode = "single" if args.single else "routed"
    run = anyio.run(lambda: ask(args.question, mode, None, policy))
    save_trace(args.question, run)
    print_run(args.question, run, Console())


if __name__ == "__main__":
    main()
