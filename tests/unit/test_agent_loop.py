"""Agent loop with a scripted LLM and the real MCP server in memory (calculate only: no DB)."""

import anyio
from mcp import Client

from finagent.agent.loop import AgentConfig, Decision, run_agent
from finagent.llm.client import ChatResult, ToolCall
from finagent.mcp_server.server import mcp


class Scripted:
    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    def chat(self, messages, tools=None, max_tokens=0, **kw):
        self.seen.append([m["role"] for m in messages])
        return self.replies.pop(0)


def reply(text=None, calls=()):
    return ChatResult(text=text, tool_calls=list(calls), tokens_in=10, tokens_out=5,
                      latency_ms=1, cost_usd=0.001, cached=False, model="fake")  # fmt: skip


def call(name, args, raw=None, cid="c1"):
    return ToolCall(id=cid, name=name, arguments=args, arguments_raw=raw or str(args))


def run(llm, cfg=None, policy=None):
    async def go():
        async with Client(mcp) as s:
            return await run_agent("q", cfg or AgentConfig(), policy, s, llm=llm)

    return anyio.run(go)


def test_tool_call_then_answer():
    llm = Scripted([reply(calls=[call("calculate", {"expression": "19.1 - 17.8"})]),
                    reply("It rose by 1.3 points [efg-2025-p3].")])  # fmt: skip
    r = run(llm)
    assert r.stopped_reason == "answered" and r.citations == ["efg-2025-p3"]
    assert r.steps[0].ok and r.steps[0].labels["trust"] == "trusted"
    assert llm.seen[1] == ["system", "user", "assistant", "tool"] and r.cost_usd == 0.002


def test_invalid_json_and_unknown_or_forbidden_tool_are_reported_to_the_model():
    llm = Scripted([reply(calls=[call("calculate", None, raw="{bad"),
                                 call("send_email", {"to": "x", "subject": "s", "body": "b"},
                                      cid="c2")]),
                    reply("I cannot answer.")])  # fmt: skip
    r = run(llm, AgentConfig(tools=["calculate"]))
    assert [s.decision for s in r.steps] == ["invalid_args", "invalid_args"]
    assert r.stopped_reason == "abstained"


def test_policy_denial_is_returned_with_rule_id():
    class DenyAll:
        def check(self, tool, args, state):
            return Decision(decision="deny", rule_id="R_TEST", reason="no")

    llm = Scripted([reply(calls=[call("calculate", {"expression": "1+1"})]), reply("done")])
    r = run(llm, policy=DenyAll())
    assert r.steps[0].decision == "deny" and r.steps[0].result.startswith("DENIED by R_TEST")


def test_max_steps():
    llm = Scripted([reply(calls=[call("calculate", {"expression": "1+1"})])] * 3)
    r = run(llm, AgentConfig(max_steps=3))
    assert r.stopped_reason == "max_steps" and len(r.steps) == 3


def test_events_are_emitted_in_order_and_do_not_change_the_run():
    events = []
    llm = Scripted(
        [reply(calls=[call("calculate", {"expression": "1+1"})]), reply("2 [x-2025-p1]")]
    )

    async def go():
        async with Client(mcp) as s:
            return await run_agent("q", AgentConfig(), None, s, llm=llm,
                                   on_event=lambda k, d: events.append(k))  # fmt: skip

    r = anyio.run(go)
    assert r.stopped_reason == "answered"
    assert events == ["agent_start", "llm_request", "llm_response", "policy_check",
                      "policy_decision", "tool_start", "tool_end", "llm_request",
                      "llm_response", "final"]  # fmt: skip


def test_a_broken_listener_does_not_break_the_agent():
    llm = Scripted([reply("done")])

    def boom(kind, data):
        raise RuntimeError("listener bug")

    async def go():
        async with Client(mcp) as s:
            return await run_agent("q", AgentConfig(), None, s, llm=llm, on_event=boom)

    assert anyio.run(go).answer == "done"


def test_router_isolates_a_broken_listener(monkeypatch):
    from finagent.agent import router

    monkeypatch.setattr(router, "classify", lambda q, llm, salt=None: (
        router.Route(route="out_of_scope"), 0.0))  # fmt: skip

    def boom(kind, data):
        raise RuntimeError("listener bug")

    r = anyio.run(lambda: router.ask("weather?", "routed", AgentConfig(), on_event=boom))
    assert r.route == "out_of_scope" and r.stopped_reason == "abstained"
