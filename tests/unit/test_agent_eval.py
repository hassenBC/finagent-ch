from eval.run_agent_eval import check, failure, first_bank
from finagent.agent.loop import AgentRun, Step


def run(answer, reason="answered", steps=(), route="figures"):
    return AgentRun(trace_id="t", answer=answer, citations=[], steps=list(steps), route=route,
                    stopped_reason=reason)  # fmt: skip


def test_first_bank_is_the_earliest_mention():
    assert first_bank("Swissquote had the highest (24.9%), ahead of Vontobel") == "swissquote"
    assert first_bank("Ahead of Julius Baer, Swissquote led") == "juliusbaer"
    assert first_bank("no bank here") is None


def test_numbers_check_needs_every_number():
    t = {"check": {"numbers": [{"value": 302.0, "unit": "CHF_m", "tolerance": 1.5},
                               {"value": 2.0, "unit": "count", "tolerance": 0.0}]}}  # fmt: skip
    assert check(t, run("Expenses were CHF 302 million; the board met 2 times."))
    assert not check(t, run("Expenses were CHF 302 million."))


def test_abstain_check_and_failure_taxonomy():
    oos = {"check": {"abstain": True}, "expected_route": "out_of_scope", "expected_tools": []}
    assert check(oos, run("I cannot answer this.", "abstained", route="out_of_scope"))
    assert failure(oos, run("Paris.", route="out_of_scope"), "routed", False) == "missed_abstention"
    fig = {"check": {"numbers": [{"value": 1.0, "unit": "pct", "tolerance": 0.1}]},
           "expected_route": "figures", "expected_tools": ["query_figures"]}  # fmt: skip
    assert failure(fig, run("x", route="documents"), "routed", False) == "wrong_route"
    assert failure(fig, run("I cannot answer.", "abstained"), "routed", False) == "false_abstention"
    ok_step = Step(tool="query_figures", args={}, decision="allow", ok=True)
    assert failure(fig, run("5%", steps=[ok_step]), "routed", False) == "wrong_answer"
