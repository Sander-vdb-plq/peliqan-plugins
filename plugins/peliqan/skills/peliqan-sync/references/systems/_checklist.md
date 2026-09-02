# System checklist (template for a new system reference)

This checklist is what keeps the skill pair-independent: the framework contract
never names a system's quirks, and the builders read exactly two files from
this directory — one per side of the pair. Adding SAP, Salesforce, Klaviyo or
any other system = answering these questions in a new `<system>.md` here.
If a question cannot be answered yet, say so explicitly in the file and treat
it as a build-time question for the dev — do NOT guess.

Copy this file to `<system>.md` and fill in every row:

| question | why it matters |
| --- | --- |
| Change-timestamp field + exact format | drives the bookmark format; per-source namespace (contract §6) |
| Timestamp granularity | seconds ⇒ equal-timestamp clusters ⇒ the v4 `>=` rule applies in full |
| Comparator under our control? | self-written filter → `>=`; opaque connector bookmark → `bookmark_with_overlap` |
| Record id shape | what goes in the link-table id column; any prefix/gid to strip |
| Incremental read mechanism | cursor / offset / delta-token paging; page caps |
| How a functional error looks on a 200 | the response layers `is_ok` alone does not cover (silent-empty-set traps) |
| Writeback mechanism + batching rule | contract §7: one record per call — name the API that enforces or violates this |
| Permission / access failure modes | which errors mean "misconfigured, freeze bookmark and self-heal", not "empty source" |
| Implicit server-side filters | anything the API hides by default (archived/inactive records) |
| Data-model impedance vs the other side | template-vs-variant splits, parent/child hierarchies, derived values (kit stock) |
| Delete semantics options | archive / deactivate / hard delete / GDPR flows — per-sync decision, but list the options |

Known systems: `shopify.md`, `odoo.md`. Examples of the level of detail
expected: both existing files record *verified live* behaviour, not
documentation summaries — mark anything unverified as such.

Placeholders deliberately NOT shipped for SAP/Salesforce: an empty or guessed
system file is worse than none, because the builders would trust it. Create
the file the first time a pair actually needs it, from this checklist plus the
dev's answers.
