# Journal

One line per session: what I tried, what I measured, what surprised me.

Entry dates follow the approximate development timeline in the repository history.

- 2026-09-12 — Phase 0: repo scaffold, Postgres+pgvector in Docker, cached LLM client (DeepSeek), vast.ai GPU scripts.
- 2026-09-15 — Dropped vast.ai: embeddings/reranking on the laptop GPU (RTX 3050 Ti, 4 GB), self-hosted LLMs via Ollama. torch 2.13 on CUDA 12.9 wheels (driver 555 only supports CUDA 12.5).
