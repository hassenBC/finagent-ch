CREATE TABLE eval_runs (
    run_id      UUID PRIMARY KEY,
    kind        TEXT,
    config      JSONB,
    git_sha     TEXT,
    dataset     TEXT,
    started_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE eval_results (
    run_id      UUID REFERENCES eval_runs,
    item_id     TEXT,
    metrics     JSONB,
    output      JSONB,
    PRIMARY KEY (run_id, item_id)
);

CREATE TABLE traces (
    trace_id    UUID PRIMARY KEY,
    query       TEXT,
    started_at  TIMESTAMPTZ,
    total_ms    INT,
    tokens_in   INT,
    tokens_out  INT,
    cost_usd    NUMERIC(10,6)
);

CREATE TABLE tool_calls (
    trace_id    UUID REFERENCES traces,
    step        INT,
    tool        TEXT,
    args        JSONB,
    decision    TEXT,
    rule_id     TEXT,
    reason      TEXT,
    latency_ms  INT
);
