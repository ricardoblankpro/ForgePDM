#!/usr/bin/env bash
# Launch the local web workspace using the existing project data.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
export PATH="$HOME/.local/bin:$PATH"
state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/forgepdm"
mkdir -p "$state_dir"
exec 9>"$state_dir/web-launch.lock"
flock 9
url=http://127.0.0.1:8000
ready() { curl --silent --fail --max-time 2 "$url/health" >/dev/null; }
if ! ready; then
    nohup uv run uvicorn forgepdm.main:app --app-dir src --host 127.0.0.1 --port 8000 \
        >>"$state_dir/web-server.log" 2>&1 </dev/null 9>&- &
    for ((attempt=0; attempt<60; attempt++)); do
        if ready; then break; fi
        sleep 0.5
    done
fi
if ! ready; then
    message="ForgePDM could not start. See $state_dir/web-server.log"
    command -v notify-send >/dev/null && notify-send 'ForgePDM' "$message" || true
    echo "$message" >&2
    exit 1
fi
flock -u 9
exec 9>&-
exec xdg-open "$url/app/"
