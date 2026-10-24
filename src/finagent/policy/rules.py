"""Rules as data (Phase 7.3). Each rule: id, a condition on (tool, args, spec, state), a decision.

Decision order: any deny wins over escalate, which wins over allow. Unknown tools: default deny.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from finagent.figures.sql_tool import UnsafeSQL, validate_sql
from finagent.policy.model import LEVELS, FlowState, PolicyConfig, ToolSpec, recipient_is_internal


def external_egress(tool: str, args: dict, spec: ToolSpec, cfg: PolicyConfig) -> bool:
    """send_email to allowlisted domains stays inside the bank; anything else leaves it."""
    if spec.egress != "external":
        return False
    return not (tool == "send_email" and recipient_is_internal(args.get("to", ""), cfg))


def _sql_unsafe(args: dict) -> bool:
    try:
        validate_sql(str(args.get("sql", "")))
    except UnsafeSQL:
        return True
    return False


@dataclass(frozen=True)
class Rule:
    id: str
    decision: str  # deny | escalate
    reason: str
    when: Callable[[str, dict, ToolSpec, FlowState, PolicyConfig], bool]


RULES: list[Rule] = [
    Rule("R1_no_confidential_egress", "deny",
         "confidential data is in the context and this call sends data outside the bank",
         lambda t, a, sp, st, c: LEVELS.index(st.max_sensitivity) >= LEVELS.index("confidential")
         and external_egress(t, a, sp, c)),
    Rule("R2_recipient_allowlist", "deny", "recipient domain is not on the allowlist",
         lambda t, a, sp, st, c: t == "send_email"
         and not recipient_is_internal(a.get("to", ""), c)),
    Rule("R3_tainted_side_effect", "escalate",
         "untrusted document text is in the context; a human must confirm this action",
         lambda t, a, sp, st, c: st.tainted and sp.side_effect),
    Rule("R4_side_effect_budget", "deny", "more than the allowed side-effect calls in one session",
         lambda t, a, sp, st, c: sp.side_effect and st.side_effects >= c.side_effect_budget),
    Rule("R5_sql_guard", "deny", "SQL rejected by the validator",
         lambda t, a, sp, st, c: t == "query_figures" and _sql_unsafe(a)),
]  # fmt: skip
RULE_IDS = [r.id for r in RULES]
