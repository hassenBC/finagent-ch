.PHONY: setup db-up db-down migrate test test-unit lint fmt llm-smoke llm-models \
        vast-search vast-up vast-sync vast-smoke vast-pull vast-tunnel vast-down

UV  ?= uv
RUN := $(UV) run
VAST := scripts/vast/vast.sh

setup:            ## install deps, start Postgres, apply migrations
	$(UV) sync
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

# --- vast.ai GPU (embeddings, reranking, vLLM). See scripts/vast/vast.sh ---
vast-search:
	$(VAST) search

vast-up:          ## make vast-up OFFER=<id>
	$(VAST) up $(OFFER)

vast-sync:
	$(VAST) sync

vast-smoke:
	$(VAST) run python scripts/vast/gpu_smoke.py

vast-pull:
	$(VAST) pull

vast-tunnel:
	$(VAST) tunnel 8000

vast-down:        ## destroy the instance (stops billing)
	$(VAST) down
