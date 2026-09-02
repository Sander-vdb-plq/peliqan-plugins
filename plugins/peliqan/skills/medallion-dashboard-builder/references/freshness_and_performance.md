# Data Freshness Diagnosis & Load-Time Hygiene

These two concerns are separate from correctness (covered in
`dax_comparison.md` and the main SKILL.md steps 3–4) and separate from each
other — a dashboard can have either problem, both, or neither, independent
of whether its formulas are right.

## Data freshness: ruling it out as a hypothesis

A rebuilt dashboard can diverge from the source report even when every
layer, formula, and filter has already been verified correct against the
DAX. When that happens, treat data freshness as a distinct, first-class
hypothesis — not a fallback to reach for only after everything else has
failed.

**Why a "healthy" pipeline doesn't mean "current" data.** A connector's
scheduled sync can report success on every run while still failing to pick
up updates on specific individual records — incremental ("what changed
since last time") sync logic can silently miss a row's update depending on
how the source system tracks change, even though the pipeline job itself
never errors. Don't infer data freshness from run-history status alone; it
answers "did the job complete," not "does every row reflect the source's
current state."

**How to check, concretely:**
1. Isolate to one disputed record (reuse the single-record isolation
   technique from step 4) — an aggregate mismatch has too many combined
   unknowns to diagnose staleness specifically.
2. Compare that record's own `modified`/`updated_at`/equivalent timestamp
   (whatever the source table exposes) against the connector's own run
   history for that table. A record last modified long before the most
   recent *successful* run, while the source report shows different
   current values for that same record, is a concrete staleness signal —
   not proof, but a specific, checkable one.
3. Where possible, compare multiple fields on that one record (quantities,
   statuses, amounts) rather than just the one that first looked wrong — a
   staleness explanation should account for every field that's off, not
   just one; if it only explains one field and not the others, keep
   looking.

**Once the evidence points to staleness, stop at diagnosis — don't propose
performing a resync.** Triggering a resync is a bigger action (it touches
the connector, has cost/permission implications, and mechanics that vary
per system) that sits outside what this skill covers. The job is to give
the user a clear, evidence-backed explanation of what's likely going on,
not to offer to fix it. Lay out plainly:
- Which specific record(s) show the mismatch, and what the mismatch is
- The timestamp evidence (record's last-modified vs. the connector's
  recent successful run history) that points to staleness rather than a
  formula or scope problem
- That this is a likely cause based on the pattern observed, not a
  certainty — other explanations (e.g. a watermark/incremental-logic bug,
  or a scope/permissions issue on specific records) remain possible if a
  resync (whenever and however the user chooses to run one) doesn't close
  the gap

Let the user decide what to do with that explanation — whether and when to
resync, who to involve, or whether to investigate further — rather than
steering toward a specific next action.

**If the user reports back after resyncing (or otherwise addressing it) on
their own,** re-run the exact same single-record comparison used to
diagnose the issue — not just the aggregate. The explanation isn't
confirmed until the specific disputed record(s) reflect current values; an
improved aggregate alone doesn't prove the diagnosis was correct.

**If the gap persists anyway, that itself is new evidence** — it means the
cause probably isn't simple staleness after all, and points back toward
something like a watermark/incremental-logic bug or a scope/permissions
issue on specific records. Treat this as the next diagnostic clue, not a
reason to fall back to adjusting formulas that were already verified
correct.

## Load-time hygiene: a separate pass from correctness

A dashboard that returns correct numbers but takes too long to load on
first visit is still an unfinished job. Once correctness is verified, run
a separate pass for load-time hygiene — don't assume slowness means the SQL
itself is "too complex" without checking first, since the actual cause is
very often one of two generic, checkable things:

**a) Full-table pulls filtered down after the fact.** Check whether each
data-loading function fetches an entire source table with no `WHERE`
clause, then discards most of the rows in application code afterward (e.g.
a date range or a not-blank/scope filter applied only after the data has
already arrived). If so, the fix is to push that same filter into the SQL
query itself, so only the rows actually used ever cross the network. This
is safe specifically because it's the *same* filter, just applied earlier
— but verify that equivalence explicitly rather than assuming it: confirm
the column being filtered in SQL is exactly the column that was being
filtered downstream, on exactly the same dataset, since a subtle mismatch
(e.g. filtering a table in SQL that a sibling table was deliberately *not*
filtered on downstream) silently changes what the dashboard shows.

**b) Sequential loads where the sources are independent.** If a dashboard
issues several independent data pulls one after another, wall-clock load
time is the sum of every pull, not the slowest one. Running independent
loads concurrently (e.g. a thread pool) can cut this to roughly the
slowest single load — but check first whether the underlying connection
object is safe to share across concurrent calls; if not, give each
concurrent load its own connection rather than reusing one across threads.

**Present these as an interactive checklist, not an unprompted change.**
Not every dashboard has both problems — a small table doesn't need SQL-side
filtering, and a single data source doesn't need parallelization — and the
person may want to see the diagnosis before authorizing a change to a
working dashboard. Surface it as a short interactive choice where the
platform supports it (otherwise a plain question), e.g.:
- Push filters into SQL (show which table(s) and how many rows this
  removes from the transfer)
- Parallelize the independent data loads
- Both
- Neither — just show me the diagnosis for now

**Confirm the change is provably neutral on correctness immediately after
applying it.** Compare row counts and a few spot-checked values before and
after the optimization — a performance change should be neutral by
construction, and this is a cheap, concrete way to confirm that rather
than assume it.
