# DAX-to-SQL Comparison Checklist

A checklist of specific mistakes that are easy to make when translating a
Power BI DAX measure into SQL. Each item below describes a *pattern* of
mistake worth checking for — treat these as things to verify on whatever
fields and formulas the current project actually has, not as a fixed list of
field names to look for. The specific column names, category codes, or
category labels will be different in every project; the underlying traps are
the same.

## 1. Per-unit vs. per-line (or per-record) fields

A field whose name suggests a "price" or "rate" (anything like `UnitPrice`,
`NetPrice`, `Rate`, or a translated equivalent in another language) is very
often a **per-unit value that does not scale with quantity**. A field whose
name suggests a total "amount" is more often the **true line or record
total**, already multiplied out.

Don't assume which is which from the name alone — field naming conventions
vary a lot between systems, and a "price"-sounding field can sometimes
already be the total, or vice versa.

**How to check, definitively:** query real rows where the relevant quantity
or multiplier is greater than 1, and check whether the candidate field's
value stays constant (per-unit) or scales proportionally (a total). This is
a five-minute query that eliminates the guesswork entirely.

## 2. The same-looking formula name can mean different things across related tables

Don't assume that because Table A's version of a calculated field uses one
combination of source fields, Table B's similarly-named field must use the
same combination. Two tables can use a calculated column with an identical
name (e.g. both called "gross amount" or "net total") where one is built
from a line total and the other from a per-unit value — this is a real
pattern seen in production Power BI models, not a hypothetical edge case.
Check each table's literal formula independently rather than inferring one
from the other, even when they look like they should obviously match.

## 3. Sign conventions can differ by table, even within the same source system

Some tables store one category of record (e.g. revenue-type postings) as
negative and another category (e.g. cost-type postings) as positive — a
common "ledger" or "debit/credit" convention. Other tables in the very same
system might store everything as plain positive values with no sign
encoding meaning at all. Don't assume a sign convention is universal across
an entire source system; check the actual signs on real rows, table by
table.

## 4. A measure with no visible filter can still only apply to a subset in practice

A DAX measure that looks unconditional (e.g. simply negating a sum with no
`FILTER` or `CALCULATE` condition) might still only ever be *displayed* for
one specific category within a chart, because the categorization is
happening elsewhere in the report — a separate calculated column, or an
implicit filter context supplied by the visual's own legend/grouping — not
inside the measure's formula itself.

**How to verify:** ask for (or compute) the measure's actual output broken
out by every category it's shown against. If the transformation applies
identically to every category, but only one category is ever routed to a
"different" bucket in the visual, the categorization logic lives outside
the measure you're looking at.

## 5. Two similar-sounding measures can deliberately use different scopes

A chart-level measure and a KPI/gauge-level measure that both appear to
compute the same kind of split (e.g. two different views of "revenue vs.
cost") may intentionally use different scopes — one might classify every
record into one of two buckets (a catch-all rule), while the other only
considers a specific, narrower whitelist of categories and silently excludes
everything else. Do not "fix" one measure to be more consistent with a
sibling measure without first confirming, from the literal DAX of both, that
they're actually supposed to follow the same rule. If in doubt, ask for the
specific formula behind each one rather than assuming from a similar
measure's behavior.

## 6. Filter conditions that look equivalent often aren't

A condition like "less than 1" and a condition like "exactly 0" look
interchangeable only if the underlying value is always a whole number. If a
partial completion, partial invoice, or partial delivery can produce a
fractional value, these two filters diverge — a fractional value like 0.5
would pass a "less than 1" check but fail an "exactly 0" check. Check for
the actual presence of fractional values in the real data before treating
these as interchangeable, and don't assume every occurrence of this pattern
across a dashboard should use the same version — a table-level display
filter and a KPI's internal calculation filter can legitimately use
different versions of a similar-looking condition, by original design.

## 7. Numeric status or type codes can differ between closely related resources

Two related entities in the same source system that both track a "status"
concept (e.g. two different kinds of orders, or an order vs. its related
invoice) may use entirely different numeric code schemes, even though they
look like they should share one obvious mapping. Verify the actual distinct
codes present in each table independently — don't reuse a code mapping
confirmed for one resource on a different, only superficially similar
resource.

## 8. Prefer a pre-translated text field over a numeric code mapping, if one exists

Sometimes the safest translation isn't to build a numeric code mapping at
all, but to reuse a field the source system already provides with
human-readable values (e.g. a "status description" field already containing
words rather than codes). If such a field exists and reliably contains a
small, known set of values, using it sidesteps any risk of getting a numeric
code mapping wrong — check whether a field like this exists before building
a `CASE WHEN` from numeric codes.

## 9. Slicers, filters, and matrix groupings each bind to one specific field — don't substitute a "friendlier" one

A dimension table often has both an ID/code column and a description/name
column (e.g. `CustomerID` vs. `CustomerName`, or a cost-center code vs. its
label), and a matrix might group rows by the description while the slicer
filters by the ID from the *same* table. Check each visual's literal
`queryRef`/`prototypeQuery` binding independently — don't assume a slicer
and a matrix on the same page use the same column just because they look
related, and don't substitute the "friendlier" column for the one actually
bound, even if the two columns happen to hold identical values for most
sample rows. When the warehouse column with the same role as the bound
field is used as a dashboard filter (e.g. a multiselect), filter on that
literal column; a readable label can be layered on for display, but the
underlying filter values must match the source field.

## 10. Fixed-width padding on ERP-sourced code/ID columns

ERP systems frequently store short codes in fixed-width text fields, padded
with trailing spaces (e.g. `"ABC123  "` instead of `"ABC123"`). A join or
`WHERE code = 'X'` against such a column will silently return zero rows —
no error, just an empty result that looks like "this data doesn't exist"
rather than "this data is padded." Before joining on any code/ID column
from an ERP-sourced dimension table, check it directly:
`SELECT '[' || code || ']' FROM table LIMIT 5` — if you see trailing
characters inside the brackets, `TRIM()` both sides of the join/comparison.

## 11. Prefer the direct relationship path over a separately-assigned key, even if the source report doesn't

When a fact table's row is genuinely linked to a project/entity through one
relationship path (e.g. an invoice line to the order line it settles), but
that same fact table also carries its own, separately-assigned key for the
same entity (e.g. an invoice header's own project/cost-center field,
assigned by whoever processed it), prefer the direct relationship path when
building the warehouse join — don't join through the separately-assigned
key just because the source report does. The separately-assigned key can
easily diverge from the true relationship (e.g. an invoice gets tagged with
a default administrative cost center rather than the specific project its
line items belong to), which causes real, populated data to disappear from
a report's cards or measures once filtered — not because the data is
missing, but because the join path used to reach it doesn't reliably
reflect the real relationship. If the source PBIX exhibits this (cards
blank while the underlying line-item data is clearly present and correct),
that's a limitation of the source report's own model, not something to
faithfully reproduce — link through the reliable path and treat the more
complete result as the intended correction.

## 12. A single-value pick (MIN, etc.) over multiple distinct values hides ambiguity

A card/measure that does `MIN()` (or similar single-value pick) over a raw
column, evaluated where the current filter context spans multiple distinct
values, will silently show one arbitrary value in the source report with no
indication that other values exist. When replicating this in a dashboard,
prefer an explicit "Multiple" (or similar) label over literally reproducing
the arbitrary single-value pick — it's more honest about what the
underlying data actually contains and prevents someone from mistaking one
cherry-picked status for the full picture. Confirm this by checking the
real underlying rows first (do the values genuinely differ?) rather than
assuming "Multiple" is correct without checking.

## 13. Pattern-based scope rules almost always have exceptions — ask

When a dimension's scope is defined by a pattern (a regex, a code prefix,
"contains a digit," etc.), proactively ask the person whether there are
specific individual codes — numbers, alphanumeric IDs, or particular
entries — they want included or excluded beyond what the pattern alone
would capture. A single pattern rule is rarely the complete picture of
which entities actually belong in scope: some entries may violate the
general pattern but still be legitimate (an internal/operational entry that
doesn't follow the normal ID scheme), while others may match the pattern
but not actually belong (an ID reused for something other than its apparent
category, like an item or inventory code that happens to look like an
entity ID). Don't wait for the person to notice a wrong inclusion or
exclusion in the rendered dashboard and correct it reactively — ask
directly once the pattern is identified: "Are there any specific
codes/numbers that should be included or excluded beyond this rule?" This
applies to any dimension a dashboard scopes by pattern (projects, cost
centers, categories, regions, product lines), not just the specific case
that prompted this note.

## 14. A confirmed scope change doesn't guarantee a better match — report the actual result

When a person confirms a business-scope change (e.g. "yes, include X"),
apply it, but immediately show the before/after impact on whatever
verification numbers are in progress — don't assume confirmation means the
match will improve. Business correctness and matching a specific reference
snapshot are two different, sometimes conflicting things (e.g. a person may
confirm that an entity legitimately belongs in scope, while its inclusion
still makes a specific aggregate comparison diverge further, for unrelated
reasons like differing time ranges). Report the actual resulting numbers
plainly and flag the conflict if one exists, rather than treating the
person's confirmation as proof the numbers now match.

## General verification method

For any calculated field, before considering it correct:

1. Get the literal formula text — not a summary or description of it
2. Identify the real underlying column names for every field it references
3. Query real rows with varied inputs (multi-quantity records, non-zero
   secondary amounts, different category values)
4. Hand-compute the expected result for those rows using the literal formula
5. Compare against the SQL's actual output for the same rows
6. If possible, cross-check against an actual screenshot or export of the
   original report showing the same record, for the strongest confidence
