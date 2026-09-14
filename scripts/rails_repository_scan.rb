#!/usr/bin/env ruby

require "json"
require "optparse"
require "ripper"
require "yaml"

UNRESOLVED_ERB_PREFIX = "__CAUSCOPE_UNRESOLVED_ERB_"
DATABASE_CANDIDATES = [
  "config/database.yml",
  "config/database.yml.sample",
  "config/database.yml.example",
].freeze

options = {
  environment: "production",
  env: {},
}

OptionParser.new do |parser|
  parser.banner = "Usage: rails_repository_scan.rb --root PATH --system-id ID --revision VALUE --output PATH [options]"
  parser.on("--root PATH") { |value| options[:root] = value }
  parser.on("--environment NAME") { |value| options[:environment] = value }
  parser.on("--database-config PATH") { |value| options[:database_config] = value }
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
abort("not a supported Rails repository: missing Gemfile") unless File.file?(gemfile_path)
abort("not a supported Rails repository: missing config/application.rb") unless File.file?(application_path)

gemfile = File.read(gemfile_path)
abort("Gemfile does not declare Rails") unless gemfile.match?(/\bgem\s+["']rails["']/)

def relative_reference(root, path)
  prefix = root.end_with?(File::SEPARATOR) ? root : root + File::SEPARATOR
  path.start_with?(prefix) ? path.delete_prefix(prefix) : path
end

def choose_database_path(root, configured)
  if configured && !configured.empty?
    path = File.expand_path(configured, root)
    abort("database config does not exist: #{path}") unless File.file?(path)
    return path
  end

  candidate = DATABASE_CANDIDATES
    .map { |relative| File.join(root, relative) }
    .find { |path| File.file?(path) }
  abort(
    "not a supported Rails repository: missing database config; expected one of #{DATABASE_CANDIDATES.join(', ')}"
  ) unless candidate
  candidate
end

database_path = choose_database_path(root, options[:database_config])
database_reference = relative_reference(root, database_path)
database_is_sample = File.basename(database_path) != "database.yml"

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

def render_bounded_env_expressions(source, environment_values)
  rendered = source.dup

  rendered.gsub!(/<%=\s*ENV\.fetch\(\s*["']([A-Z0-9_]+)["']\s*,\s*(["'])(.*?)\2\s*\)\s*%>/m) do
    key = Regexp.last_match(1)
    fallback = Regexp.last_match(3)
    yaml_scalar(environment_values.fetch(key, fallback))
  end

  rendered.gsub!(/<%=\s*ENV\.fetch\(\s*["']([A-Z0-9_]+)["']\s*\)\s*%>/m) do
    key = Regexp.last_match(1)
    environment_values.key?(key) ? yaml_scalar(environment_values.fetch(key)) : "#{UNRESOLVED_ERB_PREFIX}ENV_#{key}".to_json
  end

  rendered.gsub!(/<%=\s*ENV\[\s*["']([A-Z0-9_]+)["']\s*\]\s*%>/m) do
    key = Regexp.last_match(1)
    environment_values.key?(key) ? yaml_scalar(environment_values.fetch(key)) : "#{UNRESOLVED_ERB_PREFIX}ENV_#{key}".to_json
  end

  rendered
end

def mask_unresolved_value_erb(source)
  unresolved_lines = []
  rendered_lines = source.lines.each_with_index.map do |line, index|
    line = line.gsub(/<%#.*?%>/, "")
    next line unless line.include?("<%")

    unless line.scan(/<%.*?%>/).all? { |tag| tag.start_with?("<%=") } && !line.match?(/<%(?![=#])/)
      abort(
        "database config contains structural ERB at line #{index + 1}; portable scan never executes repository ERB"
      )
    end

    match = line.match(/^(\s*[^#\n][^:]*:\s*)(.*)$/)
    unless match && match[2].include?("<%=")
      abort(
        "database config contains unsupported ERB structure at line #{index + 1}; portable scan never executes repository ERB"
      )
    end

    placeholder = "#{UNRESOLVED_ERB_PREFIX}LINE_#{index + 1}"
    unresolved_lines << index + 1
    newline = line.end_with?("\n") ? "\n" : ""
    "#{match[1]}#{placeholder.to_json}#{newline}"
  end
  [rendered_lines.join, unresolved_lines]
end

def unresolved_value?(value)
  value.is_a?(String) && value.include?(UNRESOLVED_ERB_PREFIX)
end

def database_configurations(environment_config)
  if environment_config.key?("adapter")
    return [["primary", environment_config]]
  end

  configs = environment_config.each_with_object([]) do |(name, config), output|
    next unless config.is_a?(Hash)
    next if name.to_s == "variables"

    database_keys = %w[adapter database pool checkout_timeout replica migrations_paths]
    next unless database_keys.any? { |key| config.key?(key) }

    output << [name.to_s, config]
  end
  abort("database environment does not contain any recognizable ActiveRecord database configurations") if configs.empty?
  configs
end

def local_slug(value)
  slug = value.to_s.downcase.gsub(/[^a-z0-9_.-]+/, "-").gsub(/^-+|-+$/, "")
  slug.empty? ? "database" : slug
end

def fact_slug(value)
  slug = value.to_s.downcase.gsub(/[^a-z0-9_]+/, "_").gsub(/^_+|_+$/, "")
  slug.empty? ? "database" : slug
end

def dbms_for_adapter(adapter)
  case adapter
  when "postgresql"
    "postgresql"
  when "sqlite3"
    "sqlite"
  when "mysql2", "trilogy"
    "mysql"
  else
    adapter
  end
end

def label_for_adapter(adapter)
  case adapter
  when "postgresql"
    "PostgreSQL"
  when "sqlite3"
    "SQLite"
  when "mysql2"
    "MySQL"
  when "trilogy"
    "MySQL (Trilogy)"
  else
    adapter
  end
end

def positive_integer(value)
  return nil if value.nil? || unresolved_value?(value)

  integer = Integer(value)
  integer.positive? ? integer : nil
rescue ArgumentError, TypeError
  nil
end

def positive_float(value)
  return nil if value.nil? || unresolved_value?(value)

  number = Float(value)
  number.positive? ? number : nil
rescue ArgumentError, TypeError
  nil
end

rendered_database = render_bounded_env_expressions(File.read(database_path), environment_values)
rendered_database, unresolved_erb_lines = mask_unresolved_value_erb(rendered_database)
begin
  database = YAML.safe_load(rendered_database, aliases: true)
rescue Psych::Exception => error
  abort("#{database_reference} could not be parsed safely: #{error.message}")
end
abort("#{database_reference} must contain an object") unless database.is_a?(Hash)
environment_config = database[options.fetch(:environment)]
abort("#{database_reference} does not define environment #{options.fetch(:environment)}") unless environment_config.is_a?(Hash)
configurations = database_configurations(environment_config)

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

entities = [
  {
    "id" => service_id,
    "kind" => "service",
    "label" => options.fetch(:system_id),
    "certainty" => "direct",
    "provenance" => config_provenance.call("config/application.rb"),
    "attributes" => { "framework" => "rails", "environment" => options.fetch(:environment) },
  },
]
facts = []
limitations = [
  "Portable scan never executes repository ERB; unresolved value expressions remain unknown instead of being evaluated.",
  "Code-to-pool facts are emitted only for methods with explicit ActiveRecord connection-pool API evidence.",
  "Implicit ActiveRecord query paths remain unknown until semantic enrichment or runtime evidence proves the relationship.",
]
limitations << "Using #{database_reference} because config/database.yml is absent or an alternate database config was selected; this source may describe defaults rather than the deployed configuration." if database_is_sample
limitations << "#{database_reference} contains unresolved value ERB at line(s) #{unresolved_erb_lines.join(', ')}; only fields unaffected by those expressions are emitted as concrete facts." unless unresolved_erb_lines.empty?

pool_records = []
configurations.each do |config_name, configuration|
  config_local_slug = local_slug(config_name)
  config_fact_slug = fact_slug(config_name)
  pool_id = "pool:active_record.#{config_local_slug}"
  reference = "#{database_reference}##{options.fetch(:environment)}.#{config_name}"

  adapter_value = configuration["adapter"]
  adapter = unresolved_value?(adapter_value) || adapter_value.nil? ? nil : adapter_value.to_s
  pool_capacity = positive_integer(configuration["pool"])
  checkout_timeout = positive_float(configuration["checkout_timeout"])

  pool_attributes = {
    "technology" => "active_record",
    "environment" => options.fetch(:environment),
    "config_name" => config_name,
  }
  pool_attributes["adapter"] = adapter if adapter
  pool_attributes["replica"] = configuration["replica"] if [true, false].include?(configuration["replica"])
  pool_attributes["configured_capacity"] = pool_capacity if pool_capacity
  pool_attributes["checkout_timeout_seconds"] = checkout_timeout if checkout_timeout
  pool_attributes["config_source"] = database_reference

  entities << {
    "id" => pool_id,
    "kind" => "resource_pool",
    "label" => "ActiveRecord #{config_name} database connection pool",
    "certainty" => "direct",
    "provenance" => config_provenance.call(reference),
    "attributes" => pool_attributes,
  }

  service_fact_id = if configurations.length == 1 && config_name == "primary"
    "fact.rails.service.depends_on_primary_pool"
  else
    "fact.rails.service.depends_on_pool.#{config_fact_slug}"
  end
  facts << {
    "id" => service_fact_id,
    "subject" => service_id,
    "relation" => "depends_on",
    "object" => pool_id,
    "certainty" => "direct",
    "provenance" => config_provenance.call(reference),
  }

  dependency_id = nil
  if adapter
    dbms = dbms_for_adapter(adapter)
    dependency_id = if configurations.length == 1 && config_name == "primary"
      "dependency:#{adapter}"
    else
      "dependency:database.#{config_local_slug}"
    end
    dependency_attributes = {
      "adapter" => adapter,
      "dbms" => dbms,
      "environment" => options.fetch(:environment),
      "config_name" => config_name,
    }
    dependency_attributes["replica"] = configuration["replica"] if [true, false].include?(configuration["replica"])

    entities << {
      "id" => dependency_id,
      "kind" => "external_dependency",
      "label" => configurations.length == 1 ? label_for_adapter(adapter) : "#{label_for_adapter(adapter)} (#{config_name})",
      "certainty" => "direct",
      "provenance" => config_provenance.call(reference),
      "attributes" => dependency_attributes,
    }

    dependency_fact_id = if configurations.length == 1 && config_name == "primary" && adapter == "postgresql"
      "fact.rails.primary_pool.depends_on_postgresql"
    else
      "fact.rails.pool.#{config_fact_slug}.depends_on_database"
    end
    facts << {
      "id" => dependency_fact_id,
      "subject" => pool_id,
      "relation" => "depends_on",
      "object" => dependency_id,
      "certainty" => "direct",
      "provenance" => config_provenance.call(reference),
    }
  else
    limitations << "Database adapter for #{options.fetch(:environment)}.#{config_name} is unresolved; no concrete database dependency is emitted for #{pool_id}."
  end

  if configuration.key?("pool")
    if unresolved_value?(configuration["pool"])
      limitations << "Configured pool capacity for #{options.fetch(:environment)}.#{config_name} is unresolved; resolving it would require runtime configuration or executing repository Ruby, so capacity remains unknown."
    elsif pool_capacity.nil?
      limitations << "Configured pool capacity for #{options.fetch(:environment)}.#{config_name} is present but not a positive integer; capacity remains unknown."
    end
  else
    limitations << "Configured pool capacity for #{options.fetch(:environment)}.#{config_name} is unspecified; capacity remains unknown."
  end

  pool_records << { name: config_name, id: pool_id, dependency_id: dependency_id }
end

if configurations.length > 1
  limitations << "Multiple ActiveRecord database configurations were discovered; generic connection_pool/with_connection calls are not assigned to a specific pool without explicit role or config identity."
end

seen_code_ids = {}
explicit_methods.each_with_index do |entry, index|
  code_id = "code:#{entry.fetch(:owner)}##{entry.fetch(:method)}()"
  next if seen_code_ids.key?(code_id)

  seen_code_ids[code_id] = true
  code_attributes = { "pool_api_evidence" => entry.fetch(:evidence).join(",") }
  code_attributes["pool_assignment"] = "unresolved_multiple_configs" if configurations.length > 1
  entities << {
    "id" => code_id,
    "kind" => "code_symbol",
    "label" => "#{entry.fetch(:owner)}##{entry.fetch(:method)}",
    "certainty" => "direct",
    "provenance" => source_provenance.call(entry.fetch(:path)),
    "source_location" => { "path" => entry.fetch(:path), "start_line" => entry.fetch(:line) },
    "attributes" => code_attributes,
  }
  if configurations.length == 1
    facts << {
      "id" => "fact.rails.explicit_pool_path.#{index + 1}",
      "subject" => code_id,
      "relation" => "depends_on",
      "object" => pool_records.first.fetch(:id),
      "certainty" => "direct",
      "provenance" => source_provenance.call(entry.fetch(:path)),
      "note" => "Explicit ActiveRecord connection-pool API observed in this method and exactly one database pool is configured for the selected environment.",
    }
  end
  facts << {
    "id" => "fact.rails.service.contains_explicit_pool_path.#{index + 1}",
    "subject" => service_id,
    "relation" => "contains",
    "object" => code_id,
    "certainty" => "direct",
    "provenance" => source_provenance.call(entry.fetch(:path)),
  }
end

limitations << "No explicit application code path using ActiveRecord connection-pool APIs was found." if explicit_methods.empty?

document = {
  "schema_version" => "0.1",
  "kind" => "concrete_system_facts",
  "system_id" => options.fetch(:system_id),
  "revision" => revision,
  "entities" => entities,
  "facts" => facts,
  "limitations" => limitations.uniq,
}

File.write(options.fetch(:output), JSON.pretty_generate(document) + "\n")
