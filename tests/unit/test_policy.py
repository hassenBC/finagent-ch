"""Policy engine: every rule, decision precedence, default deny, static check (no LLM, no DB)."""

import time

import pytest

from finagent.agent.loop import SessionState
from finagent.agent.router import ALL_TOOLS, ROUTE_TOOLS
from finagent.policy.engine import PolicyEngine, static_check
from finagent.policy.model import recipient_is_internal
from finagent.policy.rules import RULE_IDS

INTERNAL = {"to": "analyst@bank.example", "subject": "s", "body": "b"}
EXTERNAL = {"to": "someone@gmail.com", "subject": "s", "body": "b"}


def check(tool, args, executed=(), active=None):
    return PolicyEngine(active=active).check(tool, args, SessionState(calls=list(executed)))


def test_default_deny_for_unknown_tools():
    d = check("delete_everything", {})
    assert d.decision == "deny" and d.rule_id == "R0_default_deny"


def test_plain_calls_are_allowed():
    assert check("search_documents", {"query": "x"}).decision == "allow"
    assert check("send_email", INTERNAL).decision == "allow"


def test_r1_confidential_then_external_egress():
    d = check("send_email", EXTERNAL, ["read_client_notes"], active={"R1_no_confidential_egress"})
    assert (d.decision, d.rule_id) == ("deny", "R1_no_confidential_egress")
    # internal recipient: allowed even after a confidential read
    assert check("send_email", INTERNAL, ["read_client_notes"]).decision == "allow"


def test_r2_recipient_allowlist():
    d = check("send_email", EXTERNAL, active={"R2_recipient_allowlist"})
    assert (d.decision, d.rule_id) == ("deny", "R2_recipient_allowlist")


@pytest.mark.parametrize(
    "to",
    [
        "a@bank.example.evil.com",
        "a@evil.com,b@bank.example",
        "bank.example",
        "",
        "a@@bank.example",
        "a@BANK.example x",
    ],
)
def test_allowlist_is_strict(to):
    assert not recipient_is_internal(to, PolicyEngine().cfg)


def test_r3_tainted_side_effect_escalates():
    d = check("send_email", INTERNAL, ["search_documents"])
    assert (d.decision, d.rule_id) == ("escalate", "R3_tainted_side_effect")


def test_r3_human_confirmation_allows():
    eng = PolicyEngine(confirm=lambda tool, args, reason: True)
    d = eng.check("send_email", INTERNAL, SessionState(calls=["search_documents"]))
    assert d.decision == "allow" and d.rule_id == "R3_tainted_side_effect"


def test_r4_side_effect_budget():
    d = check("send_email", INTERNAL, ["send_email", "send_email"])
    assert (d.decision, d.rule_id) == ("deny", "R4_side_effect_budget")
    assert check("send_email", INTERNAL, ["send_email"]).decision == "allow"


def test_r5_sql_guard():
    d = check("query_figures", {"sql": "DROP TABLE figures"})
    assert (d.decision, d.rule_id) == ("deny", "R5_sql_guard")
    assert check("query_figures", {"sql": "SELECT * FROM figures"}).decision == "allow"


def test_deny_wins_over_escalate():
    # tainted (R3 escalate) + external recipient (R2 deny) -> deny
    d = check("send_email", EXTERNAL, ["search_documents"])
    assert d.decision == "deny"


def test_taint_and_sensitivity_are_sticky():
    later = ["search_documents", "calculate", "query_figures", "calculate"]
    assert check("send_email", INTERNAL, later).decision == "escalate"
    d = check("send_email", EXTERNAL, ["read_client_notes", "calculate", "calculate"])
    assert d.rule_id == "R1_no_confidential_egress"


def test_no_rules_active_allows_everything_known():
    assert check("send_email", EXTERNAL, ["read_client_notes"], active=set()).decision == "allow"


def test_static_check_flags_single_agent_not_routed_sub_agents():
    single = static_check(ALL_TOOLS, active=set())
    assert single.flagged and not single.accepted
    assert static_check(ALL_TOOLS).accepted  # flagged but R1 + R3 active
    for route, tools in ROUTE_TOOLS.items():
        assert not static_check(tools, active=set()).flagged, route


def test_static_check_rejects_unknown_tools():
    assert not static_check(["search_documents", "shell"]).accepted


def test_policy_overhead_is_below_one_millisecond():
    eng, st = PolicyEngine(), SessionState(calls=["search_documents", "read_client_notes"] * 5)
    n, t0 = 2000, time.perf_counter()
    for _ in range(n):
        eng.check("send_email", EXTERNAL, st)
    assert (time.perf_counter() - t0) / n < 1e-3


def test_rule_ids_are_unique():
    assert len(RULE_IDS) == len(set(RULE_IDS)) == 5
