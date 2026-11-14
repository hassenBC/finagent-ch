"""Opt-in deny enforcement for one stdio server process per agent session.

Returned labels accumulate monotonically; side-effect invocations consume the configured
budget even if they fail (a failure cannot prove that no side effect occurred). R3 escalations
are left to the agent loop, which can ask a human. Only FINAGENT_SERVER_POLICY=1 enables this.
State lasts for the process, including across client reconnects; reset is for tests only.
"""

from __future__ import annotations

import inspect
import json
import os
from functools import wraps
from threading import RLock

from mcp.server.mcpserver.exceptions import ToolError

_lock = RLock()
_state = None


def reset_state() -> None:
    """Simulate a fresh server process in in-memory tests."""
    global _state
    with _lock:
        _state = None


def server_policy(fn):
    signature = inspect.signature(fn)

    @wraps(fn)
    def inner(*args, **kwargs):
        if os.environ.get("FINAGENT_SERVER_POLICY") != "1":
            return fn(*args, **kwargs)

        from finagent.policy.model import LEVELS, FlowState, load_policy
        from finagent.policy.rules import RULES

        global _state
        with _lock:
            if _state is None:
                _state = FlowState()
            cfg = load_policy()
            spec = cfg.tools.get(fn.__name__)
            if spec is None:
                raise ToolError("blocked by server policy: R0_default_deny unknown tool")
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            for rule in RULES:
                if rule.decision == "deny" and rule.when(
                    fn.__name__, bound.arguments, spec, _state, cfg
                ):
                    raise ToolError(f"blocked by server policy: {rule.id} {rule.reason}")
            _state.side_effects += spec.side_effect
            result = fn(*args, **kwargs)
            labels = json.loads(result)["_labels"]
            _state.max_sensitivity = max(
                _state.max_sensitivity, labels["sensitivity"], key=LEVELS.index
            )
            _state.tainted |= labels["trust"] == "untrusted"
            return result

    return inner
