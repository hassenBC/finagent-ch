"""Policy model (Phase 7.1–7.2): tool specs and coarse information-flow state.

The state is derived from the calls that actually ran (in order), so it cannot be talked out
of anything: once a confidential or untrusted output has entered the context, it stays there.
Limitation (by design, coarse): after one confidential read, *everything* later is treated as
confidential, even text that does not contain the confidential data.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

import yaml
from pydantic import BaseModel

from finagent.config import ROOT

Sensitivity = Literal["public", "internal", "confidential"]
LEVELS: list[str] = ["public", "internal", "confidential"]


class ToolSpec(BaseModel):
    reads: list[str]
    output_sensitivity: Sensitivity
    output_trust: Literal["trusted", "untrusted"]
    side_effect: bool
    egress: Literal["none", "external"]


class PolicyConfig(BaseModel):
    tools: dict[str, ToolSpec]
    default: Literal["deny", "allow"] = "deny"
    email_allowlist: list[str]
    side_effect_budget: int = 2


@lru_cache
def load_policy(path: str = "configs/policy/tools.yaml") -> PolicyConfig:
    return PolicyConfig.model_validate(yaml.safe_load((ROOT / path).read_text()))


class FlowState(BaseModel):
    max_sensitivity: Sensitivity = "public"
    tainted: bool = False  # untrusted content has entered the context
    side_effects: int = 0


def flow_state(executed: list[str], cfg: PolicyConfig) -> FlowState:
    """Fold the executed calls into the session state."""
    s = FlowState()
    for name in executed:
        spec = cfg.tools.get(name)
        if spec is None:
            continue
        if LEVELS.index(spec.output_sensitivity) > LEVELS.index(s.max_sensitivity):
            s.max_sensitivity = spec.output_sensitivity
        s.tainted |= spec.output_trust == "untrusted"
        s.side_effects += spec.side_effect
    return s


def recipient_is_internal(to: str, cfg: PolicyConfig) -> bool:
    """True only if every recipient is a plain ASCII address on an allowlisted domain.

    Non-ASCII is refused outright: `str.lower()` folds look-alikes such as the Kelvin sign
    (U+212A) to ASCII, so `a@banK.example` would otherwise pass as `bank.example`."""
    addrs = [a.strip() for a in str(to).replace(";", ",").split(",") if a.strip()]
    return bool(addrs) and all(
        a.isascii() and a.count("@") == 1 and a.rsplit("@", 1)[1].lower() in cfg.email_allowlist
        for a in addrs
    )
