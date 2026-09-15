# finagent-ch

[![ci](https://github.com/hassenBC/finagent-ch/actions/workflows/ci.yml/badge.svg)](https://github.com/hassenBC/finagent-ch/actions/workflows/ci.yml)

A measured, permission-aware LLM agent over Swiss financial documents.

## Quick start

```bash
cp .env.example .env   # add DEEPSEEK_API_KEY
make setup             # uv sync, Postgres+pgvector in Docker, migrations
make test
make llm-smoke         # run twice: second call is cached and free
```

Embeddings, reranking and parsing run on a local CUDA GPU (`uv sync --extra gpu`, check with `make gpu-smoke`);
without one, use `uv sync --extra cpu`.
