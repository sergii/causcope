#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

WORKSPACE=${CAUSCOPE_WORKSPACE:-$ROOT/.causcope-demo}
APP_URL=${APP_URL:-http://127.0.0.1:4567}
OTLP_ENDPOINT=${OTEL_EXPORTER_OTLP_TRACES_ENDPOINT:-http://127.0.0.1:4318/v1/traces}

export BUNDLE_GEMFILE=${BUNDLE_GEMFILE:-$ROOT/lab/rails-connection-pool/Gemfile}
export RAILS_ENV=${RAILS_ENV:-production}
export RAILS_MAX_THREADS=${RAILS_MAX_THREADS:-5}
export PORT=${PORT:-4567}
export DB_HOST=${DB_HOST:-127.0.0.1}
export DB_PORT=${DB_PORT:-5432}
export DB_USER=${DB_USER:-causcope}
export DB_PASSWORD=${DB_PASSWORD:-causcope}
export DB_NAME=${DB_NAME:-causcope}
export DB_POOL=${DB_POOL:-1}
export DB_CHECKOUT_TIMEOUT=${DB_CHECKOUT_TIMEOUT:-5}
export CAUSCOPE_SYSTEM_ID=${CAUSCOPE_SYSTEM_ID:-rails-connection-pool-app}
export CAUSCOPE_REVISION=${CAUSCOPE_REVISION:-$(git rev-parse HEAD 2>/dev/null || printf 'local-demo')}
export CAUSCOPE_REPOSITORY=${CAUSCOPE_REPOSITORY:-https://github.com/sergii/causcope}
export CAUSCOPE_INCIDENT_ID=${CAUSCOPE_INCIDENT_ID:-INC-D3-1-RAILS-DEMO}
export CAUSCOPE_OTEL_SYNC=${CAUSCOPE_OTEL_SYNC:-1}
export OTEL_SERVICE_NAME=${OTEL_SERVICE_NAME:-causcope-rails-connection-pool}
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=$OTLP_ENDPOINT
export CAUSCOPE_STATIC_FACTS="$WORKSPACE/concrete-system-facts.json"

RUNTIME_FACTS="$WORKSPACE/concrete-runtime-facts.json"
POOL_EVIDENCE="$WORKSPACE/resource-pool-runtime-evidence.json"
OTLP_LOG="$WORKSPACE/otlp.log"
PUMA_LOG="$WORKSPACE/puma.log"

rm -rf "$WORKSPACE"
mkdir -p "$WORKSPACE"

PUMA_PID=""
OTLP_PID=""
cleanup() {
  if [ -n "$PUMA_PID" ]; then
    kill "$PUMA_PID" 2>/dev/null || true
  fi
  if [ -n "$OTLP_PID" ]; then
    kill "$OTLP_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

printf '\n[1/5] Discovering the concrete Rails system\n'
./bin/causcope scan lab/rails-connection-pool \
  --provider rails \
  --environment production \
  --env-file deployment.yml \
  --system-id "$CAUSCOPE_SYSTEM_ID" \
  --revision "$CAUSCOPE_REVISION" \
  --repository "$CAUSCOPE_REPOSITORY" \
  --output "$CAUSCOPE_STATIC_FACTS"

printf '\n[2/5] Starting Causcope OTLP receiver and Rails app\n'
python scripts/otlp_concrete_receiver.py \
  --static-facts "$CAUSCOPE_STATIC_FACTS" \
  --incident-id "$CAUSCOPE_INCIDENT_ID" \
  --snapshot "$RUNTIME_FACTS" \
  --source-uri otlp:http:rails-active-record \
  >"$OTLP_LOG" 2>&1 &
OTLP_PID=$!

for _ in $(seq 1 30); do
  if curl --fail --silent http://127.0.0.1:4318/health >/dev/null; then
    break
  fi
  sleep 1
done
curl --fail --silent http://127.0.0.1:4318/health >/dev/null || {
  cat "$OTLP_LOG"
  exit 1
}

(
  cd lab/rails-connection-pool
  bundle exec puma -C config/puma.rb
) >"$PUMA_LOG" 2>&1 &
PUMA_PID=$!

for _ in $(seq 1 60); do
  if curl --fail --silent "$APP_URL/health" >/dev/null; then
    break
  fi
  sleep 1
done
curl --fail --silent "$APP_URL/health" >/dev/null || {
  cat "$PUMA_LOG"
  exit 1
}

printf '\n[3/5] Reproducing a real ActiveRecord pool-contention incident\n'
APP_URL="$APP_URL" HOLD_MS=${HOLD_MS:-2000} \
  bundle exec ruby lab/rails-connection-pool/concrete_probe.rb >"$POOL_EVIDENCE"

for _ in $(seq 1 30); do
  if [ -s "$RUNTIME_FACTS" ]; then
    break
  fi
  sleep 1
done
[ -s "$RUNTIME_FACTS" ] || {
  cat "$OTLP_LOG"
  exit 1
}

printf '\n[4/5] Workspace now contains the real proof artifacts\n'
printf '  %s\n' "$CAUSCOPE_STATIC_FACTS" "$RUNTIME_FACTS" "$POOL_EVIDENCE"

printf '\n[5/5] Asking Causcope why the request is slow\n\n'
./bin/causcope why "checkout is slow" \
  --workspace "$WORKSPACE" \
  --require-confirmed
