#!/usr/bin/env ruby

require "json"
require "net/http"
require "pg"
require "time"
require "uri"

APP_URL = ENV.fetch("APP_URL", "http://127.0.0.1:4567")
HOLD_MS = Integer(ENV.fetch("HOLD_MS", "2000"))
SYSTEM_ID = ENV.fetch("CAUSCOPE_SYSTEM_ID")
REVISION = ENV.fetch("CAUSCOPE_REVISION")
REPOSITORY = ENV.fetch("CAUSCOPE_REPOSITORY")
INCIDENT_ID = ENV.fetch("CAUSCOPE_INCIDENT_ID")
POOL_ID = "pool:active_record.primary"
DEPENDENCY_ID = "dependency:postgresql"


def monotonic
  Process.clock_gettime(Process::CLOCK_MONOTONIC)
end

def elapsed_ms(started)
  (monotonic - started) * 1000.0
end

def get_json(path)
  uri = URI.join(APP_URL, path)
  response = Net::HTTP.get_response(uri)
  raise "#{uri} returned #{response.code}: #{response.body}" unless response.is_a?(Net::HTTPSuccess)

  JSON.parse(response.body)
end

def wait_until(timeout: 5.0)
  deadline = monotonic + timeout
  loop do
    value = yield
    return value if value
    raise "timed out waiting for Rails pool state" if monotonic >= deadline

    sleep 0.02
  end
end

def direct_database_control
  started = monotonic
  connection = PG.connect(
    host: ENV.fetch("DB_HOST", "127.0.0.1"),
    port: ENV.fetch("DB_PORT", "5432"),
    user: ENV.fetch("DB_USER", "causcope"),
    password: ENV.fetch("DB_PASSWORD", "causcope"),
    dbname: ENV.fetch("DB_NAME", "causcope"),
    connect_timeout: 5
  )
  query_started = monotonic
  backend_id = connection.exec("SELECT pg_backend_pid() AS backend_id").first.fetch("backend_id")
  query_latency_ms = elapsed_ms(query_started)
  total_latency_ms = elapsed_ms(started)
  connection.close
  {
    "dependency_id" => DEPENDENCY_ID,
    "reachable" => true,
    "total_latency_ms" => total_latency_ms,
    "query_latency_ms" => query_latency_ms,
    "backend_id" => backend_id
  }
rescue StandardError => error
  {
    "dependency_id" => DEPENDENCY_ID,
    "reachable" => false,
    "total_latency_ms" => elapsed_ms(started),
    "query_latency_ms" => 0.0,
    "backend_id" => "unavailable:#{error.class}"
  }
end

def sample(document)
  {
    "checkout_wait_ms" => document.fetch("checkout_wait_ms"),
    "request_latency_ms" => document.fetch("request_latency_ms"),
    "dependency_latency_ms" => document.fetch("dependency_latency_ms")
  }
end

# Warm the framework and establish the first database connection before measuring baseline.
get_json("/work")
baseline_response = get_json("/work")
baseline = sample(baseline_response)

holder = Thread.new { get_json("/hold?ms=#{HOLD_MS}") }
wait_until do
  status = get_json("/status")
  status if status.fetch("busy") >= status.fetch("size")
end

measured_thread = Thread.new { get_json("/work") }
saturated = wait_until do
  status = get_json("/status")
  status if status.fetch("busy") >= status.fetch("size") && status.fetch("waiting") >= 1
end

control = direct_database_control
measured = measured_thread.value
holder.value
sleep 0.05
recovery_response = get_json("/work")
recovery = sample(recovery_response)

wait_delta = measured.fetch("checkout_wait_ms") - baseline.fetch("checkout_wait_ms")
request_delta = measured.fetch("request_latency_ms") - baseline.fetch("request_latency_ms")
query_limit = [baseline.fetch("dependency_latency_ms") * 5.0, 50.0].max
explanation_tolerance = [request_delta.abs * 0.25, 120.0].max

assertions = {
  "application_pool_was_at_capacity" => saturated.fetch("busy") == saturated.fetch("size") && saturated.fetch("waiting") >= 1,
  "pool_checkout_wait_increased" => wait_delta >= 200.0,
  "request_latency_increased" => request_delta >= 200.0,
  "query_latency_stayed_near_baseline" => measured.fetch("dependency_latency_ms") <= query_limit,
  "database_still_accepts_direct_connections" => control.fetch("reachable"),
  "checkout_wait_explains_request_delta" => (request_delta - wait_delta).abs <= explanation_tolerance,
  "recovery_checkout_wait_returned_to_baseline" => recovery.fetch("checkout_wait_ms") <= [baseline.fetch("checkout_wait_ms") + 50.0, 100.0].max,
  "recovery_request_latency_returned_to_baseline" => recovery.fetch("request_latency_ms") <= baseline.fetch("request_latency_ms") + 150.0
}

evidence = {
  "schema_version" => "0.1",
  "kind" => "resource_pool_runtime_evidence",
  "system_id" => SYSTEM_ID,
  "revision" => { "type" => "git", "value" => REVISION, "repository" => REPOSITORY },
  "incident_id" => INCIDENT_ID,
  "observed_at" => Time.now.utc.iso8601(6),
  "pool" => {
    "id" => POOL_ID,
    "technology" => "active_record",
    "configured_capacity" => Integer(ENV.fetch("DB_POOL")),
    "observed_capacity" => saturated.fetch("size"),
    "busy" => saturated.fetch("busy"),
    "utilization" => saturated.fetch("busy").to_f / saturated.fetch("size")
  },
  "request" => {
    "code_symbol" => measured.fetch("code_symbol"),
    "trace_id" => measured.fetch("trace_id"),
    "span_id" => measured.fetch("span_id"),
    "checkout_wait_ms" => measured.fetch("checkout_wait_ms"),
    "request_latency_ms" => measured.fetch("request_latency_ms"),
    "dependency_latency_ms" => measured.fetch("dependency_latency_ms"),
    "dependency_backend_id" => measured.fetch("dependency_backend_id")
  },
  "dependency_control" => control,
  "baseline" => baseline,
  "recovery" => recovery,
  "assertions" => assertions,
  "source" => {
    "type" => "probe",
    "name" => "rails_active_record_connection_pool",
    "uri" => "live:rails-active-record-connection-pool"
  },
  "limitations" => [
    "ActiveRecord pool statistics are point-in-time observations from the application process.",
    "The independent PostgreSQL control proves only that a separate session was admitted during the measured saturation window.",
    "Trace and span identity come from the portable Rails runtime span; the OTLP payload is exported independently by the OpenTelemetry OTLP exporter."
  ]
}

puts JSON.generate(evidence)
