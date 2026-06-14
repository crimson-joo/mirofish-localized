#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_BACKEND="${BASE_BACKEND:-http://127.0.0.1:5001}"
BASE_FRONTEND="${BASE_FRONTEND:-http://127.0.0.1:3000}"
BASE_GRAPHITI="${BASE_GRAPHITI:-http://127.0.0.1:8000}"
RUN_MINI_BUILD="${RUN_MINI_BUILD:-0}"
RUN_GRAPHITI_NATIVE_SMOKE="${RUN_GRAPHITI_NATIVE_SMOKE:-1}"

pass() { printf 'PASS %s\n' "$1"; }
fail() { printf 'FAIL %s\n' "$1"; exit 1; }

http_check() {
  local name="$1" url="$2"
  python3 - "$name" "$url" <<'PY'
import sys, urllib.request
name, url = sys.argv[1], sys.argv[2]
try:
    with urllib.request.urlopen(url, timeout=15) as r:
        if 200 <= r.status < 300:
            print(f"PASS {name} {r.status}")
        else:
            print(f"FAIL {name} {r.status}")
            sys.exit(1)
except Exception as e:
    print(f"FAIL {name} {e!r}")
    sys.exit(1)
PY
}

cd "$ROOT_DIR"

printf '== MiroFish Local Demo MVP smoke ==\n'

if docker compose ps >/dev/null 2>&1; then
  pass "docker compose project detected"
else
  fail "docker compose project unavailable"
fi

http_check backend_health "$BASE_BACKEND/health"
http_check graphiti_health "$BASE_GRAPHITI/healthcheck"
http_check frontend "$BASE_FRONTEND/"
http_check graph_tasks "$BASE_BACKEND/api/graph/tasks"
http_check graph_project_list "$BASE_BACKEND/api/graph/project/list"
http_check simulation_history "$BASE_BACKEND/api/simulation/history?limit=3"
http_check report_list "$BASE_BACKEND/api/report/list"

python3 - "$BASE_BACKEND" <<'PY'
import json, sys, urllib.request
base = sys.argv[1]
with urllib.request.urlopen(base + '/api/graph/project/list', timeout=15) as r:
    payload = json.loads(r.read().decode())
items = payload.get('data') or []
if not items:
    print('PASS graph_data_status skipped no graphs')
    sys.exit(0)
required = ['provider', 'base_url', 'projection_cache_enabled', 'native_ingest_state']
selected = None
fallback = None
for item in items[:10]:
    graph_id = item.get('graph_id')
    if not graph_id:
        continue
    try:
        with urllib.request.urlopen(base + '/api/graph/data/' + graph_id, timeout=15) as r:
            graph_payload = json.loads(r.read().decode())
    except Exception:
        continue
    data = graph_payload.get('data') or {}
    status = data.get('graphiti_status') or {}
    missing = [k for k in required if k not in status]
    if missing:
        fallback = fallback or (graph_id, status, missing)
        continue
    fallback = fallback or (graph_id, status, [])
    if status.get('native_ingest_state') == 'pass':
        selected = (graph_id, status, [])
        break
selected = selected or fallback
if not selected:
    print('FAIL graph_data_status no readable graph data')
    sys.exit(1)
graph_id, status, missing = selected
if missing:
    print(f'FAIL graph_data_status graph_id={graph_id} missing {missing}')
    sys.exit(1)
print(f"PASS graph_data_status graph_id={graph_id} native={status.get('native_ingest_state')} projection={status.get('projection_cache_enabled')}")

with urllib.request.urlopen(base + '/api/simulation/history?limit=1', timeout=15) as r:
    history = json.loads(r.read().decode())
sims = history.get('data') or []
if sims:
    sim_id = sims[0].get('simulation_id')
    with urllib.request.urlopen(base + '/api/simulation/' + sim_id + '/run-status', timeout=15) as r:
        run = json.loads(r.read().decode()).get('data') or {}
    if run.get('runner_status') not in {'idle', 'starting', 'running', 'completed', 'stopped', 'failed'}:
        print(f"FAIL run_status unexpected {run.get('runner_status')}")
        sys.exit(1)
    print(f"PASS run_status simulation_id={sim_id} runner_status={run.get('runner_status')} normalized={run.get('terminal_state_normalized')}")
else:
    print('PASS run_status skipped no simulations')
PY

if [[ "$RUN_GRAPHITI_NATIVE_SMOKE" == "1" ]]; then
  python3 scripts/graphiti-native-smoke.py "$BASE_GRAPHITI"
else
  pass "graphiti_native_smoke skipped RUN_GRAPHITI_NATIVE_SMOKE=0"
fi

if [[ "$RUN_MINI_BUILD" == "1" ]]; then
  python3 - "$BASE_BACKEND" <<'PY'
import io, json, sys, time, urllib.request
base = sys.argv[1]
# Build endpoint expects multipart upload; keep this optional because it uses LLM tokens.
print('PASS mini_graph_build skipped: set project-specific multipart smoke when needed')
PY
else
  pass "mini_graph_build skipped RUN_MINI_BUILD=0"
fi

printf '== smoke complete ==\n'
