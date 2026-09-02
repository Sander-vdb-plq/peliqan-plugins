---
name: peliqan-sync
description: "Build and extend Peliqan Reverse-ETL sync workers between two systems (e.g. Shopify ⇄ Odoo) on the data warehouse, as ONE single-file data-app. Use when scaffolding the base code for a system pair, or adding a single sync (orders, stock, customers, fulfilment, refunds) to an existing worker."
---

# Peliqan Sync

Generates the code for Peliqan warehouse-side sync workers, following the
battle-tested pattern from the live Shopify⇄Odoo worker. One worker per system
pair runs every sync between those two systems through `process_all()`; each
sync is a trio of functions on a shared framework (link table + bookmarks +
idempotency + error containment).

**Output shape is fixed: ONE runnable data-app script.** A Peliqan data-app is a
single file with no cross-app import, so the framework is embedded in every
worker and deployed with `create_data_app` / `update_data_app`. Never split a
worker into modules, never introduce a bundler, a repo layout or a build step,
and never tell the dev to edit anything other than the app. (Running one worker
across many clients from a module tree with a bundler is a valid but *different*
product — out of scope for this skill.)

## First: always read the contract + the pair's system references

Before emitting any code, read **`references/framework-contract.md`**. It is the
single source of truth for the helper API, the link-table schema, the 6-step
per-record contract, the bookmark rules, and the transport conventions. Both
workflows below must satisfy it. If generated code and the contract disagree,
the contract (and `assets/worker_template.py`) wins — **except** where the
"Build-time playbook", "Production learnings" and "Keep the scaffold lean"
sections below say otherwise: those are verified against workers that have run
live and they supersede the v4 files on disk.

The contract is deliberately **system-agnostic**. Everything system-specific
(timestamp field/format/granularity, comparator control, id shapes, how a
functional error hides in a 200, implicit filters, permission failure modes)
lives in **`references/systems/<system>.md`** — read the two files matching the
worker's pair (e.g. `shopify.md` + `odoo.md`). For a system with no file yet
(SAP, Salesforce, ...), create one from `references/systems/_checklist.md`
together with the dev — never guess the answers; an unanswered checklist row is
a build-time question.

The framework is **versioned** (`FRAMEWORK_VERSION`) because Peliqan data apps
are single files with no cross-app import — it's embedded, and the skill owns the
canonical copy. When adding a sync to a worker older than the contract, upgrade
its framework block in place first (contract §11). v4 adds the `>=` drain rule
(equal-second bookmark boundary — a strict `>` filter permanently loses records
after a truncated run; live incident 2026-07-15). v3 gave every sync, for free:
a **per-worker link table** (named for the system pair, so multiple workers for
different pairs coexist) that is **created, catalog-registered and verified on
first run** (raw DDL alone leaves tables invisible to `dbconn.insert/fetch` —
see contract v3 note), DLQ/`dead` poison handling, a run log, monitor views and
stable hashing.

## Route to one of two workflows

Check the live account first (`list_data_apps`, filter names on `sync|worker`):
no worker for the pair = scaffold; a worker exists = add a sync to it. Only if
that is still ambiguous ask the single question "scaffolding a new worker, or
adding a sync to an existing one?" and proceed.

- **Building the base code / scaffolding a worker for a system pair**
  → read and follow **`references/worker-build.md`**.
  Output: a runnable, sync-*empty* worker (the shared framework only).

- **Adding one sync** (orders, stock, customers, fulfilment, refunds, …) to an
  existing worker → read and follow **`references/sync-build.md`**.
  Output: a trio of functions + a `SYNC_*` constant + one registration tuple,
  inserted into the current worker script.

A dev typically builds the worker once, then runs the sync workflow many times.
When the dev asks for "the sync" in one go ("zet sync op tussen X en Y"), ask
ONE multi-select question (which syncs) plus ONE safety question (TEST_LIMIT and
SYNCS_ENABLED for the first run) and build worker + syncs in a single pass.

## Assets & scripts

- `assets/worker_template.py` — the sync-agnostic framework (v4), placeholdered
  for the system pair. The worker workflow starts here, then applies the
  production learnings and the lean rules below.
- `scripts/test_bookmarks.py` — pure offline test of the bookmark rules
  (equal-timestamp truncation). Run it on every worker before deploying:
  `python scripts/test_bookmarks.py <worker.py>`. It exec's four pure helpers
  out of the worker — `sort_by_updated_at`, `advance_bookmark`,
  `bookmark_with_overlap`, `simulate_bookmark_run` — so those four stay in every
  worker, with the canonical signatures from the template.
- `assets/sync_examples/product_syncs.py` — the three real product-sync trios
  (verbatim from the live worker) plus the real Shopify/Odoo transport helpers:
  - sync 1: SYSTEM_A → SYSTEM_B, create/update
  - sync 2: SYSTEM_A → SYSTEM_B, parent dependency + seed-once (orphan-freeze)
  - sync 3: SYSTEM_B → SYSTEM_A, GraphQL writeback, write_date drain

## Build-time playbook (verified 2026-09-02, account 2792, Shopify V2 ⇄ Odoo V2)

The order of operations that took a 5-sync worker from zero to two green live
runs in one session. Every step is there because skipping it cost a run or a
redeploy that day — follow it in this order.

1. **Inspect the account before asking the dev anything.** `list_connections`
   (exact connection names — here `'Odoo V2'` / `'Shopify V2'`, not the
   template's `'Odoo'`), `list_data_apps` (existing worker?), `list_schemas`
   (database id), and a 3-row `get_table_data` on the source tables in the DWH
   (paid test orders? customers? what an Odoo product looks like). This answers
   half the sync spec and shows which test data exists.
2. **Probe the target with a throwaway data-app BEFORE building a sync that
   depends on a module or field.** One `search_read` on `ir.module.module`
   (`stock`, `sale`, `sale_management`, `account`) and one on each field you
   intend to read. Live: `stock` was *uninstalled* in peliqan.odoo.com (Odoo 18)
   so `product.product.qty_available` did not exist — the stock sync was built,
   then switched off. A 10-line probe would have said so first. Delete the probe
   app afterwards (`delete_data_app`).
3. **Register the link schema ONCE with the MCP `create_schema` tool (database
   id from `list_schemas`) before the first run.** `pq.refresh_schema` requires
   `schema_name` and 404s (`ERROR_SCHEMA_DOES_NOT_EXIST`) on a schema that is
   not in the catalog yet; a connection-level refresh does not exist. Once the
   schema is registered, `ensure_schema` registers and verifies its own tables.
   Without this step the first two runs abort (correctly) on the v3 guard.
4. **Write the worker locally and run three offline checks**: `py_compile`,
   `pyflakes` (ignore only the undefined `pq`/`st`) and
   `scripts/test_bookmarks.py`. Then a **fake-platform smoke test**: exec the
   worker with a stub `pq` (state dict, `dbconnect`, `connect`, `refresh_schema`),
   a stub `st` (log collector) and fake connections that answer the exact
   response shapes (`{"status":"success","detail":{"data":...}}` for Shopify,
   `{"status":"success","detail":{"result":...}}` for Odoo). Run it three
   times: run 1 creates, run 2 must write NOTHING (only `no change in hash ->
   skip` / `already linked`), run 3 propagates one changed record. It caught two
   bugs before the first live write.
5. **Deploy with `create_data_app` and verify against the returned
   `raw_script`** (large results land as a file — parse with python). The API
   strips the trailing newline: compare with `.rstrip("\n")`, then treat as
   byte-identical. Same after every `update_data_app` (wholesale replace; the
   script is pasted inline, so keep the worker lean).
6. **First live run with `run_data_app(mode='shell')`.** The MCP call times out
   after 60 s while the run keeps going: on a timeout do NOT re-run — read
   `get_data_app_runs` + `get_data_app_run_logs`. (A double-triggered run showed
   up live; only the schema guard made it harmless.)
7. **Second run = idempotence proof.** Expect the `>=` boundary re-reads to
   settle as `n x no change in hash -> skip` / `already linked`, bookmarks
   moving, no duplicate writes. Only then hand over. Scheduling and
   `TEST_LIMIT = 0` are the dev's call — do not set them.

**Odoo facts the v4 files did not know (treat as an amendment to
`references/systems/odoo.md`):**

- **A functional error travels INSIDE a 200.** The `Odoo V2` connector returns
  `{"status": "success", "detail": {"jsonrpc": "2.0", "error": {"data":
  {"name": "builtins.ValueError", "message": "Invalid field ..."}}, "result":
  null}}`. `is_ok()` MUST also reject a dict whose `detail.error` is set;
  otherwise a broken `search_read` reads as "0 records" and the run stays
  green. Put `detail.error.data.name + message` in the error row.
- The generic transport (`odoo_api.add/update("object", {...})`,
  `odoo_api.apicall("", odoo_model=, odoo_method="search_read",
  payload=[domain], additional_params={fields, limit, offset, order})`) works
  unchanged on the `odoo_v2` server type.
- Odoo 18: `detailed_type` is gone, `type` is `consu` / `service` / `combo`;
  `qty_available` exists only with the `stock` module installed.
- `sale.order` create takes lines inline as `order_line: [[0, 0, {...}]]`;
  `date_order` wants `YYYY-MM-DD HH:MM:SS`; leave orders in draft unless the
  dev asks for `action_confirm`.

## Production learnings — apply on every build

From the live Shopify⇄Odoo worker after months in production. Where these
contradict the v4 files on disk, these win.

**Framework additions:**

- **A per-batch link cache, with write-through.** `prefetch_links(sync_name,
  direction, keys)` loads only the current page's keys (chunks of ~500,
  `SELECT DISTINCT ON (key) ... WHERE status='ok' AND key IN (...)`), caches
  misses as `(None, None)` so "in the cache" means "we know", and `find_*` falls
  back to the old query for keys never prefetched. `insert_link_row` updates the
  cache on `ok` rows — that part is *correctness*, not speed: a child sync must
  see the parent link an earlier sync wrote in the SAME run. *(Without it, one
  live run did 280+ queries for zero writes.)*
- **Aggregate skips.** `note_skip(sync_name)` in the record function,
  `write_skips(sync_name)` from `process_all` (also in the except path): one line
  per sync instead of one per record. Keep the literal text
  `"no change in hash -> skip"` — it is the idempotence proof in the log.
- **A run summary that answers an incident.** Per sync: status, **duration**,
  processed/errors/skipped, aligned on the longest name — plus a separate
  **Bookmarks** block printing `before -> after` or `unchanged`. A bookmark that
  does not move means "nothing new" OR "frozen on an orphan", and nothing else
  tells those apart.
- **`SYNCS_ENABLED`** in CONFIG: one dict, per-sync on/off, reported in a caption
  at the top of the run including which syncs are OFF. Keep every run-summary
  tuple the same arity — a shorter tuple on the disabled branch crashed a live
  run with a `ValueError` that read as "Worker aborted unexpectedly".
- **`ensure_schema` probes once** and only re-probes after a `refresh_schema`
  actually ran. The rest of the v3 behaviour (DDL → probe → refresh → raise) is
  unchanged; the schema itself is registered once via `create_schema` (playbook
  step 3).
- **`ensure_custom_fields`** — only when the pair declares extension fields (see
  the lean rules): create them in the target idempotently, with ONE batch
  existence check and a per-field fallback. The *list* is pair-specific and lives
  next to CONFIG; the *mechanism* is framework.
- **Transport**: prefer a cursor-paged drain that writes its own `>=` filter over
  a connector `list(bookmark=)` — one generic `shopify_drain(query, root,
  bookmark, extra_filter=, page_size=)` serves products, variants and orders;
  drop `shopify_list_incremental` when nothing calls it. It must treat a 200
  carrying top-level errors (`data: null`) as a loud `source_error` — otherwise
  an ACCESS_DENIED reads as "0 records". Add `find_or_create(model, domain,
  record, cache, key, strict=)`: `strict=True` raises where the write cannot
  proceed without it, `strict=False` warns and caches `None` so the failure is
  not retried per record.

**Sync rules — answer these per mapping row:**

- **Ownership is per FIELD, not per sync.** Seed-once fields are skipped on an
  already-linked record; source-owned fields need their own write path that also
  runs on linked records, with a diff check so repeat runs write nothing. Orders:
  header Shopify-owned (re-pushed on hash change), lines seeded once — state it
  in the sync's header comment.
- **Never push a value the source may not have set.** *(Live: records created
  without a price → the target's default of 1.0 became the "owner" value → 18
  real webshop prices wiped.)* A threshold guard, plus: a push direction only
  goes on once the source is demonstrably populated — backfill, prove, pin the
  hash, plan the re-drive. Stock: a `STOCK_SKIP_ZERO_QTY` guard on by default.
- **Check write-through to a shared parent** before seeding a field (a
  per-variant price wrote through to the shared template price and would flatten
  its siblings).
- **Expensive side effects get their own change signal**, not the record hash —
  track the image URL in its own field and download only when *that* changed.
- **Fan-out children get their own sync name** as a separate identity space in
  the link table: link rows yes, registry entry no (e.g. `SYNC_CUSTOMERS` under
  the orders sync, keyed on the Shopify customer id or `guest:<email>`).
- **Extending a hash re-drives every linked record once.** Say so and state the
  procedure: reset the bookmark, force the stored hash, run, verify the counts.
- **Prefetch per page, not per run** — the generator already paginates — and
  prefetch the parent syncs' links the loop resolves, not only its own.

**Dropped from the baseline** (in the v4 contract, never used in production):
multi-store / `store_id` / `company_id` scoping, `replay_source`,
`reconcile_deletes`. Generate one only when asked, and say what it costs: every
unused helper is code that must be read and kept consistent at every later
change.

## Keep the scaffold lean (review of a generated worker, 2026-09-02)

A sync-empty scaffold ships the whole helper API unused — that is the contract,
not bloat. These parts are NOT contract and go only when needed:

- **Custom-fields block only when `CUSTOM_FIELDS` is non-empty.** With an empty
  list, `_model_id_cache` / `_existing_custom_fields` / `ensure_custom_fields`
  and the call in `process_all` are ~60 dead lines. Generate them the first time
  a pair declares an extension field, together with the field.
- **One-line captions.** `st.caption(f"syncs on: {on or 'none'} | off: {off or '-'}")`
  with `on`/`off` computed once — not a six-line `%`-format with nested
  conditionals. The off-list stays: during a staged first run "which sync is
  off" is THE question.
- **No one-caller indirections** (`_columns()` in `prefetch_links`): inline the
  tuple.
- **`simulate_bookmark_run` exists only for the test.** Keep it (14 lines, pure)
  because `scripts/test_bookmarks.py` exec's it and a worker without its
  runnable check is unfinished; drop it the day the test defines its own loop.

And two that a lean review will flag but that STAY — they prevent data loss:

- **The 3× retry around the link-row insert.** A target write that succeeded
  with no link row is the silent-duplicate mode this whole framework exists to
  prevent; the retry plus the error-row fallback are the last line. Not
  negotiable for fewer lines.
- **The monotonic `_next_link_id` guard.** A colliding bigint PK drops a link
  row silently. `time.time_ns()` alone is shorter and not safe against clock
  adjustments.

## Working against the live account

The worker and syncs are Peliqan data-apps (single Python scripts). Use the
Peliqan MCP: `get_data_app` to fetch the current worker before editing,
`create_data_app` for a new worker, `update_data_app` to write a sync back — it
replaces the script wholesale, so verify `raw_script` after deploying. Keep a
`WORKER_VERSION` and a dated changelog block at the top of the script: it is the
only way to read back which version an account runs.

**A run is a write.** Never run a worker "to see what happens" against a live
target; verify with `TEST_LIMIT`, a sandbox pair, or by reading the link table
and the run log.

**Seed the test data before trusting a green run.** Every pair needs a small
seed script — a separate data-app, never the worker — that creates what the syncs
need: stock on the linked products, one paid test order, a customer with
tags/note/address. Bare dev data hides field gaps: a one-line order with no
discount, no shipping cost and no deviating tax exercises none of those mappings,
so those fields stay unbuildable *and* untestable until realistic shapes exist.

**A sandbox is a copy of the app, not a branch.** Copy the worker into a second
data-app with its **own `PAIR`** (own link table, run log, views), a `TEST_LIMIT`
and `SYNCS_ENABLED` off. The trap: a copy on the *same* connections with an
*empty* link table sees the whole catalogue as new and duplicates it into the
live target — so seed its link rows once from the production pair (aborting the
run if seeding fails) and copy the production bookmarks into its state. Isolation
lives in the link data, bookmarks and run history, not in the target systems.

## Scope honesty

Adding a sync is code generation (~3 functions), not a config one-liner. The
value is that every sync inherits idempotency, hash-skip, retry, error rows and
bookmarks from the framework — not that syncs become trivial. Say so. And list
the v1 decisions taken for the dev to review (taxes, draft vs confirm,
single-variant, single-location, line ownership) in the hand-over instead of
leaving them in code comments only.