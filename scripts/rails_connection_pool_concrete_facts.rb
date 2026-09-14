#!/usr/bin/env ruby

require "erb"
require "json"
require "optparse"
require "ripper"
require "yaml"

options = { environment: "production" }
OptionParser.new do |parser|
  parser.on("--controller PATH") { |value| options[:controller] = value }
  parser.on("--database PATH") { |value| options[:database] = value }
  parser.on("--deployment PATH") { |value| options[:deployment] = value }
  parser.on("--environment NAME") { |value| options[:environment] = value }
  parser.on("--system-id ID") { |value| options[:system_id] = value }
  parser.on("--revision VALUE") { |value| options[:revision] = value }
  parser.on("--repository URI") { |value| options[:repository] = value }
  parser.on("--output PATH") { |value| options[:output] = value }
end.parse!

required = %i[controller database deployment system_id revision repository output]
missing = required.reject { |key| options[key] && !options[key].empty? }
abort("missing required options: #{missing.join(', ')}") unless missing.empty?

controller_path = options.fetch(:controller)
database_path = options.fetch(:database)
deployment_path = options.fetch(:deployment)
controller_source = File.read(controller_path)
abort("controller source is not valid Ruby") unless Ripper.sexp(controller_source)

def collect_method_names(node, output = [])
  return output unless node.is_a?(Array)

  if node[0] == :def && node[1].is_a?(Array) && node[1][0] == :@ident
    output << node[1][1]
  end
  node.each { |child| collect_method_names(child, output) if child.is_a?(Array) }
  output
end

method_names = collect_method_names(Ripper.sexp(controller_source))
abort("PoolController#work is not declared") unless method_names.include?("work")

normalized_source = controller_source.gsub(/\s+/, "")
unless normalized_source.include?("ActiveRecord::Base.connection_pool") &&
       normalized_source.include?("pool.with_connection")
  abort("work path does not use the ActiveRecord connection pool")
end

deployment = YAML.safe_load(File.read(deployment_path), aliases: true)
environment_values = deployment.fetch("environment")
original_environment = {}
environment_values.each do |key, value|
  original_environment[key] = ENV.key?(key) ? ENV[key] : :__missing__
  ENV[key] = value.to_s
end

begin
  rendered_database = ERB.new(File.read(database_path)).result
  database = YAML.safe_load(rendered_database, aliases: true)
ensure
  original_environment.each do |key, value|
    if value == :__missing__
      ENV.delete(key)
    else
      ENV[key] = value
    end
  end
end

configuration = database.fetch(options.fetch(:environment))
adapter = configuration.fetch("adapter")
abort("D3.1 Rails provider currently requires PostgreSQL") unless adapter == "postgresql"

pool_capacity = Integer(configuration.fetch("pool"))
checkout_timeout = Float(configuration.fetch("checkout_timeout"))
abort("pool capacity must be positive") unless pool_capacity.positive?
abort("checkout timeout must be positive") unless checkout_timeout.positive?

work_line = controller_source.lines.index { |line| line.match?(/^\s*def\s+work\b/) }
abort("could not locate PoolController#work source line") unless work_line

service_id = "service:rails-connection-pool-app"
code_id = "code:PoolController#work()"
pool_id = "pool:active_record.primary"
dependency_id = "dependency:postgresql"

source_provenance = lambda do |reference|
  { "source_type" => "source", "name" => "ruby", "reference" => reference }
end
config_provenance = lambda do |reference|
  { "source_type" => "declared_config", "name" => "rails", "reference" => reference }
end

document = {
  "schema_version" => "0.1",
  "kind" => "concrete_system_facts",
  "system_id" => options.fetch(:system_id),
  "revision" => {
    "type" => "git",
    "value" => options.fetch(:revision),
    "repository" => options.fetch(:repository)
  },
  "entities" => [
    {
      "id" => service_id,
      "kind" => "service",
      "label" => "Rails connection-pool fixture",
      "certainty" => "direct",
      "provenance" => config_provenance.call(deployment_path),
      "attributes" => { "framework" => "rails", "environment" => options.fetch(:environment) }
    },
    {
      "id" => code_id,
      "kind" => "code_symbol",
      "label" => "PoolController#work",
      "certainty" => "direct",
      "provenance" => source_provenance.call(controller_path),
      "source_location" => { "path" => controller_path, "start_line" => work_line + 1 }
    },
    {
      "id" => pool_id,
      "kind" => "resource_pool",
      "label" => "ActiveRecord primary database connection pool",
      "certainty" => "direct",
      "provenance" => config_provenance.call(database_path),
      "attributes" => {
        "technology" => "active_record",
        "adapter" => adapter,
        "configured_capacity" => pool_capacity,
        "checkout_timeout_seconds" => checkout_timeout,
        "environment" => options.fetch(:environment)
      }
    },
    {
      "id" => dependency_id,
      "kind" => "external_dependency",
      "label" => "PostgreSQL",
      "certainty" => "direct",
      "provenance" => config_provenance.call(database_path),
      "attributes" => { "dbms" => "postgresql" }
    }
  ],
  "facts" => [
    {
      "id" => "fact.rails.service.contains_work",
      "subject" => service_id,
      "relation" => "contains",
      "object" => code_id,
      "certainty" => "direct",
      "provenance" => source_provenance.call(controller_path)
    },
    {
      "id" => "fact.rails.work.depends_on_pool",
      "subject" => code_id,
      "relation" => "depends_on",
      "object" => pool_id,
      "certainty" => "direct",
      "provenance" => source_provenance.call(controller_path)
    },
    {
      "id" => "fact.rails.pool.depends_on_postgresql",
      "subject" => pool_id,
      "relation" => "depends_on",
      "object" => dependency_id,
      "certainty" => "direct",
      "provenance" => config_provenance.call(database_path)
    }
  ],
  "limitations" => [
    "The extractor evaluates database.yml ERB only with values from the checked-in deployment contract.",
    "The extractor proves this bounded ActiveRecord pool path; it does not enumerate every database role, shard, or dynamically selected connection handler in a general Rails application."
  ]
}

File.write(options.fetch(:output), JSON.pretty_generate(document) + "\n")
