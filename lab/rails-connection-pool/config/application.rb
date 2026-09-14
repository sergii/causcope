require_relative "boot"

require "rails"
require "active_record/railtie"
require "action_controller/railtie"

Bundler.require(*Rails.groups)

module CauscopeRailsConnectionPool
  class Application < Rails::Application
    config.load_defaults 8.0
    config.api_only = true
    config.eager_load = false
    config.secret_key_base = "causcope-rails-connection-pool-fixture-secret"
    config.hosts.clear
    config.consider_all_requests_local = true
  end
end
