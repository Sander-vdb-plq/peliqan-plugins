---
name: medallion-dashboard-builder
description: Build a dashboard (Streamlit or similar) on a data warehouse that replicates an existing Power BI report, using a Bronze/Silver/Gold/consumer-layer medallion architecture, with the Power BI report's PBIX file (or its DAX formulas) as the source of truth to match against. Use this skill whenever the user wants to migrate, rebuild, or "port" a Power BI (or similar BI tool) report to a custom dashboard, wants to set up a medallion architecture for a new data domain, mentions comparing dashboard output against a PBIX file or DAX measures, or asks to verify that a rebuilt dashboard's numbers match an existing report. Also trigger this when the user uploads or references a .pbix file alongside a request to build or check a dashboard, even if they don't use the word "medallion" or "migration" explicitly. Applies regardless of the underlying source system (ERP, CRM, custom database, etc.) or target platform.
---

# Medallion Dashboard Builder

Rebuilds a Power BI report as a custom dashboard, using a layered
(medallion) data architecture, with the original PBIX/DAX as ground truth to
verify against at every step. The core discipline of this skill is: **never
assume a formula is correct just because it looks like standard textbook
logic — always check it against the source report's actual DAX, and always
verify the result against real data, not just the SQL syntax being valid.**

## When this skill applies

Use this whenever:
- The user wants to migrate an existing Power BI report to a custom dashboard
- The user is setting up a new medallion architecture (Bronze/Silver/Gold) for
  a data domain and wants a dashboard on top of it
- The user shares a PBIX file, DAX measures, or screenshots of a Power BI
  report and wants a matching implementation built or checked
- The user asks whether a dashboard's numbers "match" or are "correct"
  relative to an existing report

## Two very different situations, depending on what the user shares

This skill covers building a dashboard end-to-end, but the actual path
depends heavily on whether the user can provide something to verify against.
Check which situation you're in before assuming the workflow below applies
in full:

**A PBIX file, DAX formulas, or an existing report is available (in whole
or in part).** This is the situation the verification-heavy steps below
(3 and 4) are written for — use the PBIX/DAX as ground truth, and don't
guess at business logic the customer's own report already defines
explicitly. Even partial access helps: a handful of DAX measures pasted in
chat, or a few screenshots of specific visuals, are enough to verify the
calculations those specific visuals depend on, even without the full PBIX.

**No PBIX, no DAX, no reference report exists — this is a dashboard built
from scratch.** In this case, steps 3 and 4 (extracting and verifying
against DAX) don't apply, because there's nothing to verify against. Instead:
- Business logic decisions (what counts as revenue, how a status is derived,
  what a KPI formula should be) need to come from the user directly, or from
  reasonable domain-standard defaults stated explicitly as assumptions
- Treat every calculated field as an assumption to confirm with the user
  before treating it as final, the same way a PBIX-derived formula would be
  treated as an assumption if the DAX weren't available to confirm it against
- The medallion architecture (step 1), dashboard build (step 5), and
  documentation (step 7) steps still apply in full — only the "verify
  against an existing report" parts of steps 3–4 don't have a target

Every dashboard built this way will look different depending on which of
these two situations applies, and it's worth confirming with the user up
front which one they're in, rather than assuming a PBIX exists (or assuming
one doesn't, if they haven't mentioned it yet but might have one).

## Let the user know what's ahead

Before starting step 1, give the user a short, plain-language preview of the
stages ahead. This is a multi-stage process with several built-in pauses to
ask questions — which PBIX page to target, what a specific DAX formula does,
what visuals to build if there's no PBIX, whether a discrepancy is confirmed
correct before moving on — and a short preview up front means those pauses
read as expected progress, not as the process stalling or wandering off
without explanation. For example:

> "I'll set up the four data layers first, then check your PBIX (or ask what
> you want if there isn't one) — including what its charts/tables actually
> look like, not just the numbers — verify every formula against real data
> before building anything, then build the dashboard to match, and document
> what we did at the end. I'll check in at a few points along the way."

Don't restate every numbered step verbatim — a short summary of the stages
in plain language is more useful to a non-technical reader than an itemized
implementation checklist. Repeat a shorter version of this if the
conversation resumes after a long gap, so the person doesn't have to
reconstruct where things left off.

## The core workflow

### 1. Establish the medallion layers first

Before writing any dashboard code, make sure the data itself is structured in
four layers. If they don't exist yet, build them in this order:

- **Bronze** — raw data exactly as the source system sends it. Append-only,
  never transformed. This is the safety net; nothing gets recalculated here.
- **Silver** — one cleaned table per source entity (deduplicated, typed,
  nulls handled). Still no cross-source joins or business logic — just one
  ingredient at a time.
- **Gold** — sources unioned, mapping joins applied, and **every business
  rule lives here and only here**: what counts as revenue vs. cost, how a
  calculated amount is derived, how a raw status code becomes a label. This
  is the layer that matters most for correctness, because every downstream
  consumer inherits whatever is decided here.
- **Consumer-facing layer** (often named after the domain, e.g.
  `dm_<domain>`) — a straightforward passthrough or light reshaping of Gold,
  using `fct_`/`dim_` naming where applicable. Its job is to be what the
  dashboard actually reads from. Never put new business logic here — if a
  rule needs to change, it should only need to change in Gold.

(Some written architecture references use different labels for these same
four jobs — most notably calling the business-logic layer "Core" and
reserving "Gold" for the consumer-facing layer instead. If the organization
has a formal architecture document, check it and ask which convention is
actually in use before assuming either one — in practice, teams sometimes
build using one convention (e.g. "Gold" for business logic) even when their
own written documentation specifies the other, so the existing schema names
already in the warehouse are the more reliable signal to follow than the
document alone.)

See `references/medallion_architecture.md` for the full rationale and a
kitchen-analogy explanation that works well when relaying this to a
non-technical customer.

### 2. If a PBIX file itself is shared, confirm which report/page it's for before building anything

A PBIX file commonly contains multiple pages/tabs, each representing a
different report or dashboard (e.g. a sales overview page, a finance page, a
projects page, all in the same file). Don't assume which one the user wants
rebuilt just because a PBIX was uploaded — ask which specific page or
dashboard they're targeting, unless it's already obvious (e.g. only one page
has real content, or they've explicitly named it). Building out the wrong
page's visuals wastes significant effort and is easy to avoid by asking one
clarifying question up front.

Once the target page is confirmed, also compare the underlying **data**
referenced by that page's visuals against what's actually available in the
warehouse — not just the visual layout. A visual's fields might reference a
table or column that doesn't exist yet in Bronze/Silver, and that gap needs
to surface before committing to a build plan.

**Ask for a screenshot of the actual rendered page, in addition to the PBIX
file itself.** Extracting `Report/Layout` JSON and the DAX from the data
model tells you *what fields* each visual is bound to and *what type* of
visual it is (card, slicer, matrix, etc.) — but it does not show what the
page actually looks like rendered: colors, conditional formatting, which
slicer is a dropdown vs. a list, which matrix rows are expanded by default,
or truncated card text that reveals a formula's real output on real data.
A rendered screenshot is also a second, independent way to catch a
field-mapping mistake — e.g. a screenshot showing a slicer values list full
of short codes is a signal that the slicer is bound to an ID column, not a
description column, even before checking the layout JSON confirms it.
Treat the screenshot as ground truth alongside the DAX, and re-check any
visual whose rendered output doesn't match what the layout JSON implied.

**Catalog every visual's type and styling, not just its data bindings —
replicating "look and feel," not only numbers, is part of the job.** For
each visual, record its type (card, gauge, matrix/pivot table, pie chart,
slicer type, etc.) and its styling (colors, conditional formatting,
indentation/hierarchy) before writing any dashboard code, and replicate the
same visual metaphor on the target platform rather than a "close enough"
substitute — a PBIX matrix's bold-subtotal-plus-indented-lines pattern
should become an equivalent hierarchy-preserving table, not a flattened
dataframe; a half-donut gauge should look like one, not a generic progress
bar. If no PBIX or screenshot exists, ask the user directly what visuals
they want rather than guessing. See `references/pbix_visual_replication.md`
for the full checklist and rationale, and `references/streamlit_patterns.md`
for tested implementations (SVG gauges, stable color scales, the indented
matrix-table pattern) if the target platform is Streamlit.

### 3. Extract the ground truth from the PBIX / DAX, not from assumptions

This is the step most likely to go wrong if rushed. Do not assume a
calculation follows standard textbook logic (e.g. "gross = net + tax") just
because that's the conventional definition — Power BI reports frequently use
field combinations, category whitelists, or per-unit vs. per-total values
that deviate from what looks "correct" on paper, and the whole point of this
exercise is parity with the existing report, not independently reinventing
what "correct" should mean.

For each visual/KPI in the Power BI report:
1. Get the literal DAX formula (ask the user to paste it from Power BI's own
   Modeling/Measures view if the PBIX file itself isn't available)
2. Identify every field it references, and find that field's real name in
   the warehouse — friendly names shown in the Power BI model often differ
   from actual column names in the source tables, so confirm this mapping
   explicitly rather than guessing from similarity
3. Check whether each referenced field is a per-unit value or a total value
   by querying real multi-quantity rows and checking whether it scales with
   quantity — never assume from the field name alone
4. Write the SQL as a literal translation of the DAX, preserving whatever
   sign conventions and filter conditions the DAX uses, even if they look
   inconsistent between related measures — that inconsistency may be
   intentional in the original report, not a mistake to "clean up"

**This applies to non-measure visuals too — slicers, filters, and matrix
row/column groupings each bind to one specific field, and that exact field
must be used, not a semantically-similar substitute** (e.g. a slicer bound
to an ID column while a matrix groups by that same table's description
column). Beyond that binding trap, watch for several other easy-to-miss
patterns: fixed-width padding on ERP-sourced codes silently returning zero
rows on a join; preferring a direct relationship path over a
separately-assigned key even if the source report doesn't; a `MIN()`-style
single-value pick hiding real ambiguity across multiple distinct values;
pattern-based scope rules (a regex, a code prefix) almost always having
individual exceptions worth asking about; and a confirmed scope change not
guaranteeing a better match against a reference snapshot. See
`references/dax_comparison.md` for the full checklist with concrete
detection/verification steps for each of these, plus the core patterns
(sign conventions, per-unit vs. per-total fields, category whitelists vs.
catch-all classifications, numeric codes differing between related
resources).

### 4. Verify every formula against real data before trusting it

Never consider a SQL translation "done" just because it runs without error.
For each calculated field:
1. Query a handful of real rows where the calculation's inputs vary
   meaningfully (e.g. quantity > 1, a non-zero secondary amount, a record
   from a less-common category that might behave differently)
2. Hand-compute what the DAX would produce for those same rows
3. Compare — if they don't match, the SQL translation is wrong even though
   it executed successfully

If the user can share real screenshots of the Power BI report for a specific
record, cross-check the SQL output against those exact displayed numbers.
This is the strongest form of verification available, since it confirms the
whole chain end-to-end rather than just the formula in isolation.

**When a numeric mismatch has more than one unresolved unknown (e.g. both a
formula question and a scope/filter question), debug them one at a time by
isolating a single entity — don't try to resolve everything at the
aggregate level.** Aggregate totals combine every unknown at once: if a
formula is wrong AND the row scope is wrong, the aggregate error could come
from either, both, or could even partially cancel out, making it impossible
to tell which fix is working. Pick one single, real record (one customer,
one order, one project) that the person can independently verify against
the source report, and compare every field for that one record line by
line. This isolates the formula question from the scope question
completely — a single record has no ambiguity about which rows are
"in scope," so a mismatch there can only be a formula problem. Only move to
aggregate-level verification once each component has been confirmed
correct in isolation.

Keep verification queries in a dedicated schema (e.g. `CHECK`) rather than
deleting them after use — they're valuable for future audits and for
answering "how do we know this is right?" questions later.

**The `CHECK` schema will keep growing across a long build or many rounds of
debugging — periodically ask the user whether they want to clean it up,
rather than either deleting entries unprompted or letting the count grow
unchecked indefinitely.** A good moment to ask is at a natural pause (e.g.
once a page's visuals are all verified, or once a specific discrepancy is
fully resolved): mention how many check queries have accumulated and ask
whether to keep all of them, remove the ones tied to already-resolved
issues, or leave cleanup for later. Never delete a verification query
without the user confirming first — a query that looks safely superseded
might still be the reference someone reaches for later to answer "how do we
know this is right?", and that judgment call belongs to the user, not to
an assumption that older checks are no longer needed.

**When a calculation checks out, say so explicitly and specifically —
don't just move on silently.** A confirmation is only useful if it's
concrete. State plainly:
- Which record(s)/rows were checked
- What was compared (the DAX formula against the SQL translation; the
  hand-computed value against the actual output; a PBIX screenshot's
  displayed number against the dashboard's)
- The actual matching values side by side, not just "this looks correct"

A verified item is worth naming as verified, the same way a discrepancy is
worth naming as a discrepancy — both are informative, and skipping the
confirmation makes it hard for the user (or a future reader of the `CHECK`
schema) to tell "checked and correct" apart from "not checked yet."

**Treat the transition out of verification as an explicit checkpoint, not
an assumption.** Once a visual/KPI is confirmed, ask whether to continue to
the next one, or — once everything on the target page/report has been
verified — whether to move on to building (step 5) or to documentation
(step 7), rather than proceeding on your own judgment of what's done. This
keeps the person deciding the pace, and gives them a natural point to
redirect (e.g. "actually check this other measure too") before build work
starts on top of the verified formulas.

### 5. Build the dashboard reading only from the consumer layer

The dashboard's code (Streamlit, or whatever the target platform is) should only ever query the consumer-facing layer
(the consumer-facing layer's tables), never Gold or Silver directly. This keeps a clean
separation: business logic changes happen in Gold, display logic changes
happen in the dashboard script.

**This rule applies to every table in the consumer layer, not just the
dashboard script — check each one, not just what the script directly
queries.** It's possible to keep the dashboard script itself clean (only
querying `dm_*` tables) while still violating the architecture inside one
of those `dm_*` tables' own definitions — e.g. building a "helper" table
under time pressure that reaches directly into Silver, joins across
sources, or applies a business rule, because it was the fastest way to fix
an immediate problem. Silver has no cross-source joins, and the consumer
layer is a thin passthrough — this holds for *every* object in the
consumer schema, not just the ones the dashboard code visibly touches.
Periodically audit each consumer-layer table's actual query definition, not
just the dashboard script: `SELECT * FROM GOLD.x` is fine; anything
referencing `SILVER.*` or containing `UNION`/business logic from a
`dm_*`-schema table means that logic needs to move up into its own Gold
object, with the consumer-layer table reduced back to a passthrough.

**Before inventing a UI solution for a tricky layout problem (logos,
headers, custom widgets), check whether another dashboard already deployed
in the same account solved it** — a sibling dashboard's script is a faster,
more reliable source of a working pattern than guessing from general
framework knowledge.

**Naming convention:** name the deployed dashboard app/interface with the
word "Dashboard" at the end (e.g. "Sales Pipeline Dashboard", not just
"Sales Pipeline").

**Ask what the dashboard's title should be** — don't assume it from an
unrelated textbox in the source report (which may be the report suite's
overall branding rather than a page-specific name), and don't auto-translate
it.

**Ask before assuming anything about a logo/branding image** — whether the
user wants one at all, and if so, where it should come from (PBIX-embedded,
fresh upload, or a URL). See `references/dashboard_build_gotchas.md` for
the full logo-handling workflow, including why manually relaying a large
base64 string is a real source of silent image corruption, the
native-upload-control pattern that avoids it, and the specific CSS pattern
(`position: fixed`) that renders a header logo reliably.

That same reference file also covers three easy-to-skip consistency checks
worth doing once the dashboard looks functionally done: verifying a filter
doesn't visually leak a column it isn't supposed to display, checking
numeric formatting/rounding against the source report rather than letting
raw float precision show, and checking column display names against the
source report or a sibling dashboard for naming consistency — each is
independent of whether the underlying value is already correct.

See `references/streamlit_patterns.md` for reusable, tested code patterns:
multi-select filters with a "clear all" button, hand-drawn SVG gauge
charts, a stable custom color scale for pie/donut charts, and the
row-matrix table pattern (bold subtotal rows with indented line items).

### 6. Distinguish "wrong" from "different but intentional"

Not every discrepancy between your first-pass implementation and the DAX is a
bug. Two measures in the same Power BI report can deliberately use different
scopes or rules for legitimate reasons (e.g. a margin gauge that only
considers a specific whitelist of categories, versus a pie chart that
classifies every category into one of two buckets). Before "fixing" something
to be more consistent with a sibling measure, check whether the original DAX
actually specifies that inconsistency on purpose. If in doubt, ask the user
whether they have the DAX for the specific measure in question rather than
assuming from a similar one.

### 7. Produce two documents: a technical reference, and an easily-explained one

Produce two artifacts, not a single document trying to serve both purposes:

- **A technical reference document** (a markdown or Word document) with raw
  SQL, field-level mappings, and literal DAX comparisons — written for
  whoever maintains this system later.
- **An easily-explained document**, written in plain language, using
  analogies where helpful (e.g. Bronze/Silver/Gold as stages of preparing a
  meal), with no SQL or code visible — written for someone who needs to
  understand and sign off on the assumptions, not maintain the pipeline.

Never let one document serve both jobs — simplifying a technical reference
loses the precision it needs, and leaving code in the easily-explained
document creates a barrier that discourages actually reading it.

**This skill only prepares these as files and hands them to the user — it
does not publish, create, or update anything in Notion, a wiki, or any
other external documentation tool on its own,** even if such a tool happens
to be connected and available. Preparing documentation content and taking
an action in a separate connected system are two different things; this
skill covers only the former. If the user separately asks for the content
to be pushed into Notion (or anywhere else), that's a distinct request to
handle on its own terms — including checking whether that action needs
explicit confirmation before anything gets created or modified there —
not something this skill does as an automatic last step.

### 8. Rule out data freshness as its own hypothesis before trusting a formula fix

A rebuilt dashboard can diverge from the source report even when every layer,
formula, and filter has already been verified correct against the DAX. When
that happens, treat **data freshness** as a distinct, first-class hypothesis
— not a fallback to reach for only after everything else has failed. A
"healthy" pipeline (every scheduled run completing successfully) doesn't
mean every row's data is current — incremental sync logic can silently miss
updates on specific records. Isolate to one disputed record and compare its
own last-modified timestamp against the connector's run history for a
concrete, checkable signal.

**Stop at diagnosis — don't propose or perform a resync.** That's a bigger
action (connector access, cost/permission implications) outside what this
skill covers. Lay out the evidence plainly (which record, what's mismatched,
why it points to staleness) and let the user decide what to do with it,
rather than steering toward resyncing, waiting, or investigating logs.

See `references/freshness_and_performance.md` for the concrete steps and
how to handle both what happens next if the user resyncs, and what it means
if the gap persists anyway.

### 9. Check load-time hygiene as its own pass, separate from correctness

A dashboard that returns correct numbers but takes too long to load is
still an unfinished job. Once correctness is verified (steps 3–4), run a
separate pass for load-time hygiene — don't assume slowness means the SQL
is "too complex" without first checking for two generic, common causes:
full-table pulls that get filtered down only after the fact in application
code, and independent data loads run sequentially instead of concurrently.

**Present any fix as an interactive checklist, not an unprompted change** —
not every dashboard has both problems, and the person may want to see the
diagnosis before authorizing changes to a working dashboard. After applying
anything, confirm it's provably neutral on correctness (same row counts and
values as before).

See `references/freshness_and_performance.md` for how to check for each
cause concretely, and the specific fix pattern for each (pushing filters
into SQL, and parallelizing independent loads safely).

## A note on iteration

This workflow is not linear in practice — expect to revisit earlier
assumptions as more of the real DAX or real data comes to light. A formula
that looked correct in step 3 may need reverting after step 4 surfaces new
evidence (this has happened: an initial "fix" to a margin calculation was
reverted after the user produced the literal DAX showing the original
approach was actually correct). Treat each new piece of ground truth — a DAX
snippet, a screenshot, a raw data query — as authoritative over your own
prior reasoning, and be willing to say "I was wrong, here's why" rather than
defending an earlier conclusion.
