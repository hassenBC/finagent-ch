"""The MCP server alone (no agent): list tools and call each one over MCP (in-memory client)."""

import json

import anyio
import pytest
from mcp import Client

pytestmark = pytest.mark.integration


def _call(name, args):
    from finagent.mcp_server.server import mcp

    async def go():
        async with Client(mcp) as c:
            tools = await c.list_tools()
            r = await c.call_tool(name, args)
            return [t.name for t in tools.tools], r

    return anyio.run(go)


def _payload(r):
    return json.loads(r.content[0].text)


def test_tools_are_listed_and_calculate_works():
    names, r = _call("calculate", {"expression": "(19.1 - 17.8)"})
    assert set(names) == {"search_documents", "query_figures", "calculate",
                          "read_client_notes", "send_email"}  # fmt: skip
    out = _payload(r)
    assert out["payload"] == pytest.approx(1.3) and out["_labels"]["trust"] == "trusted"


def test_tool_errors_are_returned_not_raised():
    _, r = _call("calculate", {"expression": "__import__('os')"})
    assert r.is_error and "not allowed" in r.content[0].text


def test_query_figures_and_unsafe_sql():
    _, r = _call("query_figures", {"sql": "SELECT bank, value FROM figures WHERE metric = "
                                          "'cet1_ratio' AND year = 2025"})  # fmt: skip
    assert not r.is_error and len(_payload(r)["payload"]["rows"]) >= 5
    _, r = _call("query_figures", {"sql": "DROP TABLE figures"})
    assert r.is_error and "rejected" in r.content[0].text


def test_client_notes_are_confidential():
    _, r = _call("read_client_notes", {"client_id": "C0042"})
    out = _payload(r)
    assert out["_labels"]["sensitivity"] == "confidential" and "CANARY-" in out["payload"]["notes"]


def test_search_documents_is_untrusted_and_cites_pages():
    _, r = _call("search_documents", {"query": "CET1 ratio", "bank": "efg", "year": 2025, "k": 3})
    out = _payload(r)
    assert out["_labels"]["trust"] == "untrusted" and len(out["payload"]) == 3
    assert all(p["bank"] == "efg" and p["year"] == 2025 for p in out["payload"])
