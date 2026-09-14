# frozen_string_literal: true

require "json"
require "opentelemetry/sdk"
require "opentelemetry/exporter/otlp"

module Causcope
  module RailsRuntime
    THREAD_CONTEXT_KEY = :__causcope_rails_runtime_context

    class ConfigurationError < StandardError; end

    module CheckoutInstrumentation
      def checkout(*args, **kwargs, &block)
        context = Thread.current[THREAD_CONTEXT_KEY]
        return super unless context

        started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
        connection = super
        wait_ms = (Process.clock_gettime(Process::CLOCK_MONOTONIC) - started) * 1000.0
        span = OpenTelemetry::Trace.current_span
        if span.recording?
          span.set_attribute("causcope.pool.checkout_wait_ms", wait_ms)
          stat = respond_to?(:stat) ? self.stat : {}
          span.set_attribute("causcope.pool.checkout_size", stat[:size]) if stat[:size]
          span.set_attribute("causcope.pool.checkout_busy", stat[:busy]) if stat[:busy]
          span.set_attribute("causcope.pool.checkout_waiting", stat[:waiting]) if stat[:waiting]
        end
        context[:checkout_wait_ms] = [context.fetch(:checkout_wait_ms, 0.0), wait_ms].max
        connection
      end
    end

    class << self
      attr_reader :system_id, :revision, :pool_id, :known_code_symbols

      def install!
        return if @installed

        @system_id = required_env("CAUSCOPE_SYSTEM_ID")
        @revision = required_env("CAUSCOPE_REVISION")
        load_static_contract!
        configure_opentelemetry!
        install_active_record_checkout_instrumentation!
        install_controller_instrumentation!
        @installed = true
      end

      def trace_controller(controller)
        code_symbol = "code:#{controller.class.name}##{controller.action_name}()"
        return yield unless @known_code_symbols.include?(code_symbol)

        pool = ActiveRecord::Base.connection_pool
        before = safe_pool_stat(pool)
        tracer.in_span(
          code_symbol.delete_prefix("code:"),
          attributes: base_attributes(code_symbol, before)
        ) do |span|
          Thread.current[THREAD_CONTEXT_KEY] = { checkout_wait_ms: 0.0 }
          started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
          begin
            yield
          ensure
            duration_ms = (Process.clock_gettime(Process::CLOCK_MONOTONIC) - started) * 1000.0
            after = safe_pool_stat(pool)
            span.set_attribute("causcope.request.duration_ms", duration_ms)
            span.set_attribute("causcope.pool.post_size", after[:size]) if after[:size]
            span.set_attribute("causcope.pool.post_busy", after[:busy]) if after[:busy]
            span.set_attribute("causcope.pool.post_waiting", after[:waiting]) if after[:waiting]
            context = Thread.current[THREAD_CONTEXT_KEY]
            span.set_attribute("causcope.pool.max_checkout_wait_ms", context[:checkout_wait_ms]) if context
            Thread.current[THREAD_CONTEXT_KEY] = nil
          end
        end
      end

      def tracer
        @tracer ||= OpenTelemetry.tracer_provider.tracer("causcope.rails.runtime", "0.1")
      end

      private

      def required_env(name)
        value = ENV[name]
        raise ConfigurationError, "#{name} is required" if value.nil? || value.empty?

        value
      end

      def static_facts_path
        configured = ENV["CAUSCOPE_STATIC_FACTS"]
        return configured unless configured.nil? || configured.empty?

        root = defined?(::Rails) && ::Rails.respond_to?(:root) && ::Rails.root ? ::Rails.root.to_s : Dir.pwd
        File.join(root, ".causcope", "concrete-system-facts.json")
      end

      def load_static_contract!
        path = static_facts_path
        document = JSON.parse(File.read(path))
        unless document["kind"] == "concrete_system_facts"
          raise ConfigurationError, "#{path} is not a concrete_system_facts document"
        end
        unless document["system_id"] == @system_id
          raise ConfigurationError, "static system_id does not match CAUSCOPE_SYSTEM_ID"
        end
        unless document.dig("revision", "value") == @revision
          raise ConfigurationError, "static revision does not match CAUSCOPE_REVISION"
        end

        entities = Array(document["entities"])
        @known_code_symbols = entities.filter_map do |entity|
          entity["id"] if entity["kind"] == "code_symbol"
        end.to_set

        pools = entities.select do |entity|
          entity["kind"] == "resource_pool" && entity.dig("attributes", "technology") == "active_record"
        end
        unless pools.length == 1
          raise ConfigurationError, "portable Rails runtime currently requires exactly one ActiveRecord resource_pool"
        end
        @pool_entity = pools.first
        @pool_id = @pool_entity.fetch("id")
      rescue Errno::ENOENT => error
        raise ConfigurationError, "static facts not found: #{error.message}" from error
      rescue JSON::ParserError => error
        raise ConfigurationError, "static facts are not valid JSON: #{error.message}" from error
      end

      def configure_opentelemetry!
        if ENV["CAUSCOPE_OTEL_SYNC"] == "1"
          ENV["OTEL_TRACES_EXPORTER"] = "none"
          exporter = OpenTelemetry::Exporter::OTLP::Exporter.new
          processor = OpenTelemetry::SDK::Trace::Export::SimpleSpanProcessor.new(exporter)
          OpenTelemetry::SDK.configure do |config|
            config.service_name = ENV.fetch("OTEL_SERVICE_NAME", @system_id)
            config.add_span_processor(processor)
          end
        else
          OpenTelemetry::SDK.configure do |config|
            config.service_name = ENV.fetch("OTEL_SERVICE_NAME", @system_id)
          end
        end
      end

      def install_active_record_checkout_instrumentation!
        ActiveSupport.on_load(:active_record) do
          pool_class = ActiveRecord::ConnectionAdapters::ConnectionPool
          unless pool_class.ancestors.include?(Causcope::RailsRuntime::CheckoutInstrumentation)
            pool_class.prepend(Causcope::RailsRuntime::CheckoutInstrumentation)
          end
        end
      end

      def install_controller_instrumentation!
        ActiveSupport.on_load(:action_controller) do
          around_action do |controller, action|
            Causcope::RailsRuntime.trace_controller(controller) { action.call }
          end
        end
      end

      def base_attributes(code_symbol, stat)
        attributes = {
          "causcope.code_symbol" => code_symbol,
          "causcope.system_id" => @system_id,
          "causcope.revision" => @revision,
          "causcope.pool_id" => @pool_id,
          "causcope.pool.technology" => "active_record"
        }
        configured_capacity = @pool_entity.dig("attributes", "configured_capacity")
        attributes["causcope.pool.configured_capacity"] = configured_capacity if configured_capacity
        attributes["causcope.pool.pre_size"] = stat[:size] if stat[:size]
        attributes["causcope.pool.pre_busy"] = stat[:busy] if stat[:busy]
        attributes["causcope.pool.pre_waiting"] = stat[:waiting] if stat[:waiting]
        attributes
      end

      def safe_pool_stat(pool)
        pool.stat
      rescue StandardError
        {}
      end
    end
  end
end

require "set"
Causcope::RailsRuntime.install!
