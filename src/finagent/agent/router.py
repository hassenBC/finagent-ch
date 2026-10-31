"""Router + least-privilege sub-agents (Phase 6.4), and the single-agent baseline.

One structured LLM call picks a route; the sub-agent for that route sees only the tools it needs.
`out_of_scope` gets no tools and no agent call at all.
"""

from __future__ import annotations

from contextlib import suppress
from typing import Literal

import anyio
from mcp import Client
from pydantic import BaseModel

from finagent import tracing
from finagent.agent.loop import AgentConfig, AgentRun, Policy, run_agent
from finagent.llm.client import LLMClient

RouteName = Literal[
    "documents", "figures", "documents_and_figures", "client", "share", "out_of_scope"
]

ROUTE_TOOLS: dict[str, list[str]] = {
    "documents": ["search_documents", "calculate"],
    "figures": ["query_figures", "calculate"],
    "documents_and_figures": ["search_documents", "query_figures", "calculate"],
    "client": ["read_client_notes", "send_email", "calculate"],
    # e-mailing report content (no client data: never confidential + untrusted + egress at once)
    "share": ["search_documents", "query_figures", "calculate", "send_email"],
    "out_of_scope": [],
}
ALL_TOOLS = ["search_documents", "query_figures", "calculate", "read_client_notes", "send_email"]


class Route(BaseModel):
    route: RouteName
    bank: str | None = None
    year: int | None = None


ROUTER_PROMPT = """Classify a question for a system that knows the FY2024/FY2025 annual reports of
six Swiss banks (juliusbaer, vontobel, efg, swissquote, bcv, bcge) and the bank's own clients.
Routes:
- figures: only key metrics (net profit, operating income/expenses, cost/income, CET1, total
  capital, leverage ratio, AuM / client assets, net new money, total assets, ROE, headcount),
  including rankings, averages and year-on-year changes of these metrics;
- documents: anything else in the reports (strategy, risks, governance, notes, other numbers);
- documents_and_figures: needs both a key metric and other report content;
- client: about a client of the bank (ids like C0042), including e-mailing client information;
- share: e-mailing report figures or report content (no client data) to someone;
- out_of_scope: anything else.
Also return the bank (one of the ids above) and year if the question names exactly one.

Question: {question}"""


def classify(question: str, llm: LLMClient, salt: str | None = None) -> tuple[Route, float]:
    msgs = [{"role": "user", "content": ROUTER_PROMPT.format(question=question)}]
    try:
        r = llm.chat(msgs, response_format=Route, max_tokens=1500, cache_salt=salt)
    except ValueError:
        r = llm.chat(msgs, response_format=Route, max_tokens=3000, cache_salt=salt)
    return r.parsed, r.cost_usd


async def ask(question: str, mode: Literal["routed", "single"] = "routed",
              cfg: AgentConfig | None = None, policy: Policy | None = None,
              session: Client | None = None, trace_id: str | None = None,
              on_event=None) -> AgentRun:  # fmt: skip
    cfg = cfg or AgentConfig()
    if mode == "single":
        return await run_agent(question, cfg.model_copy(update={"tools": ALL_TOOLS}), policy,
                               session, route="single", trace_id=trace_id,
                               on_event=on_event)  # fmt: skip
    llm = LLMClient.from_config(cfg.model)
    with tracing.span("route") as sp:
        route, cost = await anyio.to_thread.run_sync(
            lambda: classify(question, llm, cfg.cache_salt)
        )
        sp.set(route=route.route, bank=route.bank, year=route.year)
    if on_event:
        with suppress(Exception):  # a broken listener must never break the agent
            on_event("route", {"route": route.route, "bank": route.bank, "year": route.year,
                           "tools": ROUTE_TOOLS[route.route], "cost_usd": cost})  # fmt: skip
    if route.route == "out_of_scope":
        return AgentRun(trace_id=trace_id or "",
                        answer="I cannot answer this: it is outside the reports and "
                        "clients I can access.", citations=[], steps=[], route="out_of_scope",
                        cost_usd=cost, stopped_reason="abstained")  # fmt: skip
    sub = cfg.model_copy(update={"tools": ROUTE_TOOLS[route.route]})
    run = await run_agent(
        question, sub, policy, session, route=route.route, trace_id=trace_id, on_event=on_event
    )
    return run.model_copy(update={"cost_usd": run.cost_usd + cost})
