
.PHONY: security regression regression-ci setup db-up db-down migrate test test-unit lint fmt llm-smoke llm-models gpu-smoke download ingest embed-small eval-retrieval eval-retrieval-grid report eval-rag judge report-rag

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

download:         ## fetch the PDFs in data/sources.csv (records sha256)
	$(RUN) python -m finagent.ingest.download

ingest:           ## parse, chunk and load every document (idempotent)
	$(RUN) python -m finagent.ingest.run

embed-small:      ## embed all chunkers with multilingual-e5-small
	$(RUN) python -m finagent.ingest.embed e5_small

eval-retrieval:   ## make eval-retrieval CONFIG=configs/retrieval/<name>.yaml
	$(RUN) python -m eval.run_retrieval $(CONFIG)

eval-retrieval-grid:  ## run every config matching GRID (default: all of configs/retrieval)
	$(RUN) python -m eval.run_retrieval --grid '$(or $(GRID),configs/retrieval/*.yaml)'

report:           ## aggregate latest runs into results/*.csv and results/retrieval.png
	$(RUN) python -m eval.report

eval-rag:         ## make eval-rag CONFIG=configs/rag/<name>.yaml [MAX_COST=0.5]; then make report-rag
	$(RUN) python -m eval.run_rag $(or $(CONFIG),configs/rag/*.yaml) --max-cost $(or $(MAX_COST),0.5)

judge:            ## make judge NAMES="rag_best_k10" [MAX_COST=0.5]
	$(RUN) python -m eval.run_judge $(NAMES) --max-cost $(or $(MAX_COST),0.5)

report-rag:       ## RAG table per dataset -> results/rag_dev.csv, results/rag_test.csv
	$(RUN) python -m eval.report_rag

security:         ## Phase 7 grid: attacks + benign x {single, routed} x {none, prompt, policy}, in parallel
	bash eval/security_parallel.sh

regression:       ## full tier: retrieval, RAG, agent, security vs thresholds + per-item diff (needs key)
	$(RUN) python -m eval.regression

regression-ci:    ## fast tier locally: load the CI fixture into a scratch DB and run it like CI does
	$(RUN) python -m eval.regression --ci

demo:             ## re-record the README demo video (docs/demo/)
	./docs/demo/build.sh
