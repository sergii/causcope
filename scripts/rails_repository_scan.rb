#!/usr/bin/env ruby

require "json"
require "optparse"
require "ripper"
require "yaml"

options = {
  environment: "production",
  env: {},
}

OptionParser.new do |parser|
  parser.banner = "Usage: rails_repository_scan.rb --root PATH --system-id ID --revision VALUE --output PATH [options]"
  parser.on("--root PATH") { |value| options[:root] = value }
  parser.on("--environment NAME") { |value| options[:environment] = value }
  parser.on("--env-file PATH") { |value| options[:env_file] = value }
  parser.on("--env KEY=VALUE") do |value|
    key, separator, item = value.partition("=")
    abort("--env expects KEY=VALUE") if separator.empty? || key.empty?
    options[:env][key] = item
  end
  parser.on("--system-id ID") { |value| options[:system_id] = value }
  parser.on("--revision VALUE") { |value| options[:revision] = value }
  parser.on("--repository URI") { |value| options[:repository] = value }
  parser.on("--output PATH") { |value| options[:output] = value }
end.parse!

required = %i[root system_id revision output]
missing = required.reject { |key| options[key] && !options[key].to_s.empty? }
abort("missing required options: #{missing.join(', ')}") unless missing.empty?

root = File.expand_path(options.fetch(:root))
abort("Rails root does not exist: #{root}") unless Dir.exist?(root)

gemfile_path = File.join(root, "Gemfile")
application_path = File.join(root, "config", "application.rb")
database_path = File.join(root, "config", "database.yml")
abort("not a supported Rails repository: missing Gemfile") unless File.file?(gemfile_path)
abort("not a supported Rails repository: missing config/application.rb") unless File.file?(application_path)
abort("not a supported Rails repository: missing config/database.yml") unless File.file?(database_path)

gemfile = File.read(gemfile_path)
abort("Gemfile does not declare Rails") unless gemfile.match?(/\bgem\s+["']rails["']/)

environment_values = {}
if options[:env_file]
  env_file = File.expand_path(options[:env_file], root)
  payload = YAML.safe_load(File.read(env_file), aliases: true)
  abort("environment file must contain an object") unless payload.is_a?(Hash)
  source = payload.key?("environment") ? payload.fetch("environment") : payload
  abort("environment mapping must contain scalar values") unless source.is_a?(Hash)
  source.each do |key, value|
    abort("environment value for #{key} must be scalar") if value.is_a?(Hash) || value.is_a?(Array)
    environment_values[key.to_s] = value.nil? ? nil : value.to_s
  end
end
options[:env].each { |key, value| environment_values[key] = value }

def yaml_scalar(value)
  return "null" if value.nil?

  value.to_s.to_json
end

def bounded_render_database(source, environment_values)
  rendered = source.dup

  rendered.gsub!(/<%=\s*ENV\.fetch\(\s*["']([A-Z0-9_]+)["']\s*,\s*(["'])(.*?)\2\s*\)\s*%>/m) do
    key = Regexp.last_match(1)
    fallback = Regexp.last_match(3)
    yaml_scalar(environment_values.fetch(key, fallback))
  end

  rendered.gsub!(/<%=\s*ENV\.fetch\(\s*["']([A-Z0-9_]+)["']\s*\)\s*%>/m) do
    key = Regexp.last_match(1)
    abort("database.yml requires unresolved environment variable #{key}") unless environment_values.key?(key)
    yaml_scalar(environment_values.fetch(key))
  end

  rendered.gsub!(/<%=\s*ENV\[\s*["']([A-Z0-9_]+)["']\s*\]\s*%>/m) do
    key = Regexp.last_match(1)
    yaml_scalar(environment_values[key])
  end

  abort("database.yml contains unsupported ERB; portable scan never executes repository ERB") if rendered.include?("<%")
  rendered
end

rendered_database = bounded_render_database(File.read(database_path), environment_values)
database = YAML.safe_load(rendered_database, aliases: true)
abort("config/database.yml must contain an object") unless database.is_a?(Hash)
configuration = database[options.fetch(:environment)]
abort("database.yml does not define environment #{options.fetch(:environment)}") unless configuration.is_a?(Hash)

if !configuration.key?("adapter") && configuration["primary"].is_a?(Hash)
  configuration = configuration.fetch("primary")
end

adapter = configuration["adapter"]
abort("portable Rails D3.1 provider currently requires PostgreSQL") unless adapter == "postgresql"

pool_capacity = nil
if configuration.key?("pool") && !configuration["pool"].nil?
  begin
    pool_capacity = Integer(configuration["pool"])
  rescue ArgumentError, TypeError
    abort("database pool capacity must resolve to an integer")
  end
  abort("database pool capacity must be positive") unless pool_capacity.positive?
end

checkout_timeout = nil
if configuration.key?("checkout_timeout") && !configuration["checkout_timeout"].nil?
  begin
    checkout_timeout = Float(configuration["checkout_timeout"])
  rescue ArgumentError, TypeError
    abort("checkout timeout must resolve to a number")
  end
  abort("checkout timeout must be positive") unless checkout_timeout.positive?
end

def const_name(node)
  return nil unless node.is_a?(Array)

  case node[0]
  when :const_ref, :var_ref
    token = node[1]
    token.is_a?(Array) && token[0] == :@const ? token[1] : nil
  when :top_const_ref
    token = node[1]
    token.is_a?(Array) && token[0] == :@const ? token[1] : nil
  when :const_path_ref, :const_path_field
    left = const_name(node[1])
    token = node[2]
    right = token.is_a?(Array) && token[0] == :@const ? token[1] : nil
    [left, right].compact.join("::")
  else
    nil
  end
end

def called_method_names(node, output = [])
  return output unless node.is_a?(Array)

  if %i[call command_call fcall vcall].include?(node[0])
    node.each do |child|
      output << child[1] if child.is_a?(Array) && child[0] == :@ident
    end
  end

  node.each { |child| called_method_names(child, output) if child.is_a?(Array) }
  output
end

def collect_explicit_pool_methods(node, namespace = [], output = [])
  return output unless node.is_a?(Array)

  case node[0]
  when :class
    name = const_name(node[1])
    collect_explicit_pool_methods(node[3], name ? namespace + [name] : namespace, output)
    return output
  when :module
    name = const_name(node[1])
    collect_explicit_pool_methods(node[2], name ? namespace + [name] : namespace, output)
    return output
  when :def
    token = node[1]
    method_name = token.is_a?(Array) && token[0] == :@ident ? token[1] : nil
    calls = called_method_names(node)
    evidence = calls.select { |item| %w[connection_pool with_connection].include?(item) }.uniq.sort
    if method_name && !evidence.empty?
      output << {
        owner: namespace.join("::"),
        method: method_name,
        line: token[2][0],
        evidence: evidence,
      }
    end
    return output
  end

  node.each { |child| collect_explicit_pool_methods(child, namespace, output) if child.is_a?(Array) }
  output
end

explicit_methods = []
Dir.glob(File.join(root, "app", "**", "*.rb")).sort.each do |path|
  source = File.read(path)
  sexp = Ripper.sexp(source)
  next unless sexp

  collect_explicit_pool_methods(sexp).each do |entry|
    next if entry[:owner].empty?

    entry[:path] = path.delete_prefix(root + File::SEPARATOR)
    explicit_methods << entry
  end
end

slug = options.fetch(:system_id).downcase.gsub(/[^a-z0-9_.-]+/, "-").gsub(/^-+|-+$/, "")
slug = "rails-app" if slug.empty?
service_id = "service:#{slug}"
pool_id = "pool:active_record.primary"
dependency_id = "dependency:postgresql"

revision = {
  "type" => "git",
  "value" => options.fetch(:revision),
}
revision["repository"] = options[:repository] if options[:repository] && !options[:repository].empty?

config_provenance = lambda do |reference|
  { "source_type" => "declared_config", "name" => "rails_repository_scan", "reference" => reference }
end
source_provenance = lambda do |reference|
  { "source_type" => "source", "name" => "ruby_ripper", "reference" => reference }
end

pool_attributes = {
  "technology" => "active_record",
  "adapter" => adapter,
  "environment" => options.fetch(:environment),
}
pool_attributes["configured_capacity"] = pool_capacity if pool_capacity
pool_attributes["checkout_timeout_seconds"] = checkout_timeout if checkout_timeout

entities = [
  {
    "id" => service_id,
    "kind" => "service",
    "label" => options.fetch(:system_id),
    "certainty" => "direct",
    "provenance" => config_provenance.call("config/application.rb"),
    "attributes" => { "framework" => "rails", "environment" => options.fetch(:environment) },
  },
  {
    "id" => pool_id,
    "kind" => "resource_pool",
    "label" => "ActiveRecord primary database connection pool",
    "certainty" => "direct",
    "provenance" => config_provenance.call("config/database.yml"),
    "attributes" => pool_attributes,
  },
  {
    "id" => dependency_id,
    "kind" => "external_dependency",
    "label" => "PostgreSQL",
    "certainty" => "direct",
    "provenance" => config_provenance.call("config/database.yml"),
    "attributes" => { "dbms" => "postgresql" },
  },
]

facts = [
  {
    "id" => "fact.rails.service.depends_on_primary_pool",
    "subject" => service_id,
    "relation" => "depends_on",
    "object" => pool_id,
    "certainty" => "direct",
    "provenance" => config_provenance.call("config/database.yml"),
  },
  {
    "id" => "fact.rails.primary_pool.depends_on_postgresql",
    "subject" => pool_id,
    "relation" => "depends_on",
    "object" => dependency_id,
    "certainty" => "direct",
    "provenance" => config_provenance.call("config/database.yml"),
  },
]

explicit_methods.each_with_index do |entry, index|
  code_id = "code:#{entry.fetch(:owner)}##{entry.fetch(:method)}()"
  entities << {
    "id" => code_id,
    "kind" => "code_symbol",
    "label" => "#{entry.fetch(:owner)}##{entry.fetch(:method)}",
    "certainty" => "direct",
    "provenance" => source_provenance.call(entry.fetch(:path)),
    "source_location" => { "path" => entry.fetch(:path), "start_line" => entry.fetch(:line) },
    "attributes" => { "pool_api_evidence" => entry.fetch(:evidence).join(",") },
  }
  facts << {
    "id" => "fact.rails.explicit_pool_path.#{index + 1}",
    "subject" => code_id,
    "relation" => "depends_on",
    "object" => pool_id,
    "certainty" => "direct",
    "provenance" => source_provenance.call(entry.fetch(:path)),
    "note" => "Explicit ActiveRecord connection-pool API observed in this method.",
  }
  facts << {
    "id" => "fact.rails.service.contains_explicit_pool_path.#{index + 1}",
    "subject" => service_id,
    "relation" => "contains",
    "object" => code_id,
    "certainty" => "direct",
    "provenance" => source_provenance.call(entry.fetch(:path)),
  }
end

limitations = [
  "Portable scan never executes repository ERB; only bounded ENV access forms in database.yml are rendered.",
  "Code-to-pool facts are emitted only for methods with explicit ActiveRecord connection-pool API evidence.",
  "Implicit ActiveRecord query paths remain unknown until semantic enrichment or runtime evidence proves the relationship.",
]
limitations << "Configured pool capacity is unresolved; D3.1 capacity matching cannot advance until capacity evidence is supplied." unless pool_capacity
limitations << "No explicit application code path using ActiveRecord connection-pool APIs was found." if explicit_methods.empty?

document = {
  "schema_version" => "0.1",
  "kind" => "concrete_system_facts",
  "system_id" => options.fetch(:system_id),
  "revision" => revision,
  "entities" => entities,
  "facts" => facts,
  "limitations" => limitations,
}

File.write(options.fetch(:output), JSON.pretty_generate(document) + "\n")
