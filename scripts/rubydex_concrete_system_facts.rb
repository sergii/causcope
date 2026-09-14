#!/usr/bin/env ruby
# frozen_string_literal: true

require "digest"
require "json"
require "optparse"
require "pathname"
require "rubydex"

SUPPORTED_DECLARATIONS = [Rubydex::Class, Rubydex::Module, Rubydex::Method].freeze


def parse_options
  options = {}
  parser = OptionParser.new do |opts|
    opts.banner = "Usage: rubydex_concrete_system_facts.rb --workspace PATH --system-id ID --revision SHA [options]"
    opts.on("--workspace PATH", "Ruby workspace to index") { |value| options[:workspace] = value }
    opts.on("--system-id ID", "Concrete system identifier") { |value| options[:system_id] = value }
    opts.on("--revision VALUE", "Pinned repository revision") { |value| options[:revision] = value }
    opts.on("--repository VALUE", "Repository identity or URL") { |value| options[:repository] = value }
    opts.on("--output PATH", "Write JSON to PATH instead of stdout") { |value| options[:output] = value }
  end
  parser.parse!

  missing = %i[workspace system_id revision].reject { |key| options[key] && !options[key].empty? }
  abort("missing required options: #{missing.join(', ')}") unless missing.empty?

  options
end


def within_workspace?(path, workspace)
  resolved = Pathname.new(path).realpath
  resolved == workspace || resolved.to_s.start_with?("#{workspace}#{File::SEPARATOR}")
rescue Errno::ENOENT, Rubydex::Location::NotFileUriError, URI::InvalidURIError
  false
end


def source_location(definition, workspace)
  location = definition.location
  path = location.to_file_path
  return nil unless within_workspace?(path, workspace)

  display = location.to_display
  {
    "path" => Pathname.new(path).realpath.relative_path_from(workspace).to_s,
    "start_line" => display.start_line,
    "start_column" => display.start_column,
    "end_line" => display.end_line,
    "end_column" => display.end_column,
  }
rescue Errno::ENOENT, Rubydex::Location::NotFileUriError, URI::InvalidURIError
  nil
end


def workspace_definitions(declaration, workspace)
  declaration.definitions.filter_map do |definition|
    location = source_location(definition, workspace)
    next unless location

    [definition, location]
  end.sort_by do |_definition, location|
    [location.fetch("path"), location.fetch("start_line"), location.fetch("start_column")]
  end
end


def declaration_kind(declaration)
  declaration.class.name.delete_prefix("Rubydex::")
end


def code_id(declaration)
  "code:#{declaration.name}"
end


def fact_id(relation, subject, object)
  digest = Digest::SHA256.hexdigest([relation, subject, object].join("\0"))[0, 16]
  "fact.rubydex_#{relation}.#{digest}"
end


def entity_for(declaration, definitions)
  primary_location = definitions.first.fetch(1)
  owner = declaration.owner
  attributes = {
    "rubydex_kind" => declaration_kind(declaration),
    "definition_count" => definitions.length.to_s,
  }
  attributes["owner"] = owner.name if owner && owner.name && !owner.name.empty?

  {
    "id" => code_id(declaration),
    "kind" => "code_symbol",
    "label" => declaration.name,
    "certainty" => "direct",
    "confidence" => "high",
    "provenance" => {
      "source_type" => "static_analysis",
      "name" => "rubydex",
      "reference" => declaration.name,
      "query" => "graph.declarations",
    },
    "source_location" => primary_location,
    "attributes" => attributes,
  }
end


def containment_fact(owner, member)
  subject = code_id(owner)
  object = code_id(member)
  {
    "id" => fact_id("contains", subject, object),
    "subject" => subject,
    "relation" => "contains",
    "object" => object,
    "certainty" => "direct",
    "confidence" => "high",
    "provenance" => {
      "source_type" => "static_analysis",
      "name" => "rubydex",
      "reference" => "#{owner.name} owns #{member.name}",
      "query" => "declaration.owner",
    },
  }
end


def build_document(options)
  workspace = Pathname.new(options.fetch(:workspace)).realpath
  graph = nil

  Dir.chdir(workspace) do
    graph = Rubydex::Graph.new
    graph.index_workspace
    graph.resolve
  end

  selected = {}
  graph.declarations.each do |declaration|
    next unless SUPPORTED_DECLARATIONS.any? { |klass| declaration.is_a?(klass) }
    next if declaration.name.nil? || declaration.name.empty? || declaration.name.match?(/\s/)

    definitions = workspace_definitions(declaration, workspace)
    next if definitions.empty?

    selected[declaration.name] = [declaration, definitions]
  end

  entities = selected.values.map { |declaration, definitions| entity_for(declaration, definitions) }
  entity_ids = entities.to_h { |entity| [entity.fetch("id"), true] }

  facts = selected.values.filter_map do |declaration, _definitions|
    owner = declaration.owner
    next unless owner && entity_ids[code_id(owner)]

    containment_fact(owner, declaration)
  end

  facts = facts.uniq { |fact| fact.fetch("id") }
  abort("Rubydex found no workspace-defined code symbols") if entities.empty?
  abort("Rubydex found code symbols but no exportable ownership relations") if facts.empty?

  revision = {
    "type" => "git",
    "value" => options.fetch(:revision),
  }
  revision["repository"] = options[:repository] if options[:repository] && !options[:repository].empty?

  {
    "schema_version" => "0.1",
    "kind" => "concrete_system_facts",
    "system_id" => options.fetch(:system_id),
    "revision" => revision,
    "entities" => entities.sort_by { |entity| entity.fetch("id") },
    "facts" => facts.sort_by { |fact| fact.fetch("id") },
    "limitations" => [
      "This v0 extractor exports only workspace-defined classes, modules, methods, and declaration ownership.",
      "A reopened declaration can have multiple definitions; source_location records the first deterministic workspace definition and definition_count records multiplicity.",
      "Rubydex ownership is static repository evidence and does not prove runtime execution, transaction membership, database access, lock ordering, or concurrency.",
      "Dynamic or unresolved behavior is not converted into absent facts.",
    ],
  }
end


options = parse_options
document = build_document(options)
json = JSON.pretty_generate(document) + "\n"

if options[:output]
  Pathname.new(options[:output]).write(json)
else
  $stdout.write(json)
end
