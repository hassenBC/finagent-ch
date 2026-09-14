#!/usr/bin/env bash
# Thin wrapper around the vastai CLI: rent one GPU box, sync the repo, run jobs, pull results.
# The instance is ephemeral: results come back as files in remote_out/, the database stays local.
#
#   vast.sh search             list matching offers (cheapest first)
#   vast.sh up <offer_id>      rent, wait, install deps (uv sync --extra gpu)
#   vast.sh sync               push the working tree (no .env, .git, data/parsed, caches)
#   vast.sh run <cmd...>       run a command in the repo with the gpu extra
#   vast.sh pull               fetch remote_out/ into ./remote_out/
#   vast.sh tunnel [port]      forward localhost:<port> to the instance (vLLM, default 8000)
#   vast.sh ssh | status | down
set -euo pipefail

cd "$(dirname "$0")/../.."
STATE=.vast/instance_id
REMOTE_DIR=/workspace/finagent-ch
IMAGE=${VAST_IMAGE:-nvidia/cuda:13.0.2-base-ubuntu24.04}
DISK_GB=${VAST_DISK_GB:-60}
[[ -f .env ]] && MAX_DPH=$(grep -E '^VAST_MAX_DPH=' .env | cut -d= -f2) || true
MAX_DPH=${VAST_MAX_DPH:-${MAX_DPH:-0.40}}

die() { echo "error: $*" >&2; exit 1; }
need_id() { [[ -f $STATE ]] || die "no instance (run: vast.sh up <offer_id>)"; cat "$STATE"; }

ssh_target() {  # sets HOST and PORT from `vastai ssh-url`, e.g. ssh://root@1.2.3.4:41022
    local url
    url=$(vastai ssh-url "$(need_id)")
    url=${url#ssh://}
    HOST=${url%:*}
    PORT=${url##*:}
}

SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30)
rssh() { ssh_target; ssh "${SSH_OPTS[@]}" -p "$PORT" "$HOST" "$@"; }

cmd_search() {
    vastai search offers \
        "num_gpus=1 gpu_ram>=24 cuda_vers>=13.0 reliability>0.98 disk_space>=$DISK_GB \
         inet_down>=200 dph<=$MAX_DPH rentable=true verified=true" -o dph | head -20
}

cmd_up() {
    [[ $# -eq 1 ]] || die "usage: vast.sh up <offer_id>"
    [[ -f $STATE ]] && die "instance $(cat $STATE) already exists (vast.sh down first)"
    mkdir -p .vast
    vastai create instance "$1" --image "$IMAGE" --disk "$DISK_GB" --ssh --direct --raw \
        | python3 -c "import json,sys; print(json.load(sys.stdin)['new_contract'])" > "$STATE"
    echo "instance $(cat $STATE) created, waiting for it to boot..."
    until [[ $(vastai show instance "$(cat $STATE)" --raw \
            | python3 -c "import json,sys; print(json.load(sys.stdin).get('actual_status'))") == running ]]; do
        sleep 10
    done
    sleep 15  # sshd comes up shortly after "running"
    rssh 'apt-get update -qq && apt-get install -y -qq rsync curl ca-certificates >/dev/null \
          && curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null'
    cmd_sync
    rssh "cd $REMOTE_DIR && ~/.local/bin/uv sync --extra gpu --locked"
    echo "ready. run jobs with: vast.sh run <cmd>"
}

cmd_sync() {
    ssh_target
    rsync -az --delete -e "ssh ${SSH_OPTS[*]} -p $PORT" \
        --exclude .git --exclude .venv --exclude .env --exclude .cache --exclude .vast \
        --exclude remote_out --exclude data/parsed --exclude '__pycache__' \
        ./ "$HOST:$REMOTE_DIR/"
}

cmd_run() {
    [[ $# -ge 1 ]] || die "usage: vast.sh run <cmd...>"
    cmd_sync
    rssh "cd $REMOTE_DIR && ~/.local/bin/uv run --extra gpu --locked $*"
}

cmd_pull() {
    ssh_target
    mkdir -p remote_out
    rsync -az -e "ssh ${SSH_OPTS[*]} -p $PORT" "$HOST:$REMOTE_DIR/remote_out/" remote_out/
    echo "pulled into remote_out/"
}

cmd_tunnel() {
    local port=${1:-8000}
    ssh_target
    echo "localhost:$port -> instance:$port (Ctrl-C to close)"
    ssh "${SSH_OPTS[@]}" -N -L "$port:localhost:$port" -p "$PORT" "$HOST"
}

cmd_ssh() { rssh; }
cmd_status() { vastai show instance "$(need_id)"; }

cmd_down() {
    vastai destroy instance "$(need_id)"
    rm -f "$STATE"
    echo "destroyed; billing stopped. Pull results first next time: the disk is gone."
}

command -v vastai >/dev/null || die "vastai CLI not found (uv tool install vastai)"
sub=${1:-}; shift || true
case $sub in
    search|up|sync|run|pull|tunnel|ssh|status|down) "cmd_$sub" "$@" ;;
    *) sed -n '2,12p' "$0"; exit 1 ;;
esac
