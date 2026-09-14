# frozen_string_literal: true

require "json"
require "set"
require "opentelemetry/sdk"
require "opentelemetry/exporter/otlp"

module Causcope
  module RailsRuntime
    THREAD_CONTEXT_KEY = :__causcope_rails_runtime_context
    POOL_CHECKOUT_EVENT = "causcope.pool.checkout"

    class ConfigurationError < StandardError; end

    # SimpleSpanProcessor may invoke one exporter concurrently when request spans
    # finish on different application threads. Sync mode exists for deterministic
    # local proofs, so serialize that exporter explicitly instead of relying on the
    # HTTP exporter's connection object to be safe for concurrent use.
    class SynchronizedExporter
      def initialize(exporter)
        @exporter = exporter
        @mutex = Mutex.new
      end

      def export(span_data, timeout: nil)
        @mutex.synchronize { @exporter.export(span_data, timeout: timeout) }
      end

      def force_flush(timeout: nil)
        @mutex.synchronize { @exporter.force_flush(timeout: timeout) }
      end

      def shutdown(timeout: nil)
        @mutex.synchronize { @exporter.shutdown(timeout: timeout) }
      end
    end

    module CheckoutInstrumentation
      def checkout(*args, **kwargs, &block)
        context = Thread.current[THREAD_CONTEXT_KEY]
        return super unless context

        started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
        connection = super
        wait_ms = (Process.clock_gettime(Process::CLOCK_MONOTONIC) - started) * 1000.0
        stat = respond_to?(:stat) ? self.stat : {}
        span = OpenTelemetry::Trace.current_span
        binding = Causcope::RailsRuntime.pool_binding(self)

        if span.recording?
          if binding
            span.add_event(
              POOL_CHECKOUT_EVENT,
              attributes: Causcope::RailsRuntime.pool_checkout_event_attributes(binding, wait_ms, stat)
            )
            context[:pool_ids] << binding.fetch(:entity).fetch("id")

            # Preserve the original single-pool transport attributes for existing
            # consumers. In multi-pool applications a scalar pool_id would be
            # ambiguous, so exact identity lives only on repeated checkout events.
            if Causcope::RailsRuntime.single_pool_contract?
              span.set_attribute("causcope.pool_id", binding.fetch(:entity).fetch("id"))
              span.set_attribute("causcope.pool.checkout_wait_ms", wait_ms)
              span.set_attribute("causcope.pool.checkout_size", stat[:size]) if stat[:size]
              span.set_attribute("causcope.pool.checkout_busy", stat[:busy]) if stat[:busy]
              span.set_attribute("causcope.pool.checkout_waiting", stat[:waiting]) if stat[:waiting]
            end
          else
            context[:unresolved_pool_checkouts] += 1
          end
        end

        context[:checkout_wait_ms] = [context.fetch(:checkout_wait_ms, 0.0), wait_ms].max
        connection
      end
    end

    class << self
      attr_reader :system_id, :revision, :known_code_symbols, :pool_entities

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

        legacy_pool = single_pool_contract? ? ActiveRecord::Base.connection_pool : nil
        legacy_binding = legacy_pool ? pool_binding(legacy_pool) : nil
        before = legacy_pool ? safe_pool_stat(legacy_pool) : {}

        tracer.in_span(
          code_symbol.delete_prefix("code:"),
          attributes: base_attributes(code_symbol, before, legacy_binding)
        ) do |span|
          previous_context = Thread.current[THREAD_CONTEXT_KEY]
          Thread.current[THREAD_CONTEXT_KEY] = {
            checkout_wait_ms: 0.0,
            unresolved_pool_checkouts: 0,
            pool_ids: Set.new
          }
          started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
          begin
            yield
          ensure
            duration_ms = (Process.clock_gettime(Process::CLOCK_MONOTONIC) - started) * 1000.0
            context = Thread.current[THREAD_CONTEXT_KEY]
            span.set_attribute("causcope.request.duration_ms", duration_ms)
            span.set_attribute("causcope.pool.max_checkout_wait_ms", context[:checkout_wait_ms]) if context
            if context
              span.set_attribute("causcope.pool.distinct_checkout_pools", context[:pool_ids].length)
              if context[:unresolved_pool_checkouts].positive?
                span.set_attribute(
                  "causcope.pool.unresolved_checkouts",
                  context[:unresolved_pool_checkouts]
                )
              end
            end

            if legacy_pool && legacy_binding
              after = safe_pool_stat(legacy_pool)
              span.set_attribute("causcope.pool.post_size", after[:size]) if after[:size]
              span.set_attribute("causcope.pool.post_busy", after[:busy]) if after[:busy]
              span.set_attribute("causcope.pool.post_waiting", after[:waiting]) if after[:waiting]
            end
            Thread.current[THREAD_CONTEXT_KEY] = previous_context
          end
        end
      end

      def tracer
        @tracer ||= OpenTelemetry.tracer_provider.tracer("causcope.rails.runtime", "0.2")
      end

      def single_pool_contract?
        @pool_entities.length == 1
      end

      def pool_binding(pool)
        db_config = pool.respond_to?(:db_config) ? pool.db_config : nil
        return nil unless db_config

        config_name = string_value(db_config.respond_to?(:name) ? db_config.name : nil)
        return nil unless config_name

        entity = @pool_entities_by_config_name[config_name]
        return nil unless entity

        attributes = entity.fetch("attributes", {})
        runtime_environment = string_value(db_config.respond_to?(:env_name) ? db_config.env_name : nil)
        static_environment = string_value(attributes["environment"])
        return nil if static_environment && runtime_environment && static_environment != runtime_environment

        runtime_adapter = string_value(db_config.respond_to?(:adapter) ? db_config.adapter : nil)
        static_adapter = string_value(attributes["adapter"])
        return nil if static_adapter && runtime_adapter && static_adapter != runtime_adapter

        {
          entity: entity,
          config_name: config_name,
          environment: runtime_environment,
          adapter: runtime_adapter,
          role: runtime_pool_dimension(pool, :role),
          shard: runtime_pool_dimension(pool, :shard)
        }
      rescue StandardError
        nil
      end

      def pool_checkout_event_attributes(binding, wait_ms, stat)
        entity = binding.fetch(:entity)
        attributes = {
          "causcope.system_id" => @system_id,
          "causcope.revision" => @revision,
          "causcope.pool_id" => entity.fetch("id"),
          "causcope.pool.technology" => entity.dig("attributes", "technology"),
          "causcope.pool.config_name" => binding.fetch(:config_name),
          "causcope.pool.checkout_wait_ms" => wait_ms
        }
        attributes["causcope.pool.role"] = binding[:role] if binding[:role]
        attributes["causcope.pool.shard"] = binding[:shard] if binding[:shard]
        attributes["causcope.pool.checkout_size"] = stat[:size] if stat[:size]
        attributes["causcope.pool.checkout_busy"] = stat[:busy] if stat[:busy]
        attributes["causcope.pool.checkout_waiting"] = stat[:waiting] if stat[:waiting]
        attributes
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

        @pool_entities = entities.select do |entity|
          entity["kind"] == "resource_pool" && entity.dig("attributes", "technology") == "active_record"
        end
        if @pool_entities.empty?
          raise ConfigurationError, "portable Rails runtime requires at least one ActiveRecord resource_pool"
        end

        @pool_entities_by_config_name = {}
        @pool_entities.each do |entity|
          config_name = string_value(entity.dig("attributes", "config_name"))
          unless config_name
            raise ConfigurationError,
                  "ActiveRecord resource_pool #{entity.fetch('id')} lacks attributes.config_name; rescan with the current Causcope provider"
          end
          if @pool_entities_by_config_name.key?(config_name)
            raise ConfigurationError,
                  "multiple ActiveRecord resource pools declare config_name #{config_name.inspect}"
          end
          @pool_entities_by_config_name[config_name] = entity
        end
      rescue Errno::ENOENT => error
        raise ConfigurationError, "static facts not found: #{error.message}"
      rescue JSON::ParserError => error
        raise ConfigurationError, "static facts are not valid JSON: #{error.message}"
      end

      def configure_opentelemetry!
        if ENV["CAUSCOPE_OTEL_SYNC"] == "1"
          ENV["OTEL_TRACES_EXPORTER"] = "none"
          exporter = SynchronizedExporter.new(OpenTelemetry::Exporter::OTLP::Exporter.new)
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

      def base_attributes(code_symbol, stat, binding)
        attributes = {
          "causcope.code_symbol" => code_symbol,
          "causcope.system_id" => @system_id,
          "causcope.revision" => @revision,
          "causcope.pool.technology" => "active_record"
        }
        return attributes unless binding

        entity = binding.fetch(:entity)
        attributes["causcope.pool_id"] = entity.fetch("id")
        attributes["causcope.pool.config_name"] = binding.fetch(:config_name)
        attributes["causcope.pool.role"] = binding[:role] if binding[:role]
        attributes["causcope.pool.shard"] = binding[:shard] if binding[:shard]
        configured_capacity = entity.dig("attributes", "configured_capacity")
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

      def runtime_pool_dimension(pool, name)
        value = if pool.respond_to?(name)
          pool.public_send(name)
        elsif pool.respond_to?(:pool_config) && pool.pool_config.respond_to?(name)
          pool.pool_config.public_send(name)
        end
        string_value(value)
      end

      def string_value(value)
        return nil if value.nil?

        rendered = value.to_s
        rendered.empty? ? nil : rendered
      end
    end
  end
end

Causcope::RailsRuntime.install!
