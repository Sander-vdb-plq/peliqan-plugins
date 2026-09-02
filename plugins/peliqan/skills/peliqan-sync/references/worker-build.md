# Workflow: Build a Worker

Goal: a runnable, **sync-empty** worker (framework v4) for one system pair.
It pins down two things for life — the two systems and the warehouse objects —
then syncs are added with the sync-builder.

## Platform fact that shapes this

Peliqan data apps are **single files**; there is no runtime import of shared code
across apps (a local bundler can flatten a multi-file app at deploy time, but
that needs CI outside the MCP flow). So the framework is **embedded and
versioned**: the skill owns the canonical copy (`FRAMEWORK_VERSION`), and stale
workers are upgraded in place (contract §11).

## Inputs to gather

1. **System pair** + connection names. Default: Shopify (`'Shopify V2'`) ⇄ Odoo
   (`'Odoo'`). Confirm the names match the account.
2. **Account label** — header only (`{ACCOUNT_LABEL}`).
3. **Build-time options** (set the constants near the top of the template):
   - `MULTI_STORE` — `True` if multiple Shopify stores / Odoo companies (scopes
     the link keys). Leave `False` otherwise; the columns exist either way.
   - `MAX_ATTEMPTS` — retries before a row is marked `dead`.
   - `TEST_LIMIT` — cap per sync per run while testing (`None`/`0` = all).
   - Cadence: if latency-sensitive syncs (stock, fulfilment) need to run more
     often than eventual-consistency ones (payouts, gift cards), note it — it may
     mean more than one scheduled worker or a per-sync gate later.
4. **Per-worker link table** — no manual setup: `ensure_schema()` creates,
   **registers and verifies** this worker's own objects on first run —
   `{LINK_SCHEMA}.link_{PAIR}`, `runs_{PAIR}`, and the pair-suffixed monitor
   views — and migrates a pre-existing table by adding
   `attempt`/`store_id`/`company_id`/`error_detail`. Registration matters:
   `dbconn.insert/fetch` only see catalog-registered tables, so after the DDL
   `ensure_schema` probes the tables and runs
   `pq.refresh_schema(connection_name=dw_name, schema_name=LINK_SCHEMA)` when
   needed; if they stay unregistered it raises and no sync runs (contract v3).
   Set `PAIR` (e.g. `"shopify_odoo"`, `"klaviyo_odoo"`) at the top of the
   template; every object name derives from it, so multiple workers for different
   pairs never collide. To reuse the original worker's existing rows instead of a
   fresh per-pair table, set `LINK_TABLE = "link_table"` / `RUNS_TABLE = "sync_runs"`.

## Steps (default Shopify ⇄ Odoo)

1. Read `references/framework-contract.md` (v4) AND the two system references
   for the pair (`references/systems/<A>.md`, `references/systems/<B>.md`) —
   the emitted code must satisfy the contract; the system files answer the
   per-source questions (timestamp format/granularity, comparator control,
   error detection). If a system file does not exist, create it from
   `references/systems/_checklist.md` with the dev — never guess the answers.
2. Take `assets/worker_template.py` as-is (already concrete + runnable). Only
   substitute `{ACCOUNT_LABEL}` and set the build-time constants.
3. Leave the SYNC INSERTION POINT, the empty `SYNC_REGISTRY`, and `process_all`
   intact. Framework, transport, DLQ, run log and views are already in place.
4. Sanity-check: imports; run `python scripts/test_bookmarks.py <worker.py>`
   (pure, offline — asserts the v4 equal-timestamp rules); `ensure_schema()`
   runs first and its **fetch-probe passes** (the first run's log should show
   either a clean pass or one `refresh_schema` line — an abort means the
   account needs attention, not the syncs); `process_all()` runs with an empty
   registry and prints an empty run summary; `FRAMEWORK_VERSION` is set.

## Peliqan platform gotchas (any pair)

- `update_data_app` replaces the script **wholesale** — always send the full
  file, then fetch it back (`get_data_app`) and verify **byte-identical**
  against the local build before trusting the deploy.
- A Peliqan API call that errors (transient 500) may still have EXECUTED the
  action — verified live: two "failed" run attempts had in fact run and
  advanced bookmarks. After an API error, check run history / state before
  retrying anything non-idempotent.
- Bookmarks live in **app state** (`pq.get_state`/`set_state`), survive script
  updates, and can be edited via the MCP state tools — a bookmark rewind + one
  run is the standard recovery for records a drain missed (hash-skip makes the
  re-scan cheap). State writes shallow-merge at the top level: always write the
  full `bookmarks` object, never a single key.
- Large MCP tool results land as files (`/mnt/user-data/tool_results/*.json`)
  — parse them, don't guess their structure.

## Steps (a DIFFERENT system pair, e.g. SAP ⇄ Salesforce)

As above, plus a mechanical rename of the two system tokens — set `PAIR` (names
the link table / run log / views), the variables + `pq.connect(...)` names, the
`shopify_*`/`odoo_*` columns in `ensure_schema` / `insert_link_row` / `find_*` /
views, the transport helpers (new read/write for the new systems; keep `is_ok`),
and each source's bookmark field/format. The bookmark field/format, comparator
control and error-detection answers come from `references/systems/<system>.md`
(one per side); fill in missing ones via `_checklist.md` before generating
transport code. Contract §6 (v4) applies regardless of pair: `>=` drains, or
`bookmark_with_overlap` where the comparator is opaque.

## Deliver

- Create via Peliqan MCP `create_data_app`, named `"<A>-<B> data sync - Worker"`,
  or hand back the script. Safe to schedule immediately (does nothing until a
  sync is registered).

## Do NOT

- Bake any single sync's logic into the framework.
- Reintroduce a `system_a`/`system_b` indirection.
- Change the helper argument names the sync trios depend on except as part of a
  full, consistent different-pair rename (that is the contract).
