"""finagent MCP server (Phase 6.2): five tools over stdio.

python -m finagent.mcp_server.server
Each tool returns a JSON string {"payload": ..., "_labels": {"sensitivity", "trust"}}.
Tool descriptions are prompts: the model chooses tools from them.
"""

from __future__ import annotations

from functools import wraps

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from finagent.figures.gold_sheet import load_metrics
from finagent.figures.sql_tool import tool_description
from finagent.mcp_server import tools
from finagent.mcp_server.guard import server_policy

mcp = MCPServer("finagent")


def model_errors(fn):
    """Expected failures (bad SQL, unknown client, invalid expression) go back to the model as
    tool errors with their reason, so it can correct itself; anything else stays a crash."""

    @wraps(fn)
    def inner(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as e:
            raise ToolError(str(e)) from e

    return inner


@mcp.tool(description=(
    "Search the annual reports (FY2024 and FY2025) of six Swiss banks: juliusbaer, vontobel, efg, "
    "swissquote (English) and bcv, bcge (French). Returns passages with bank, year, page and a "
    "source_id to cite. Use for qualitative questions, notes, governance, risk, or any figure that "
    "is not one of the key metrics. Pass bank and year when the question names them."
))  # fmt: skip
@model_errors
@server_policy
def search_documents(query: str, bank: str | None = None, year: int | None = None,
                     k: int = 5) -> str:  # fmt: skip
    return tools.dumps(tools.search_documents(query, bank, year, k))


@mcp.tool(description=tool_description(load_metrics()))
@model_errors
@server_policy
def query_figures(sql: str) -> str:
    return tools.dumps(tools.query_figures(sql))


@mcp.tool(description=(
    "Evaluate an arithmetic expression with numbers, + - * / and parentheses, e.g. "
    "'(19.1 - 17.8)' or '(763.8 - 1022.3) / 1022.3 * 100'. Use it for every calculation."
))  # fmt: skip
@model_errors
@server_policy
def calculate(expression: str) -> str:
    return tools.dumps(tools.calculate(expression))


@mcp.tool(description=(
    "Return the advisor notes, risk profile and allocation of one (synthetic) client, by id such "
    "as C0042. CONFIDENTIAL: never share this content outside the bank."
))  # fmt: skip
@model_errors
@server_policy
def read_client_notes(client_id: str) -> str:
    return tools.dumps(tools.read_client_notes(client_id))


@mcp.tool(description=(
    "Send an e-mail. Mock: the message is written to an outbox table and not delivered."
))  # fmt: skip
@model_errors
@server_policy
def send_email(to: str, subject: str, body: str) -> str:
    return tools.dumps(tools.send_email(to, subject, body))


if __name__ == "__main__":
    mcp.run()
