"""Oversized tool arguments are rejected before any parsing, translation or database work."""

import pytest

from finagent.mcp_server import tools


def test_cap_lengths_accepts_normal_and_rejects_oversized():
    tools.cap_lengths(query="capital ratio", to="a@bank.example", subject="s", body="x" * 20000)
    with pytest.raises(ValueError, match="body is too long"):
        tools.cap_lengths(body="x" * 20001)


@pytest.mark.parametrize(
    ("fn", "kwargs"),
    [
        (tools.send_email, {"to": "a@bank.example", "subject": "s", "body": "A" * 100_000}),
        (tools.send_email, {"to": "a" * 400 + "@x.example", "subject": "s", "body": "b"}),
        (tools.query_figures, {"sql": "SELECT 1 /*" + "x" * 5000 + "*/"}),
        (tools.search_documents, {"query": "q" * 5000}),
        (tools.read_client_notes, {"client_id": "C" * 200}),
    ],
)
def test_tools_reject_oversized_arguments_before_doing_work(fn, kwargs):
    with pytest.raises(ValueError, match="too long"):
        fn(**kwargs)
