#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BASE_URL="${MIROFISH_CANARY_BASE_URL:-http://127.0.0.1:5001}"
MANIFEST="${BETTAFISH_HANDOFF_MANIFEST:-}"
STATE_PATH="${MIROFISH_CANARY_STATE_PATH:-.hermes/runs/preintegration-handoff/state.json}"
LOG_FILE="${MIROFISH_CANARY_LOG_FILE:-.hermes/runs/preintegration-handoff/events.jsonl}"
PYTHON_BIN="${MIROFISH_CANARY_PYTHON:-backend/.venv/bin/python}"

printf '== MiroFish BettaFish-handoff pre-integration canary ==\n'

if [[ -z "$MANIFEST" ]]; then
  printf 'FAIL BETTAFISH_HANDOFF_MANIFEST is required\n' >&2
  exit 1
fi
if [[ ! -f "$MANIFEST" ]]; then
  printf 'FAIL manifest not found: %s\n' "$MANIFEST" >&2
  exit 1
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  printf 'FAIL python env not found: %s\n' "$PYTHON_BIN" >&2
  exit 1
fi

docker compose up -d
RUN_GRAPHITI_NATIVE_SMOKE="${RUN_GRAPHITI_NATIVE_SMOKE:-1}" RUN_MINI_BUILD=0 bash scripts/local-smoke.sh

"$PYTHON_BIN" scripts/bettafish-single-e2e-runner.py \
  --base-url "$BASE_URL" \
  --bettafish-manifest "$MANIFEST" \
  --state-path "$STATE_PATH" \
  --log-file "$LOG_FILE" \
  --profile-count "${MIROFISH_CANARY_PROFILE_COUNT:-2}" \
  --max-rounds "${MIROFISH_CANARY_MAX_ROUNDS:-1}" \
  --force-graph \
  --force-prepare \
  --force-start \
  --force-report

printf 'PASS MiroFish handoff canary complete\n'
printf 'state=%s\nlog=%s\n' "$STATE_PATH" "$LOG_FILE"
