class PoolController < ApplicationController
  CODE_SYMBOL = "code:PoolController#work()"
  TRACER = OpenTelemetry.tracer_provider.tracer("causcope.rails.connection_pool", "0.1")

  def health
    render json: { ok: true, pool_size: pool.stat.fetch(:size) }
  end

  def status
    render json: pool.stat.transform_keys(&:to_s)
  end

  def hold
    hold_ms = Integer(params.fetch(:ms, "2000"))
    backend_id = nil

    pool.with_connection do |connection|
      backend_id = connection.select_value("SELECT pg_backend_pid()").to_s
      sleep(hold_ms / 1000.0)
    end

    render json: { held_ms: hold_ms, dependency_backend_id: backend_id }
  end

  def work
    wall_start_ns = Process.clock_gettime(Process::CLOCK_REALTIME, :nanosecond)

    TRACER.in_span(
      "PoolController#work",
      attributes: {
        "causcope.code_symbol" => CODE_SYMBOL,
        "causcope.system_id" => ENV.fetch("CAUSCOPE_SYSTEM_ID"),
        "causcope.revision" => ENV.fetch("CAUSCOPE_REVISION")
      }
    ) do |span|
      request_started = monotonic
      checkout_started = monotonic
      checkout_wait_ms = nil
      dependency_latency_ms = nil
      dependency_backend_id = nil

      pool.with_connection do |connection|
        checkout_wait_ms = elapsed_ms(checkout_started)
        query_started = monotonic
        dependency_backend_id = connection.select_value("SELECT pg_backend_pid()").to_s
        dependency_latency_ms = elapsed_ms(query_started)
      end

      request_latency_ms = elapsed_ms(request_started)
      wall_end_ns = Process.clock_gettime(Process::CLOCK_REALTIME, :nanosecond)

      render json: {
        code_symbol: CODE_SYMBOL,
        trace_id: span.context.hex_trace_id,
        span_id: span.context.hex_span_id,
        start_time_unix_nano: wall_start_ns.to_s,
        end_time_unix_nano: wall_end_ns.to_s,
        checkout_wait_ms: checkout_wait_ms,
        request_latency_ms: request_latency_ms,
        dependency_latency_ms: dependency_latency_ms,
        dependency_backend_id: dependency_backend_id
      }
    end
  end

  private

  def pool
    ActiveRecord::Base.connection_pool
  end

  def monotonic
    Process.clock_gettime(Process::CLOCK_MONOTONIC)
  end

  def elapsed_ms(started)
    (monotonic - started) * 1000.0
  end
end
