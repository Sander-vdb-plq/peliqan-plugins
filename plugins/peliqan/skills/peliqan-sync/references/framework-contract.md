# Framework Contract (v4)

Single source of truth for the API a sync trio may rely on. The worker-builder
emits a framework that satisfies this; the sync-builder emits syncs that call
only these. If this file and the code disagree, `assets/worker_template.py` wins.

**Framework is versioned.** The worker carries `FRAMEWORK_VERSION = "4"`. Data
apps are single files (no cross-app import), so the framework is embedded and
the skill owns the canonical copy. When it changes, bump the version here and in
the template; the sync-builder upgrades a stale worker's framework block in place
(see "Upgrading" below). This is what prevents the drift seen between the first
two hand-built workers.

**v3 (breaking fix): warehouse objects must be CATALOG-REGISTERED.** Verified on
a live account: `dbconn.insert`/`dbconn.fetch` only work on tables registered in
Peliqan's catalog. Raw DDL via `dbconn.execute` creates the Postgres object but
does NOT register it — insert/fetch then 404 (`ERROR_TABLE_DOES_NOT_EXIST`)
while the DDL "succeeded", producing v2's failure mode: a green-looking run that
writes to the target with **no link rows** (duplicates on every run) and still
advances bookmarks. v3's `ensure_schema` therefore: runs the idempotent DDL →
probes the tables with a real fetch → if unregistered, calls
`pq.refresh_schema(connection_name=dw_name, schema_name=LINK_SCHEMA)` (a
synchronous catalog sync) → re-probes → **raises** if still unregistered, and
`process_all` runs no syncs on that failure. Two traps to never reintroduce:
do not create the link table with `dbconn.write()` (write-created tables are
pipeline-flagged and `dbconn.insert` is rejected on them), and do not treat a
failed link write as a warning-only event when the whole table is unusable.

**v4 (data-loss fix): incremental drains MUST use `>=`, never strict `>`.**
Verified on a live account (2026-07-15): source timestamps have **second
granularity**, so several records routinely share one timestamp (bulk imports,
batch edits). With a strict `>` filter, any run that stops mid-cluster —
`TEST_LIMIT`, a crash, a page cap — sets the bookmark to that shared second and
the NEXT run skips the remaining records at that same second **permanently**:
no link row, no error row, no dead-letter entry, and their children orphan-freeze
forever. (Live incident: 3 products silently lost this way; recovered only by a
manual bookmark rewind.) The rules:

- Where the sync writes the filter itself (a GraphQL/SQL/OData `updated-at`
  filter), use `>=` against the bookmark.
- Where a connector controls the comparator (`list(bookmark=...)`) and its
  strictness is unknown, pass `bookmark_with_overlap(bookmark)` (§3) instead of
  the raw bookmark.
- The boundary records this re-reads each run are absorbed by the framework's
  idempotency (hash-skip / already-linked) — a handful of no-ops per run is the
  designed cost.
- This is system-agnostic: it applies to ANY source with second-granularity
  change timestamps (Shopify `updatedAt`, Odoo `write_date`, Salesforce
  `SystemModstamp`, SAP `CHANGEDAT`, ...). A new system reference
  (`references/systems/<system>.md`) must state the timestamp granularity and
  whether the comparator is under our control.

## 1. Naming conventions

- **sync_name**: `<sourcesys>_<sourceobj>_to_<targetsys>_<targetobj>`.
- **fns**: `fieldmapping_*`, `process_<one record>`, `process_<sync>` (the loop).
- **Two systems fixed at creation, named concretely everywhere** (`shopify_*` /
  `odoo_*`). No `system_a`/`system_b` indirection — a different pair is a
  generation-time rename, not a runtime abstraction.

## 2. Warehouse objects — **per worker**, created by it (`ensure_schema`, first thing in `process_all`)

Each worker (system pair) owns its **own** link table, run log and views, named
after its pair via top-of-file constants (`LINK_SCHEMA`, `PAIR`, `LINK_TABLE =
f"link_{PAIR}"`, `RUNS_TABLE = f"runs_{PAIR}"`). This is what lets several
workers for different pairs coexist — a shared table with fixed `shopify_id`/
`odoo_id` columns can't serve a Klaviyo⇄Odoo worker. All the helper queries build
the table name from `_LT = f"{LINK_SCHEMA}.{LINK_TABLE}"`, so a sync never names
the table itself.

`{LINK_SCHEMA}.{LINK_TABLE}` (e.g. `link_tables.link_shopify_odoo`), append-only,
shared by all syncs **in this worker**:

| column | meaning |
| --- | --- |
| `id` (bigint PK) | unique per row, `_next_link_id()` |
| `sync_name`, `action` (insert/update), `status` | see below |
| `attempt` (int) | failure count; **set by the framework**, not the sync |
| `shopify_id` / `odoo_id` | the two identities (text) — named for this pair |
| `store_id` / `company_id` | nullable; multi-store scoping (§8) |
| `shopify_source_hash` / `odoo_source_hash` | `stable_hash` of owned fields, per direction |
| `shopify_source_json` / `odoo_source_json` | full source record, for replay |
| `error_detail`, `timestamp` | error text (error rows only); ISO `...Z` |

`status` values: `ok`, `source_error`, `target_error`, and **`dead`** (poison —
reached `MAX_ATTEMPTS`, stops retrying). Effective link = latest `ok` per
(sync_name, id). Append-only: every upsert is a new row.

Also created (per worker): `{LINK_SCHEMA}.{RUNS_TABLE}` (run log) and pair-suffixed
views `v_link_shopify_latest_{PAIR}`, `v_link_odoo_latest_{PAIR}`,
`v_dead_letter_{PAIR}`, `v_run_summary_{PAIR}`.

*Legacy:* the first hand-built worker used `link_tables.link_table`. To reuse that
data, set `LINK_TABLE = "link_table"` and `RUNS_TABLE = "sync_runs"` instead of
the per-pair names.

## 3. Helper API (a sync may call ONLY these)

Config/const: `TEST_LIMIT`, `MAX_ATTEMPTS`, `MULTI_STORE`, `FRAMEWORK_VERSION`,
`_limit_reached(processed)`.

State/bookmark: `get_bookmark`, `set_bookmark`, `sort_by_updated_at(records, ts_field=)`,
`advance_bookmark(hw, ts)`, `bookmark_with_overlap(bookmark, fmt=, seconds=)` (v4 —
for comparators we don't control), `simulate_bookmark_run(records, current, limit, ts_field=)`.

Hash: `stable_hash(dict) -> str` — canonical JSON md5 over the **owned/mapped
fields**. Use this; never concatenate `str(a)+str(b)`.

Link table:
- `insert_link_row(sync_name, action, status, shopify_id=, odoo_id=,`
  `shopify_source_hash=, odoo_source_hash=, shopify_source_json=,`
  `odoo_source_json=, store_id=, company_id=, error_detail=) -> bool`
  (attempt counting and promotion to `dead` happen **inside** this call.)
- `find_target(sync_name, shopify_id, store_id=, company_id=) -> (odoo_id, shopify_source_hash)`
- `find_link_by_odoo(sync_name, odoo_id, store_id=, company_id=) -> (shopify_id, odoo_source_hash)`

Ops/reliability:
- `record_run(sync_name, started_at, counts, status=, detail=)` — called by
  `process_all`; a sync just returns its counts dict.
- `replay_source(sync_name, process_one, statuses=, include_dead=, limit=)` —
  re-drives error/dead rows from stored source JSON; `process_one(sync_name, record)`.
- `reconcile_deletes(sync_name, live_source_ids, apply_delete, side=)` — diffs
  ok-links vs live ids, calls `apply_delete(link_row)` per orphan.
- `ensure_schema()` — idempotent bootstrap of everything in §2: DDL **plus
  catalog registration** (`pq.refresh_schema`) **plus a fetch-probe verify**.
  Raises if the tables stay unregistered; `process_all` then runs no syncs.

Transport (in the worker): Shopify `gid_to_numeric`, `shopify_list_incremental`,
`shopify_graphql`, `graphql_user_errors`; Odoo `odoo_object_add/update/search`,
`odoo_search_read_incremental`, `extract_new_id`; and `is_ok(result)`.

## 4. The 6 steps (every single-record function)

1. **Validate source** → `insert_link_row(..., "source_error", ...)`, return.
2. **Lookup link** (`find_target` / `find_link_by_odoo`) → target id + last hash → insert vs update.
3. **Map + hash** (`fieldmapping_*` → `(shape, stable_hash(owned))`). Equal hash → skip. Shape may be one record or richer (header + lines, multiple models).
4. **Writeback** — one target record per call; fan out / branch / multi-model as the domain needs.
5. **Handle response** — `is_ok`; for GraphQL also `graphql_user_errors` (functional error on a 200). Attempt/`dead` promotion is automatic in step 6.
6. **Append link row** — `ok` with hash on success; else an error status with `error_detail` and no hash (retries next run until `dead`).

Return `"ok" | "skip" | "error"` from the single-record fn so the loop can count.

## 5. The loop (`process_<sync>`)

- `bookmark = get_bookmark(sync_name) or <epoch in this source's format>`.
- Read the changed set (incremental), `sort_by_updated_at(..., ts_field=<source field>)`.
- Loop with `_limit_reached`; per-record try/except that records a row and continues; `advance_bookmark` only over reached records; orphan-freeze on a parent dep.
- **Return `{"processed": n, "errors": e, "skipped": s}`** so `process_all` logs the run.
- Register in `SYNC_REGISTRY`: `{"name": SYNC_X, "run": process_x, "replay": <optional>}`, in dependency order (parents first, Shopify→Odoo before Odoo→Shopify).

## 6. Bookmark rules

Each source has its own timestamp field/format (see the system references,
`references/systems/`). **Never compare across sources.** Advance only over the
contiguous processed prefix. Orphan-freeze: freeze at the first child whose
parent isn't linked yet.

**Comparator (v4): `>=`, never strict `>`.** Timestamps have second granularity
and clusters of equal timestamps are normal; a truncated run + strict `>` loses
the rest of the cluster permanently (see the v4 header note). Self-written
filters use `>=`; unknown-comparator paths (connector `list(bookmark=)`) get
`bookmark_with_overlap(bookmark)`. Boundary re-reads are absorbed by hash-skip.
The pure test `scripts/test_bookmarks.py` asserts this behaviour — run it
offline before deploying a worker or a new sync.

## 7. Transport conventions

One record per mutation/write call; a single-row search may return a dict
(normalise to list); paginate reads with the source cursor; prefer a
cursor-paged `fetch_changed_*` with an explicit `>=` filter over a connector
`list(bookmark=)` for large sets. **System-specific transport quirks (query
syntax, id shapes, functional-error detection on 200s, permission failure
modes, implicit filters) live in `references/systems/<system>.md`** — the
sync-builder reads the two files for the worker's pair; this contract stays
system-agnostic.

## 8. Multi-store / multi-company

Off by default (`MULTI_STORE = False`); the `store_id`/`company_id` columns exist
regardless so the key never needs retrofitting. When `True`, pass `store_id` /
`company_id` to `insert_link_row` and the `find_*` calls scope on them. Decide at
build time (a single `shopify_id ↔ odoo_id` mapping breaks the moment the same
product exists in two stores).

## 9. Reliability summary (all generic; every sync inherits)

Two-layer idempotency (hash-skip + append-only link) · attempt counter → `dead`
poison handling · `replay_source` from stored snapshots · run log + monitor views
· delete-reconciliation primitive · nothing aborts the run.

## 10. Known limitations / open items

- **Single-variant assumption** (`variants[0]`) — multi-variant matcher is next
  (see the `[SCRATCH] inspect multivariant mapping` app).
- **Delete semantics** (unlink vs archive) are still a per-sync decision; the
  detection primitive (`reconcile_deletes`) now exists, the handler does not.
- **Ingest-layer dedupe** (duplicate webhook events landing in the DWH) is
  separate from writeback dedupe and depends on confirming webhook-relay mode —
  a build-time question, not yet a helper.

## 11. Upgrading a worker's framework

When `FRAMEWORK_VERSION` here is newer than a worker's, the sync-builder should
replace everything from the header down to the `>>> SYNC INSERTION POINT <<<`
marker with the current template's framework, preserve the syncs and
`SYNC_REGISTRY` below the marker, and confirm the diff before `update_data_app`.
