"""Deterministic policy engine (Phase 7.3–7.4): runtime checks and the pre-deployment static check.

No LLM decides whether a call is allowed — the model can be talked out of anything, code cannot.
"""

from __future__ import annotations

from pydantic import BaseModel

from finagent.agent.loop import Decision, SessionState
from finagent.policy.model import PolicyConfig, flow_state, load_policy
from finagent.policy.rules import RULE_IDS, RULES


class PolicyEngine:
    def __init__(
        self, cfg: PolicyConfig | None = None, active: set[str] | None = None, confirm=None
    ):
        self.cfg = cfg or load_policy()
        self.active = set(RULE_IDS) if active is None else active
        self.confirm = confirm  # optional callback(tool, args, reason) -> bool for escalations

    def check(self, tool: str, args: dict, state: SessionState) -> Decision:
        spec = self.cfg.tools.get(tool)
        if spec is None:
            if self.cfg.default == "deny":
                return Decision(decision="deny", rule_id="R0_default_deny", reason="unknown tool")
            return Decision(decision="allow")
        flow = flow_state(state.calls, self.cfg)
        fired = [
            r for r in RULES if r.id in self.active and r.when(tool, args, spec, flow, self.cfg)
        ]
        deny = next((r for r in fired if r.decision == "deny"), None)
        if deny:
            return Decision(decision="deny", rule_id=deny.id, reason=deny.reason)
        esc = next((r for r in fired if r.decision == "escalate"), None)
        if esc:
            if self.confirm and self.confirm(tool, args, esc.reason):
                return Decision(decision="allow", rule_id=esc.id, reason="confirmed by a human")
            return Decision(decision="escalate", rule_id=esc.id, reason=esc.reason)
        return Decision(decision="allow")


class StaticReport(BaseModel):
    tools: list[str]
    reads_confidential: bool
    ingests_untrusted: bool
    can_send_out: bool
    flagged: bool  # all three together: the data-leak combination
    accepted: bool
    reason: str


def static_check(
    toolset: list[str], active: set[str] | None = None, cfg: PolicyConfig | None = None
) -> StaticReport:
    """Flag a toolset that can read confidential data, ingest untrusted content and send data
    out. A flagged toolset is accepted only if the rules covering that flow (R1, R3) are active."""
    cfg = cfg or load_policy()
    active = set(RULE_IDS) if active is None else active
    unknown = [t for t in toolset if t not in cfg.tools]
    specs = [cfg.tools[t] for t in toolset if t in cfg.tools]
    conf = any(s.output_sensitivity == "confidential" for s in specs)
    untrusted = any(s.output_trust == "untrusted" for s in specs)
    out = any(s.egress == "external" for s in specs)
    flagged = conf and untrusted and out
    if unknown:
        return StaticReport(
            tools=toolset,
            reads_confidential=conf,
            ingests_untrusted=untrusted,
            can_send_out=out,
            flagged=flagged,
            accepted=False,
            reason=f"unknown tools {unknown} (default deny)",
        )
    covered = {"R1_no_confidential_egress", "R3_tainted_side_effect"} <= active
    accepted = not flagged or covered
    reason = (
        "no confidential-read + untrusted-input + egress combination"
        if not flagged
        else "flagged; accepted because R1 and R3 are active"
        if covered
        else "flagged: confidential read + untrusted input + egress without R1/R3"
    )
    return StaticReport(
        tools=toolset,
        reads_confidential=conf,
        ingests_untrusted=untrusted,
        can_send_out=out,
        flagged=flagged,
        accepted=accepted,
        reason=reason,
    )
