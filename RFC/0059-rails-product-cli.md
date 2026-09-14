# RFC 0059: Rails product CLI lifecycle

- Status: Implemented proof
- Date: 2026-09-15
- Scope: Turn the portable Rails static and runtime providers into a safe operator workflow without weakening revision identity

## Summary

RFC 0057 made repository scanning portable. RFC 0058 made runtime delivery production-shaped through standard OpenTelemetry.

The remaining usability gap was orchestration. A user still had to copy integration files, set several environment variables, remember the correct OTLP receiver invocation, and preserve exact revision identity manually.

RFC 0059 adds a small product-facing lifecycle:

```text
causcope scan ./my-rails-app
causcope rails install ./my-rails-app
causcope runtime start ./my-rails-app --incident-id INC-123
causcope rails run ./my-rails-app -- bundle exec puma
```

The commands are wrappers around the existing contracts. They do not add a new causal engine or a new evidence model.

## Safety invariant

Convenience must not create false identity.

The installer deliberately does not bake the scanned revision into a generated Rails initializer. Otherwise an application could move to a new commit while both the copied initializer and stale static contract continued to claim the old revision.

Instead:

```text
static scan revision
        ==
actual runtime revision
        or
runtime instrumentation does not start
```

`causcope rails run` obtains the current Git revision by default, or accepts an explicit deployment revision, and compares it exactly with the revision in `concrete_system_facts`.

A mismatch fails closed and asks the operator to rescan.

## `causcope rails install`

The install command requires an already-scanned Rails repository. By default it reads:

```text
.causcope/concrete-system-facts.json
```

It installs:

```text
lib/causcope/runtime.rb
config/initializers/causcope.rb
```

The runtime file is copied from the canonical portable integration in the Causcope checkout. The initializer loads only that repository-local copy.

The command also ensures that the Rails Gemfile declares:

```ruby
gem "opentelemetry-sdk", ">= 1.6", "< 2"
gem "opentelemetry-exporter-otlp", ">= 0.29", "< 1"
```

It does not run `bundle install` automatically.

The install is idempotent. Existing generated files with identical content are left unchanged. Conflicting files are never overwritten unless `--force` is explicit.

`--no-gemfile` is available for applications that manage OpenTelemetry dependencies elsewhere.

## `causcope rails run`

The run command launches an arbitrary application command under exact Causcope runtime identity:

```bash
causcope rails run ./my-rails-app -- bundle exec puma
```

Before executing the process it verifies:

- the Rails runtime integration is installed;
- the concrete static contract exists;
- the current or explicitly supplied revision exactly equals the scanned revision;
- pre-existing `CAUSCOPE_SYSTEM_ID` and `CAUSCOPE_REVISION` values do not conflict with the pinned contract.

It then supplies:

```text
CAUSCOPE_SYSTEM_ID
CAUSCOPE_REVISION
CAUSCOPE_STATIC_FACTS
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT
```

The OTLP endpoint defaults to:

```text
http://127.0.0.1:4318/v1/traces
```

`--sync-export` exists only for deterministic local and CI proofs. Normal operation keeps the asynchronous SDK exporter behavior from RFC 0058.

## `causcope runtime start`

The runtime command packages the existing concrete OTLP receiver invocation:

```bash
causcope runtime start ./my-rails-app --incident-id INC-123
```

By default it binds only to loopback and writes the current revision-bound runtime snapshot under:

```text
.causcope/runtime/<incident-id>.json
```

The command accepts explicit host, port, snapshot, source URI, and verbosity options. `--dry-run` validates the static contract and renders the exact receiver invocation without opening a socket.

The receiver semantics remain unchanged:

- explicit code-symbol bindings only;
- exact system and revision matching;
- unbound spans remain unknown rather than absent;
- OTLP delivery itself is not causal confirmation.

## Command routing

`bin/causcope` now owns three product-oriented command families:

```text
scan
rails
runtime
```

Existing investigation commands still fall through to `scripts/causcope_cli.py` unchanged.

## Failure behavior

The lifecycle is intentionally fail-closed for identity and fail-safe for user-owned files.

Examples:

```text
missing static facts
  -> install/run refuses and asks for causcope scan

runtime revision != scanned revision
  -> run refuses before application command execution

existing generated path has different content
  -> install refuses unless --force

pre-existing CAUSCOPE_REVISION conflicts with contract
  -> run refuses instead of silently replacing it
```

## Validation

`scripts/test_rails_product_cli.py` covers the lifecycle against a copied Rails fixture:

- scan to the default `.causcope` contract;
- install generated runtime and initializer;
- add missing OpenTelemetry Gemfile declarations exactly once;
- repeat install idempotently;
- validate copied Ruby runtime syntax;
- launch a child process with exact runtime identity;
- reject a revision mismatch before child execution;
- reject conflicting generated files and permit explicit `--force`;
- validate the concrete receiver command through `runtime start --dry-run`;
- reject install when static facts are missing.

The existing live Rails D3.1 workflow remains the transport and causal end-to-end proof. RFC 0059 does not duplicate that mechanism test.

## Non-goals

This slice does not yet provide:

- a published Ruby gem;
- automatic `bundle install`;
- daemon/service management for the receiver;
- authentication or TLS;
- multi-tenant runtime routing;
- multiple ActiveRecord pools, roles, or shards;
- ownership-aware integration with an application that already configures OpenTelemetry.

## Next milestone

The next high-value validation is no longer another synthetic failure mechanism.

Use the product lifecycle against an external open-source Rails application:

```text
real third-party Rails repository
        -> causcope scan
        -> causcope rails install
        -> causcope runtime start
        -> causcope rails run
        -> standard OTLP
        -> concrete runtime facts
```

The purpose of that milestone is to discover integration assumptions that our own fixture cannot expose: Gemfile layout, Rails initialization ordering, real database configuration shapes, existing telemetry ownership, multiple databases, and ordinary application code that does not explicitly call connection-pool APIs.
