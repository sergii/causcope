#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
WORKSPACE=${CAUSCOPE_WORKSPACE:-$ROOT/.causcope-canonical-demo}
APP_ROOT=$ROOT/lab/rails-connection-pool
APP_URL=${APP_URL:-http://127.0.0.1:4567}
OTLP_ENDPOINT=${OTEL_EXPORTER_OTLP_TRACES_ENDPOINT:-http://127.0.0.1:4318/v1/traces}
export BUNDLE_GEMFILE=${BUNDLE_GEMFILE:-$APP_ROOT/Gemfile}
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
export CAUSCOPE_OTEL_SYNC=${CAUSCOPE_OTEL_SYNC:-1}
export OTEL_SERVICE_NAME=${OTEL_SERVICE_NAME:-causcope-rails-connection-pool}
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=$OTLP_ENDPOINT
STATIC_FACTS="$WORKSPACE/concrete-system-facts.json"
POOL_EVIDENCE="$WORKSPACE/resource-pool-runtime-evidence.json"
OTLP_LOG="$WORKSPACE/otlp.log"
PUMA_LOG="$WORKSPACE/puma.log"
rm -rf "$WORKSPACE"
mkdir -p "$WORKSPACE"
PUMA_PID=""
OTLP_PID=""
cleanup() {
  if [ -n "$PUMA_PID" ]; then kill "$PUMA_PID" 2>/dev/null || true; fi
  if [ -n "$OTLP_PID" ]; then kill "$OTLP_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT

printf '\n[1/6] Bootstrapping canonical system state\n'
./bin/causcope bootstrap "$APP_ROOT" --workspace "$WORKSPACE" --environment production --env-file deployment.yml --system-id "$CAUSCOPE_SYSTEM_ID" --revision "$CAUSCOPE_REVISION" --repository "$CAUSCOPE_REPOSITORY" --database "$DB_NAME" --database-url-env CAUSCOPE_DEMO_DATABASE_URL

printf '\n[2/6] Starting one Investigation from the product front door\n'
./bin/causcope why "checkout is slow" --workspace "$WORKSPACE" >/dev/null
CAUSCOPE_INCIDENT_ID=$(python - "$WORKSPACE/incident-context.yaml" <<'PY'
import sys
from pathlib import Path
import yaml
context = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(context["incident_id"])
PY
)
export CAUSCOPE_INCIDENT_ID
RUNTIME_FACTS="$WORKSPACE/runtime/$CAUSCOPE_INCIDENT_ID.json"
export CAUSCOPE_STATIC_FACTS="$STATIC_FACTS"
printf '  Investigation: %s\n' "$CAUSCOPE_INCIDENT_ID"

printf '\n[3/6] Observing the real Rails request and exact ActiveRecord pool\n'
python scripts/otlp_concrete_receiver.py --static-facts "$STATIC_FACTS" --incident-id "$CAUSCOPE_INCIDENT_ID" --snapshot "$RUNTIME_FACTS" --source-uri otlp:http:rails-active-record >"$OTLP_LOG" 2>&1 &
OTLP_PID=$!
for _ in $(seq 1 30); do
  if curl --fail --silent http://127.0.0.1:4318/health >/dev/null; then break; fi
  sleep 1
done
curl --fail --silent http://127.0.0.1:4318/health >/dev/null || { cat "$OTLP_LOG"; exit 1; }
(
  cd "$APP_ROOT"
  bundle exec puma -C config/puma.rb
) >"$PUMA_LOG" 2>&1 &
PUMA_PID=$!
for _ in $(seq 1 60); do
  if curl --fail --silent "$APP_URL/health" >/dev/null; then break; fi
  sleep 1
done
curl --fail --silent "$APP_URL/health" >/dev/null || { cat "$PUMA_LOG"; exit 1; }
APP_URL="$APP_URL" HOLD_MS=${HOLD_MS:-2000} bundle exec ruby lab/rails-connection-pool/concrete_probe.rb >"$POOL_EVIDENCE"
for _ in $(seq 1 30); do
  if [ -s "$RUNTIME_FACTS" ]; then break; fi
  sleep 1
done
[ -s "$RUNTIME_FACTS" ] || { cat "$OTLP_LOG"; exit 1; }

printf '\n[4/6] Seeding canonical diagnosis revision 1\n'
./bin/causcope runtime seed "$APP_ROOT" --workspace "$WORKSPACE" --runtime-facts "$RUNTIME_FACTS" --request-latency-threshold-ms 200 --pool-wait-threshold-ms 50

printf '\n[5/6] Letting Causcope select and execute the current semantic probe\n\n'
./bin/causcope why "checkout is slow" --workspace "$WORKSPACE" --require-confirmed

printf '\n[6/6] Canonical autonomous product proof complete\n'
printf '  workspace: %s\n' "$WORKSPACE"
printf '  authority: diagnosis.json + runtime-evidence.json -> causal_verification\n'
printf '  manual acquisition flag used: no\n'
printf '  manual resource-pool import used: no\n'
printf '  legacy X-Ray artifact flags used: no\n'
