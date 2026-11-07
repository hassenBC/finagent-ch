"""Minimal tracing (Phase 8.4): nested spans with latency and attributes, stored in `spans`.

Off unless FINAGENT_TRACING=1 and a trace id is active (`start(trace_id)` or FINAGENT_TRACE_ID,
which the agent passes to the MCP server process). Evaluation runs leave it off.
"""

from __future__ import annotations

import os
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

_trace: ContextVar[str | None] = ContextVar("trace", default=None)
_parent: ContextVar[str | None] = ContextVar("parent", default=None)
_global_trace: str | None = None  # fallback for worker threads that do not inherit context


def start(trace_id: str) -> None:
    global _global_trace
    _global_trace = trace_id
    _trace.set(trace_id)


def current() -> str | None:
    return _trace.get() or _global_trace or os.environ.get("FINAGENT_TRACE_ID")


def enabled() -> bool:
    return os.environ.get("FINAGENT_TRACING") == "1" and current() is not None


class Span:
    def __init__(self) -> None:
        self.attrs: dict[str, Any] = {}

    def set(self, **attrs: Any) -> None:
        self.attrs.update(attrs)


@contextmanager
def span(name: str, **attrs: Any):
    """with span("retrieve.fts", n=50) as s: ...; s.set(hits=12)"""
    s = Span()
    s.set(**attrs)
    if not enabled():
        yield s
        return
    sid, parent = str(uuid.uuid4()), _parent.get()
    token = _parent.set(sid)
    started, t0 = datetime.now(UTC), time.perf_counter()
    try:
        yield s
    except Exception as e:
        s.set(error=f"{type(e).__name__}: {e}"[:200])
        raise
    finally:
        _parent.reset(token)
        _save(current(), sid, parent, name, started, 1000 * (time.perf_counter() - t0), s.attrs)


def _save(trace, sid, parent, name, started, ms, attrs) -> None:
    from psycopg.types.json import Jsonb

    from finagent.db import pool

    process = "mcp_server" if os.environ.get("FINAGENT_PROCESS") == "mcp_server" else "agent"
    try:
        with pool().connection() as conn:
            conn.execute(
                "INSERT INTO spans (trace_id, span_id, parent_id, name, process, started_at, ms,"
                " attrs) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (trace, sid, parent, name, process, started, ms, Jsonb(attrs)),
            )
    except Exception:  # tracing must never break the request
        pass
