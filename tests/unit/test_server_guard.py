"""Server policy through in-memory MCP, with no database-backed implementations."""

import anyio
import pytest
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

from finagent.mcp_server import guard, tools
from finagent.mcp_server.server import mcp
from finagent.policy.model import load_policy


@pytest.fixture(autouse=True)
def isolated_server(monkeypatch):
    guard.reset_state()
    monkeypatch.delenv("FINAGENT_SERVER_POLICY", raising=False)
    calls = []

    def stub(name, sensitivity, trust="trusted"):
        def run(*args, **kwargs):
            calls.append(name)
            return tools.labelled({}, sensitivity, trust)

        monkeypatch.setattr(tools, name, run)

    stub("read_client_notes", "confidential")
    stub("send_email", "public")
    stub("search_documents", "public", "untrusted")
    stub("query_figures", "internal")
    yield calls
    guard.reset_state()


def run_calls(*calls):
    async def go():
        async with Client(mcp) as client:
            return [await client.call_tool(name, args) for name, args in calls]

    return anyio.run(go)


def email(to=None):
    return "send_email", {
        "to": to or f"advisor@{load_policy().email_allowlist[0]}",
        "subject": "s",
        "body": "b",
    }


NOTES = ("read_client_notes", {"client_id": "C0042"})


@pytest.mark.parametrize("setting", [None, "0", "true"])
def test_off(monkeypatch, setting, isolated_server):
    if setting is not None:
        monkeypatch.setenv("FINAGENT_SERVER_POLICY", setting)
    results = run_calls(NOTES, email("outside@external.example"))
    assert all(not r.is_error for r in results)
    assert isolated_server == ["read_client_notes", "send_email"]
    assert guard._state is None


def test_confidential_egress(monkeypatch, isolated_server):
    monkeypatch.setenv("FINAGENT_SERVER_POLICY", "1")
    read, denied = run_calls(NOTES, email("outside@external.example"))
    assert not read.is_error and denied.is_error
    assert "blocked by server policy: R1" in denied.content[0].text
    assert isolated_server == ["read_client_notes"]


def test_internal_allowed(monkeypatch):
    monkeypatch.setenv("FINAGENT_SERVER_POLICY", "1")
    assert not run_calls(email())[0].is_error


def test_budget(monkeypatch, isolated_server):
    monkeypatch.setenv("FINAGENT_SERVER_POLICY", "1")
    budget = load_policy().side_effect_budget
    assert budget == 2
    results = run_calls(*[email()] * (budget + 1))
    assert all(not r.is_error for r in results[:-1])
    assert results[-1].is_error
    assert "blocked by server policy: R4" in results[-1].content[0].text
    assert isolated_server == ["send_email"] * budget


def test_unsafe_sql(monkeypatch, isolated_server):
    monkeypatch.setenv("FINAGENT_SERVER_POLICY", "1")
    result = run_calls(("query_figures", {"sql": "DROP TABLE figures"}))[0]
    assert result.is_error
    assert "blocked by server policy: R5" in result.content[0].text
    assert isolated_server == []


def test_fresh_process_state(monkeypatch):
    monkeypatch.setenv("FINAGENT_SERVER_POLICY", "1")
    run_calls(NOTES, ("search_documents", {"query": "q"}), email(), email())
    assert guard._state.max_sensitivity == "confidential"
    assert guard._state.tainted
    assert guard._state.side_effects == 2
    guard.reset_state()  # A separate stdio process gets fresh module globals.
    assert not run_calls(email())[0].is_error
    assert guard._state.max_sensitivity == "public"
    assert not guard._state.tainted
    assert guard._state.side_effects == 1


def test_actual_labels_and_escalation(monkeypatch):
    monkeypatch.setenv("FINAGENT_SERVER_POLICY", "1")
    monkeypatch.setattr(
        tools, "calculate", lambda expression: tools.labelled(2, "confidential", "untrusted")
    )
    results = run_calls(("calculate", {"expression": "1+1"}), email())
    assert all(not r.is_error for r in results)  # R3 is left to the loop.
    assert guard._state.max_sensitivity == "confidential"
    assert guard._state.tainted


def test_unknown_tool(monkeypatch):
    monkeypatch.setenv("FINAGENT_SERVER_POLICY", "1")

    @guard.server_policy
    def unknown():
        pytest.fail("unknown tool must not execute")

    with pytest.raises(ToolError, match="blocked by server policy: R0_default_deny"):
        unknown()


def test_external_recipient_blocked_without_a_confidential_read(monkeypatch, isolated_server):
    monkeypatch.setenv("FINAGENT_SERVER_POLICY", "1")
    result = run_calls(email("someone@external.example"))[0]
    assert result.is_error
    assert "blocked by server policy: R2" in result.content[0].text
    assert isolated_server == []


def test_non_ascii_look_alike_recipient_is_blocked(monkeypatch, isolated_server):
    monkeypatch.setenv("FINAGENT_SERVER_POLICY", "1")
    domain = load_policy().email_allowlist[0].replace("k", "K")  # Kelvin sign
    result = run_calls(email(f"a@{domain}"))[0]
    assert result.is_error and "R2" in result.content[0].text
    assert isolated_server == []
