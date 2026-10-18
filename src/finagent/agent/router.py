"""Router + least-privilege sub-agents (Phase 6.4), and the single-agent baseline.

One structured LLM call picks a route; the sub-agent for that route sees only the tools it needs.
`out_of_scope` gets no tools and no agent call at all.
"""

from __future__ import annotations

from typing import Literal

import anyio
from mcp import Client
from pydantic import BaseModel

from finagent.agent.loop import AgentConfig, AgentRun, Policy, run_agent
from finagent.llm.client import LLMClient

RouteName = Literal["documents", "figures", "documents_and_figures", "client", "out_of_scope"]

ROUTE_TOOLS: dict[str, list[str]] = {
    "documents": ["search_documents", "calculate"],
    "figures": ["query_figures", "calculate"],
    "documents_and_figures": ["search_documents", "query_figures", "calculate"],
    "client": ["read_client_notes", "send_email", "calculate"],
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
- client: about a client of the bank (ids like C0042) or e-mailing information;
- out_of_scope: anything else.
Also return the bank (one of the ids above) and year if the question names exactly one.

Question: {question}"""


def classify(question: str, llm: LLMClient) -> tuple[Route, float]:
    msgs = [{"role": "user", "content": ROUTER_PROMPT.format(question=question)}]
    try:
        r = llm.chat(msgs, response_format=Route, max_tokens=1500)
    except ValueError:
        r = llm.chat(msgs, response_format=Route, max_tokens=3000)
    return r.parsed, r.cost_usd


async def ask(question: str, mode: Literal["routed", "single"] = "routed",
              cfg: AgentConfig | None = None, policy: Policy | None = None,
              session: Client | None = None) -> AgentRun:  # fmt: skip
    cfg = cfg or AgentConfig()
    if mode == "single":
        return await run_agent(question, cfg.model_copy(update={"tools": ALL_TOOLS}), policy,
                               session, route="single")  # fmt: skip
    llm = LLMClient.from_config(cfg.model)
    route, cost = await anyio.to_thread.run_sync(lambda: classify(question, llm))
    if route.route == "out_of_scope":
        return AgentRun(trace_id="", answer="I cannot answer this: it is outside the reports and "
                        "clients I can access.", citations=[], steps=[], route="out_of_scope",
                        cost_usd=cost, stopped_reason="abstained")  # fmt: skip
    sub = cfg.model_copy(update={"tools": ROUTE_TOOLS[route.route]})
    run = await run_agent(question, sub, policy, session, route=route.route)
    return run.model_copy(update={"cost_usd": run.cost_usd + cost})
