require "opentelemetry/sdk"

OpenTelemetry::SDK.configure do |config|
  config.service_name = ENV.fetch("OTEL_SERVICE_NAME", "causcope-rails-connection-pool")
end
