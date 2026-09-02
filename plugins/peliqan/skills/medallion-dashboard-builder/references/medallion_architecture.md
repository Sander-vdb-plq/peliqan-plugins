# Medallion Architecture Reference

This reference follows the naming actually used in practice: **Bronze →
Silver → Gold → consumer-facing layer**, with **Gold as the business-logic
layer**. Some formal architecture documents instead call the business-logic
layer "Core" and reserve "Gold" for the consumer-facing layer — if the
organization has a written architecture reference, check it, but also check
the actual schema names already in use in the warehouse. In practice, a
team's real implementation sometimes uses one convention (Gold = business
logic) even when their own documentation specifies the other — the existing
schema names are the more reliable signal to follow than a document alone,
since renaming an established schema after the fact adds real migration
work for no functional benefit.

## The four layers

**Bronze — single shared landing zone.** Raw data ingested exactly as the
source system sends it (CRM, ERP, API, file upload, webhook — whatever the
source is). Append-only, never transformed, typically shared across all
environments. Keep everything, even fields that seem unused today — the
point is to always have the original record to go back to.

**Silver — cleaned & source-aligned.** One cleaned, deduplicated, typed
table per source entity, with nulls handled. No cross-source joins yet. This
is where a date becomes a real date instead of text, and duplicate rows get
resolved — but still one source at a time, nothing combined.

**Gold — unified business entities.** Sources are unioned together, mapping
joins are applied, and **this is the only place business logic should
live**: what counts as revenue vs. cost, how a calculated amount is derived,
how a raw status code becomes a human-readable label. If a number is
calculated a certain way, the formula should exist here once — never
duplicated into dashboard code, or into a second copy of a table with a
different formula for the "same" thing.

**Consumer-facing layer — domain-shaped output.** A straightforward
passthrough or light reshaping of Gold, often using `fct_`/`dim_` naming and
often named after the specific domain it serves (e.g. `dm_sales`,
`dm_projects`). This is what the dashboard (or any other consumer) actually
reads from. Its only purpose is to be a stable point of contact — if a
business rule changes, it changes in Gold, and this layer updates
automatically without needing its own edits.

## Two operational principles worth carrying over into any implementation

**Promote code, not data.** If there are multiple environments (dev, test,
acceptance, production), Silver, Gold, and the consumer-facing layer are
typically replicated per environment, while Bronze is shared across all of
them. Changes move through environments as code (the queries/
transformations), not as copied data.

**Consumers always point to the consumer-facing layer in production.**
Nothing downstream of the warehouse — a dashboard, a report, an API —
should query Gold or Silver directly in production. This keeps the boundary
clean: business logic changes happen in Gold, and every consumer
automatically inherits the change without needing its own edits.

## Why this separation matters practically

If a number on a dashboard ever looks wrong, it's traceable backward one
layer at a time: dashboard → consumer-facing layer → Gold → Silver →
Bronze. Because each layer has exactly one job, a bug is always findable at
whichever layer introduced it, rather than being accidentally duplicated
with two different "correct" answers living in two different places.

## The customer-facing explanation (kitchen analogy)

This has tested well when explaining the architecture to a non-technical
audience — adjust the specific business-logic example to whatever domain
the dashboard covers:

> Think of it like a kitchen preparing a meal. **Bronze** is the raw
> delivery of ingredients — nothing is cooked yet, and everything is kept
> even if some of it won't end up being used. **Silver** is washing and
> chopping each ingredient individually — nothing is combined yet. **Gold**
> is where the actual cooking and recipe happen — ingredients get combined,
> and this is where the specific business "recipe" lives (whatever the
> domain's real logic is — a classification rule, a calculated total, a
> status translation). The **final layer** is the plated dish, ready to
> serve — a straightforward shaping of what came out of Gold for a specific
> audience, with nothing new being cooked at the table.

## Renaming and schema hygiene

If a layer's schema needs a name change, the underlying platform may not
support a direct "rename schema" operation. A safe procedure that works
regardless of platform:

1. Create the new schema
2. Recreate each table with the identical query, pointed at the new schema
3. Update every downstream consumer's queries to the new schema name
4. Verify each recreated table actually has its query/fields populated — an
   empty definition with nothing set is a silent failure mode worth checking
   for before assuming the migration succeeded
5. Check lineage/dependencies on the old schema's tables before deleting
   anything — confirm nothing else in the warehouse still depends on them
6. Only delete the old schema once every consumer has been confirmed
   migrated and re-verified against real data
