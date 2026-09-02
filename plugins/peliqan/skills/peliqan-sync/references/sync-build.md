# Workflow: Add a Sync

Goal: turn one sync specification (a row of the requirements sync matrix +
a field mapping) into a trio of functions and wire it into an existing worker.

## Inputs to gather (the sync spec)

This maps 1:1 onto the requirements-doc sync matrix. For the sync, collect:

| input | example | notes |
| --- | --- | --- |
| source system + object | Shopify `Order` | drives which read helper + timestamp |
| target system + model(s) | Odoo `sale.order`, `sale.order.line` | |
| direction | Shopify → Odoo | which `find_*` to use |
| source of truth / owned fields | Shopify owns header, taxes | **hash covers only these** |
| field mapping | title→name, ... + transforms (e.g. `weight_to_kg`) | the body of `fieldmapping_*` |
| identity / lookup key | `find_target(sync, shopify_id)` | how the link row is keyed |
| trigger | event / scheduled / hybrid | informs polling; loop is scheduled either way |
| parent dependency | order line needs order; variant needs template | → orphan-freeze if yes |
| delete semantics | archive / unlink / n/a | only if the delete flow is in scope |

If a field is owned by the *other* system, either omit it from the mapping or
seed it once and never again (see sync 2 — "seed once then Odoo-owned").

Ask only for what the matrix row doesn't already answer. If the dev pastes a
matrix row + a field list, that is usually the whole spec.

## The three examples are a pattern, not a menu

`assets/sync_examples/product_syncs.py` holds the only three syncs that exist
today. They are **reference implementations of the pattern**, not the catalogue
of allowed sync types. Any domain in the requirements matrix — and others — is
in scope: orders, POS/pickup, fulfilment, refunds/returns, payments, payouts,
stock by location, kit/BOM stock, customers, deletes, gift cards, backfill.

Do **not** force a new domain into "sync 1, 2 or 3." Instead, keep the 6-step
contract (which holds for every sync) and compose the **mechanisms** the domain
needs. The variation lives inside step 3 (mapping may produce several target
writes) and step 4 (writeback may branch or hit multiple models):

- **1 → many target writes.** One source record fans out to several target
  records/models. An Order → `sale.order` + N `sale.order.line` + `res.partner`
  + `account.tax`. The `fieldmapping_*` returns the whole shape; `process_*`
  writes parent then children; the link row keys the parent, child links can be
  keyed too if they must be addressed later.
- **Branch on a source field.** A Refund with `restock: true` → return
  `stock.picking`; `restock: false` → `account.move` credit note only. Payment
  `financial_status` (paid/partially_paid/pending/voided) drives the invoice
  state, while the raw `Transaction` records feed the journal entry — two
  outputs from related sources, not one collapsed step.
- **Derived / computed values.** Kit stock is the phantom `mrp.bom`'s least
  available component, not `stock.quant` for the kit — compute before writeback.
- **Parent/child identity.** Customers as parent `res.partner` + child delivery/
  invoice contacts; reconcile on `partner_id + type`, not just email.
- **Parent dependency (orphan-freeze).** Any child whose parent may not be
  linked yet (see sync 2).
- **Multi-model / two-source.** A domain the matrix shows as one row may need
  more than one pipeline step (payments vs payouts; transactions vs status).
- **Reconciliation / backfill.** A scheduled sweep with numeric tolerances and
  an exception workflow, rather than per-record upsert.
- **Delete detection.** A SQL diff after a full sync (link row with no live
  source) → unlink vs archive per the decided semantics.

Borrow the closest example for the plumbing (which `find_*`, which source
drain, single-line GraphQL, one-record-per-call), then add the mechanisms above.
If a domain needs a genuinely new *framework* capability (not just new mapping/
branching), that belongs in the worker + a contract bump — not hidden in a sync.

## Steps

1. Read `references/framework-contract.md` (the API you may call) AND the two
   system references for this worker's pair (`references/systems/<A>.md`,
   `<B>.md`) — they answer the source drain questions (timestamp field/format/
   granularity, comparator control → `>=` vs `bookmark_with_overlap`, how a
   functional error looks on a 200, implicit filters). Pick the example whose
   **plumbing** is closest as a starting point (direction + source drain):
   A→B create/update (sync 1), A→B with parent dep / seed-once (sync 2),
   B→A writeback + change-date drain (sync 3). Then compose the mechanisms the
   domain actually needs — don't assume it looks like the example.
2. Fetch the current worker script (Peliqan MCP `get_data_app`).
3. Write the trio:
   - optional query/mutation constant(s), single-line
   - `fieldmapping_*` → `(target_shape, stable_hash(owned_fields))`; the shape
     can be one record or a structure (header + lines + …). **Use `stable_hash`
     over a dict of the owned fields — never `str(a)+str(b)` concatenation.**
   - `process_<one record>` → the 6 steps (contract §4); **return
     `"ok" | "skip" | "error"`**. DLQ/`dead` promotion is automatic inside
     `insert_link_row` — don't hand-roll retry counting.
   - `process_<sync>` → the loop (contract §5): correct `ts_field`/epoch, orphan-
     freeze if there's a parent dep, and **return `{"processed","errors","skipped"}`**.
4. Add a `SYNC_* = "..."` constant near the other sync constants.
5. Insert the trio at the SYNC INSERTION POINT (before `SYNC_REGISTRY`).
6. Register an entry in `SYNC_REGISTRY`, in dependency order (parents first,
   Shopify → Odoo before Odoo → Shopify):
   `{"name": SYNC_X, "run": process_x, "replay": <process_one or adapter, optional>}`.
   Add a `replay` handler when replay from the stored source JSON is meaningful
   (simple 1:1 syncs: the `process_<one record>` directly; fan-in syncs: a small
   adapter that resolves parents first — see `replay_one_variant`). Omit it when
   the normal drain already reprocesses (see sync 3).
7. If the domain has a delete flow, add a handler and call `reconcile_deletes`
   (detection is generic; unlink-vs-archive is your handler's decision).
8. Update the worker (Peliqan MCP `update_data_app`) or return the edited script.
   If the worker's `FRAMEWORK_VERSION` is older than the contract, upgrade the
   framework block first (contract §11).

## Self-check before delivering

- Hash uses `stable_hash` over **only** the owned/mapped fields (a field the
  other system owns must not be in the hash, or you get write loops).
- One target record per writeback call (fan-out = several calls).
- `source_error` vs `target_error` used correctly; GraphQL `userErrors` checked;
  no hand-rolled retry counting (DLQ/`dead` is automatic).
- Single-record fn returns `ok/skip/error`; loop returns the counts dict.
- Bookmark advances only over reached records; correct field/format; never
  compared against another source's bookmark; drain filter is `>=` (or
  `bookmark_with_overlap` on an opaque comparator) per contract §6 — run
  `python scripts/test_bookmarks.py <worker.py>` before delivering.
- Registered in `SYNC_REGISTRY` in the right dependency position, with a `replay`
  handler where meaningful.
- No new helper invented that isn't in the contract — if you need one, it belongs
  in the worker (bump the version), not hidden in a sync.

## This is code generation, not config

Be honest with the dev: each sync is ~3 real Python functions, not a config
row. The skill enforces the pattern and reuses the framework; it does not make
a sync a one-liner. The payoff is that every sync inherits idempotency,
hash-skip, retry, error rows and bookmarks for free.
