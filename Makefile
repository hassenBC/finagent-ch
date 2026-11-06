.PHONY: setup db-up db-down migrate test test-unit lint fmt llm-smoke llm-models gpu-smoke

UV  ?= uv
RUN := $(UV) run

setup:            ## install deps (incl. CUDA torch), start Postgres, apply migrations
	$(UV) sync --extra gpu
	$(MAKE) db-up
	$(MAKE) migrate

db-up:
	docker compose up -d --wait db

db-down:
	docker compose down

migrate:
	$(RUN) python -m finagent.db

test:             ## unit + integration (integration skips if Postgres is down)
	$(RUN) pytest -q

test-unit:
	$(RUN) pytest -q tests/unit

lint:
	$(RUN) ruff check .
	$(RUN) ruff format --check .

fmt:
	$(RUN) ruff format .
	$(RUN) ruff check --fix .

llm-smoke:        ## run twice: the second call must print cached=True cost_usd=0
	$(RUN) python -m finagent.llm.client "Say hi"

llm-models:       ## list model ids served by the default provider
	$(RUN) python -m finagent.llm.client --list-models

gpu-smoke:        ## embed 3 sentences on CUDA
	$(RUN) python scripts/gpu_smoke.py
