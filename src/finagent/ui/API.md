# finagent demo app — API and event contract

Backend: `src/finagent/ui/app.py` (Starlette, run with `finagent ui` → http://localhost:8000).
Frontend: `src/finagent/ui/static/` — `index.html`, `app.js`, `style.css`. Plain HTML/CSS/JS, no build
step, no framework, no CDN (works offline). Served at `/` and `/static/...`.

Purpose: a live demo of an LLM agent over Swiss bank annual reports, with a **developer view** that shows
every step as it happens so a presenter can explain the process in an interview: routing, each LLM call
(tokens, latency, cost, cache hit), each tool call, the deterministic **policy engine** decision (allow /
deny / escalate, with rule id and reason), the session's information-flow state (highest sensitivity
seen, tainted by untrusted text, side-effect count), retrieval stages inside the MCP server, and the final
cited answer.

## HTTP endpoints

| Method & path | Body / query | Response |
|---|---|---|
| `GET /api/config` | – | `{models: [{key, label, local, note}], modes: ["routed","single"], defences: ["none","prompt","policy"], presets: [{id, label, question, mode, defence, explains}], injection_demo: bool}` |
| `POST /api/runs` | `{question, mode, defence, model}` | `{run_id}`; `409 {error}` if a run is in progress (one at a time); `503 {error}` if the agent backend failed to start |
| `GET /api/runs/{run_id}/events` | – | Server-Sent Events stream (below); ends with `done`. Every message has an SSE `id` (= `seq`); reconnecting with `Last-Event-ID` replays the rest, and several subscribers each get the full log |
| `POST /api/runs/{run_id}/approval` | `{approval_id, allow: true|false}` (strict boolean) | `{ok: true}`; `409` if that approval is not pending (already answered, expired, wrong id) |
| `GET /api/page?source=efg-2025-p12` | `source` = citation id `bank-year-pN` | PNG of that PDF page (404 if unknown) |
| `GET /api/outbox` | – | `{emails: [{email_id, to, subject, body, created_at, internal}]}` newest first, max 20 (mock e-mail: nothing is sent) |
| `POST /api/demo/injection` | `{enabled: bool}` | `{enabled}` — plants / removes a synthetic poisoned page (Vontobel 2025, "Digital wealth platforms") containing a hidden instruction to e-mail client notes outside |

## SSE events

Each message: `data: {"seq": int, "t_ms": int, "kind": str, "data": {...}}` (`t_ms` = ms since run start).

| kind | data | meaning |
|---|---|---|
| `run_start` | `{question, mode, defence, model}` | |
| `route` | `{route, bank, year, tools: [..], cost_usd, static_check: {flagged, accepted, reason}}` | router decision (routed mode only); the sub-agent gets only `tools` |
| `agent_start` | `{route, model, tools: [..], system, question, max_steps, policy}` | `system` = full system prompt |
| `llm_request` | `{turn, n_messages, context_chars}` | an LLM call starts |
| `llm_response` | `{turn, text, tool_calls: [{name, args}], tokens_in, tokens_out, cost_usd, cached, latency_ms}` | |
| `policy_check` | `{tool, args, state: {max_sensitivity, tainted, side_effects}}` | state before the call |
| `policy_decision` | `{tool, decision: allow|deny|escalate, rule_id, reason, state}` | |
| `approval_needed` | `{approval_id, tool, args, rule_id, reason}` | the run is paused until `POST .../approval` with this `approval_id` (auto-deny after 5 min) |
| `approval_result` | `{approval_id, allow, timed_out}` | |
| `tool_start` | `{tool, args}` | |
| `server_span` | `{name, ms, attrs, started_at}` | spans from the MCP server process while a tool runs: `retrieve`, `retrieve.translate`, `retrieve.fts`, `retrieve.vector`, `retrieve.fusion`, `retrieve.rerank`, `llm` (translation) |
| `tool_end` | `{tool, ok, latency_ms, labels: {sensitivity, trust}, result, state}` | `result` = JSON text `{"payload": ..., "_labels": ...}` or an error message; `state` after the call |
| `invalid_call` | `{tool, reason, raw}` | invalid JSON args or a tool the sub-agent does not have |
| `error` | `{message}` | |
| `final` | `{answer, citations: ["bank-year-pN", ..], stopped_reason, route, tokens_in, tokens_out, cost_usd, latency_ms, n_calls}` | exactly once per run, including out-of-scope answers; cost includes the router |
| `done` | `{run_id}` | stream ends |

Notes for rendering
- Citations in `answer` look like `[efg-2025-p12]` → render as clickable chips that open `/api/page?source=...`.
- `labels.trust == "untrusted"` (document text) and `labels.sensitivity == "confidential"` (client notes)
  should be visually distinct; `state.tainted` / `state.max_sensitivity` drive a small "session state" badge.
- Decisions: allow = green, escalate = amber (with Approve / Deny buttons on `approval_needed`), deny = red with
  the rule id (R1_no_confidential_egress, R2_recipient_allowlist, R3_tainted_side_effect,
  R4_side_effect_budget, R5_sql_guard, R0_default_deny).
