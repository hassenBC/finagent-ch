#!/usr/bin/env bash
# Re-record and re-assemble the demo video. Needs: Docker (db container), a populated database, .env with
# the LLM key (never shown on screen), Go (for vhs) and Python with playwright. Run: ./docs/demo/build.sh
set -euo pipefail
cd "$(dirname "$0")"
D=$PWD; ROOT=$(cd ../.. && pwd); PORT=8765
./bootstrap.sh
export FINAGENT_ROOT=$ROOT PATH="$D/.tools/bin:$PATH" LD_LIBRARY_PATH="$D/.tools/lib:${LD_LIBRARY_PATH:-}"
mkdir -p build; rm -rf build/raw build/*.webm build/*.mp4

DOCKER=docker; command -v docker >/dev/null && docker info >/dev/null 2>&1 || DOCKER=docker.exe
(cd "$ROOT" && $DOCKER compose up -d --wait db)

# 1. web UI: start a server, warm every scenario (model load + cached LLM calls), clear the mock outbox, record
(cd "$ROOT" && uv run finagent ui --port $PORT >"$D/build/ui.log" 2>&1) & UI=$!
trap 'kill $UI 2>/dev/null || true; pkill -f "finagent ui --port $PORT" 2>/dev/null || true' EXIT
for _ in $(seq 60); do curl -sf localhost:$PORT/api/config >/dev/null && break; sleep 1; done
python3 ui_scenes.py warm http://localhost:$PORT
(cd "$ROOT" && uv run python docs/demo/clear_outbox.py)
python3 ui_scenes.py record http://localhost:$PORT

# 2. terminal scenes
vhs tapes/setup.tape >/dev/null
vhs tapes/ask.tape >/dev/null

# 3. edit and export demo.mp4, demo.gif, poster.png
python3 edit.py
