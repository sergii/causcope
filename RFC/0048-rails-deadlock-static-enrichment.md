# RFC 0048: Conservative Rails static enrichment for D2.2

- Status: Accepted
- Date: 2026-09-14

## Summary

RFC 0047 established a real Rubydex -> `concrete_system_facts` bridge for direct semantic repository evidence. This RFC adds the first deterministic framework-aware enrichment layer required for the D2.2 predictive deadlock slice.

The pipeline is now:

```text
Ruby source
  -> Rubydex direct semantic facts
  -> conservative Rails source rules
  -> inferred transaction/data/access-order facts
  -> D2.2 opposing access-order projection
```

The enrichment remains static. It detects structural preconditions only and must not claim an observed deadlock.

## Why a separate layer

Rubydex can establish code identity, ownership, and source location. It does not itself establish Rails framework semantics such as ActiveRecord table mapping or transaction boundaries.

Those interpretations therefore remain separate from direct Rubydex evidence:

```text
direct Rubydex fact
  !=
framework-derived fact
  !=
runtime/database evidence
```

All Rails-derived entities and facts use `certainty: inferred` plus an explicit `provenance.rule`.

## Initial rule set

The first rule set is intentionally narrow and designed only to prove the D2.2 vertical slice.

### `rails.explicit_table_name.v0`

Recognizes a top-level Rails model with an explicit source mapping:

```ruby
class Account < ApplicationRecord
  self.table_name = "accounts"
end
```

It produces:

```text
code:Account
  --maps_to-->
db:public.accounts
```

The rule does not implement Rails inflection or infer a table name from a class name.

### `rails.transaction_block.v0`

Recognizes only explicit block forms:

```ruby
ApplicationRecord.transaction do
  ...
end
```

or:

```ruby
ActiveRecord::Base.transaction do
  ...
end
```

It creates an inferred transaction entity and an `executes_in` relation from the Rubydex method symbol to that transaction.

### `rails.constant_receiver_write.v0`

Inside a recognized transaction, the first slice recognizes a conservative allow-list of constant-receiver ActiveRecord write calls such as:

```ruby
Account.update_all(...)
LedgerEntry.create!(...)
```

The call is mapped to the data resource only when the model itself has an explicit table mapping recognized by the previous rule.

### `rails.source_ordered_writes.v0`

For recognized writes inside one transaction, source order produces an inferred `accesses_before` fact.

For example:

```text
CheckoutService#call()
  accounts -> ledger_entries

SettlementJob#perform()
  ledger_entries -> accounts
```

allows the existing deterministic projection to emit:

```text
opposing_access_order_precondition
```

## Epistemic constraint

`accesses_before` in this slice means source order among the recognized write statements. It is not proof that PostgreSQL acquired physical or logical locks in that exact order.

Therefore the projection remains:

```text
structural precondition detected: yes
runtime overlap: unknown
wait-for cycle: unknown
deadlock observed: false
```

A runtime deadlock claim still requires runtime/database evidence.

## Explicit non-goals

This slice does not attempt to model:

- implicit Rails table naming;
- callbacks;
- associations;
- scopes;
- nested service calls;
- SQL strings;
- dynamic dispatch;
- metaprogramming;
- writes hidden behind repository/service abstractions;
- implicit transactions;
- nested transactions/savepoints;
- PostgreSQL lock modes;
- actual row/key identity;
- runtime concurrency or overlap.

Unknown behavior remains unknown rather than being converted to absent behavior.

## Fixture proof

The Rubydex integration fixture now contains two transaction-bearing paths:

```text
CheckoutService#call()
  Account.update_all
  LedgerEntry.create!

SettlementJob#perform()
  LedgerEntry.create!
  Account.update_all
```

with explicit model mappings for `accounts` and `ledger_entries`.

The workflow validates that:

1. Rubydex still emits only direct semantic facts;
2. Rails enrichment emits inferred data-resource, transaction, write, and access-order facts;
3. the two paths produce exactly one D2.2 opposing-order structural precondition;
4. the projection keeps `deadlock_observed: false`;
5. both direct and enriched outputs are deterministic across repeated runs.

No LLM is involved.

## Next slice

The next step is to combine this static D2.2 precondition with runtime evidence:

```text
static opposing order
  +
OTel evidence that both paths execute / overlap
  +
pgBot or PostgreSQL lock/wait evidence
  ->
epistemic D2.2 state
```

That composition should distinguish at least:

- structural possibility;
- preconditions present;
- runtime concurrency observed;
- lock contention observed;
- concrete deadlock/wait-for cycle observed;
- confirmed causal diagnosis.

Those states should be derived from evidence where possible rather than stored as free-form LLM conclusions.
