-- Phase 8.4: tracing spans. Spans from the MCP server process have no parent id (they live in
-- another process); `finagent trace` nests them under the tool call whose time window holds them.
CREATE TABLE spans (
    trace_id    UUID NOT NULL,
    span_id     UUID PRIMARY KEY,
    parent_id   UUID,
    name        TEXT NOT NULL,
    process     TEXT NOT NULL,          -- agent | mcp_server
    started_at  TIMESTAMPTZ NOT NULL,
    ms          DOUBLE PRECISION NOT NULL,
    attrs       JSONB
);
CREATE INDEX spans_trace_idx ON spans (trace_id, started_at);
