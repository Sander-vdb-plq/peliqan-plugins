# ============================================================
# SHOPIFY-ODOO DATA SYNC WORKER  ({ACCOUNT_LABEL})
# framework version: 4   (keep FRAMEWORK_VERSION below in sync)
# ============================================================
# Default system pair: Shopify (SYSTEM A) <-> Odoo (SYSTEM B).
# For a DIFFERENT pair, this file is a mechanical rename of the two system
# tokens — see references/worker-build.md ("Different pair"). No generic
# system_a/system_b indirection: a worker is bound to one pair for life.
#
# Data apps are single files (no cross-app import), so this framework is
# EMBEDDED. The skill owns the canonical copy and bumps FRAMEWORK_VERSION;
# the sync-builder upgrades this block in place when a worker is stale.
#
# WHAT THIS APP DOES
# A scheduled Worker that runs every sync between Shopify and Odoo through
# process_all(), driven by SYNC_REGISTRY. Each sync is a trio
# (fieldmapping_* / process_<one record> / process_<sync>). Order: parents
# before children, all Shopify -> Odoo first, then Odoo -> Shopify.
#
# STEPS PER RECORD (the 6-step contract)
#   1 validate source  2 lookup link  3 map + stable hash (equal = skip)
#   4 writeback (1 record/call; may fan out / branch)  5 handle response
#   6 append link row (hash only on ok)
#
# RELIABILITY (all generic, inherited by every sync)
#   - two error statuses: source_error / target_error; an error row carries
#     error_detail + an attempt counter. At MAX_ATTEMPTS a row becomes
#     'dead' (poison record; stops retrying).
#   - replay_source(): re-drives error/dead rows from the stored source JSON.
#   - append-only link table + hash-skip = idempotent replays.
#   - run log (sync_runs) + monitor views for ops (created on first run).
#   - ensure_schema creates, REGISTERS (pq.refresh_schema) and VERIFIES the
#     warehouse objects; an unregistered link table ABORTS the run instead of
#     silently dropping link rows while writing to the target.
#   - nothing else aborts the run: sync-, record- and link-write-level guards.
#
# LINK TABLE  <LINK_SCHEMA>.link_<pair>  (per-worker, append-only, self-created)
#   id | sync_name | action | status | attempt
#   shopify_id | odoo_id | store_id | company_id  (last two nullable;
#     multi-store scoping — see MULTI_STORE below)
#   shopify_source_hash | odoo_source_hash
#   shopify_source_json | odoo_source_json | error_detail | timestamp
#
# TEST — TEST_LIMIT caps processed records per sync per run (None/0 = all).
# ============================================================

import hashlib
import json
import time
import traceback
from datetime import datetime

FRAMEWORK_VERSION = "4"
TEST_LIMIT = 100        # None or 0 = process everything
MAX_ATTEMPTS = 5        # after this many failures a link row is marked 'dead'
MULTI_STORE = False     # True = scope links by store_id/company_id (see find_*)

dw_name = pq.DW_NAME
dbconn = pq.dbconnect(dw_name)
shopify_api = pq.connect('Shopify V2')   # SYSTEM A connection
odoo_api = pq.connect('Odoo')            # SYSTEM B connection

st.title("Shopify-Odoo data sync - Worker")
st.caption(f"framework v{FRAMEWORK_VERSION} · TEST_LIMIT = {TEST_LIMIT if TEST_LIMIT else 'all'} · MAX_ATTEMPTS = {MAX_ATTEMPTS}")

# --- per-worker warehouse objects -----------------------------------------
# Each worker (system pair) owns its OWN link table, run log and views, so
# multiple workers for different pairs never collide and each has correctly
# named id columns. Name them after this worker's pair.
LINK_SCHEMA = "link_tables"
PAIR = "shopify_odoo"                 # this worker's pair; part of every object name
LINK_TABLE = f"link_{PAIR}"          # e.g. link_shopify_odoo
RUNS_TABLE = f"runs_{PAIR}"          # e.g. runs_shopify_odoo
_LT = f"{LINK_SCHEMA}.{LINK_TABLE}"  # convenience for queries
# NOTE: the original hand-built worker used link_tables.link_table. To REUSE
# that existing data instead of a fresh per-pair table, set:
#   PAIR = "shopify_odoo"; LINK_TABLE = "link_table"; RUNS_TABLE = "sync_runs"

ERROR_STATUSES = ("source_error", "target_error")

# --- sync name constants (one per sync; added by the sync-builder) ---
# Convention: "<sourcesys>_<sourceobj>_to_<targetsys>_<targetobj>"


def _limit_reached(processed):
    return bool(TEST_LIMIT) and processed >= TEST_LIMIT


# ------------------------------------------------------------
# Schema bootstrap: link table + run log + monitor views, created AND
# REGISTERED, then VERIFIED (idempotent; safe on first and every later run)
# ------------------------------------------------------------
def ensure_schema():
    """Create and REGISTER this worker's own warehouse objects.

    PLATFORM FACT (verified on a live account): dbconn.insert/fetch only work
    on tables that are registered in Peliqan's catalog. Raw DDL via
    dbconn.execute creates the Postgres object but does NOT register it, so
    insert/fetch return 404 ERROR_TABLE_DOES_NOT_EXIST while DDL "succeeds".
    pq.refresh_schema(connection_name=..., schema_name=...) runs a synchronous
    catalog sync that registers everything in the schema.
    Do NOT create the link table with dbconn.write(): a write-created table is
    pipeline-flagged and dbconn.insert is REJECTED on it ("not allowed for a
    table that is part of a pipeline").

    Order: (1) idempotent DDL  (2) probe the tables via a real fetch
    (3) if unregistered, refresh_schema once and re-probe  (4) still
    unregistered -> RAISE. process_all treats that as fatal and runs no syncs:
    running syncs that write to the target while unable to record link rows is
    the silent-loss mode this guards against (duplicate target records +
    advanced bookmarks, with a green-looking run)."""
    v_shop = f"v_link_shopify_latest_{PAIR}"
    v_odoo = f"v_link_odoo_latest_{PAIR}"
    v_dead = f"v_dead_letter_{PAIR}"
    v_runs = f"v_run_summary_{PAIR}"
    stmts = [
        f"CREATE SCHEMA IF NOT EXISTS {LINK_SCHEMA}",
        f"""CREATE TABLE IF NOT EXISTS {_LT} (
               id bigint PRIMARY KEY, sync_name text, action text, status text,
               attempt int DEFAULT 0,
               shopify_id text, odoo_id text, store_id text, company_id text,
               shopify_source_hash text, odoo_source_hash text,
               shopify_source_json text, odoo_source_json text,
               error_detail text, timestamp text )""",
        # migrations for a table made before these columns existed
        f"ALTER TABLE {_LT} ADD COLUMN IF NOT EXISTS attempt int DEFAULT 0",
        f"ALTER TABLE {_LT} ADD COLUMN IF NOT EXISTS store_id text",
        f"ALTER TABLE {_LT} ADD COLUMN IF NOT EXISTS company_id text",
        f"ALTER TABLE {_LT} ADD COLUMN IF NOT EXISTS error_detail text",
        # run log
        f"""CREATE TABLE IF NOT EXISTS {LINK_SCHEMA}.{RUNS_TABLE} (
               id bigint PRIMARY KEY, sync_name text, started_at text, ended_at text,
               processed int, errors int, skipped int, status text, detail text )""",
        # monitor views (ops-facing; queryable without code), per pair
        f"""CREATE OR REPLACE VIEW {LINK_SCHEMA}.{v_shop} AS
           SELECT DISTINCT ON (sync_name, shopify_id) *
           FROM {_LT} WHERE shopify_id IS NOT NULL
           ORDER BY sync_name, shopify_id, timestamp DESC""",
        f"""CREATE OR REPLACE VIEW {LINK_SCHEMA}.{v_odoo} AS
           SELECT DISTINCT ON (sync_name, odoo_id) *
           FROM {_LT} WHERE odoo_id IS NOT NULL
           ORDER BY sync_name, odoo_id, timestamp DESC""",
        f"""CREATE OR REPLACE VIEW {LINK_SCHEMA}.{v_dead} AS
           SELECT * FROM {LINK_SCHEMA}.{v_shop} WHERE status <> 'ok'
           UNION ALL
           SELECT * FROM {LINK_SCHEMA}.{v_odoo}
           WHERE status <> 'ok' AND shopify_id IS NULL""",
        f"""CREATE OR REPLACE VIEW {LINK_SCHEMA}.{v_runs} AS
           SELECT sync_name, left(started_at, 10) AS day,
                  count(*) AS runs, sum(processed) AS processed,
                  sum(errors) AS errors, sum(skipped) AS skipped
           FROM {LINK_SCHEMA}.{RUNS_TABLE}
           GROUP BY sync_name, left(started_at, 10)""",
    ]
    for stmt in stmts:
        try:
            dbconn.execute(dw_name, query=stmt)
        except Exception as e:
            st.info(f"ensure_schema (DDL): {e}")

    # --- registration check + repair (the part raw DDL does not do) ---
    def _registered(table):
        try:
            # deliberately NOT the swallow-errors fetch() helper: we need the failure
            dbconn.fetch(dw_name, query=f"SELECT 1 FROM {LINK_SCHEMA}.{table} LIMIT 1")
            return True
        except Exception:
            return False

    needed = [LINK_TABLE, RUNS_TABLE]
    if not all(_registered(t) for t in needed):
        st.info("warehouse objects not registered in the Peliqan catalog yet; "
                "running pq.refresh_schema (synchronous)")
        try:
            pq.refresh_schema(connection_name=dw_name, schema_name=LINK_SCHEMA)
        except Exception as e:
            st.warning(f"refresh_schema failed: {e}")

    missing = [t for t in needed if not _registered(t)]
    if missing:
        raise RuntimeError(
            f"ensure_schema: {LINK_SCHEMA}.{' and '.join(missing)} exist(s) in Postgres but "
            f"remain(s) unregistered in the Peliqan catalog after refresh_schema. Aborting "
            f"the run: without a usable link table, syncs would write to the target with no "
            f"link rows (duplicates) while looking green.")


# ------------------------------------------------------------
# State helpers (bookmarks)
# ------------------------------------------------------------
def _get_state():
    try:
        state = pq.get_state()
    except Exception:
        return {}
    return state if isinstance(state, dict) else {}


def get_bookmark(sync_name):
    return _get_state().get("bookmarks", {}).get(sync_name)


def set_bookmark(sync_name, bookmark):
    try:
        state = _get_state()
        bookmarks = state.get("bookmarks", {})
        bookmarks[sync_name] = bookmark
        state["bookmarks"] = bookmarks
        pq.set_state(state)
    except Exception as e:
        st.warning(f"Could not persist bookmark for {sync_name}: {e}")


# ------------------------------------------------------------
# Bookmark math (PURE - no I/O - the single source of truth)
# ------------------------------------------------------------
def sort_by_updated_at(records, ts_field="updatedAt"):
    """Oldest-first. Records without the timestamp sort last (never advance)."""
    return sorted(records, key=lambda r: str(r.get(ts_field) or "9999"))


def bookmark_with_overlap(bookmark, fmt="%Y-%m-%dT%H:%M:%SZ", seconds=1):
    """v4 (contract §6): rewind a bookmark by `seconds` for fetch paths whose
    comparator strictness we do NOT control (e.g. a connector list(bookmark=...)).
    Where we write the filter ourselves, use >= directly instead. Idempotency
    (hash-skip / already-linked) makes the overlap re-reads no-ops."""
    try:
        from datetime import datetime, timedelta
        dt = datetime.strptime(str(bookmark), fmt)
        return (dt - timedelta(seconds=seconds)).strftime(fmt)
    except Exception:
        return bookmark


def advance_bookmark(high_water, ts):
    if ts and str(ts) > str(high_water):
        return str(ts)
    return high_water


def simulate_bookmark_run(records, current_bookmark, limit, ts_field="updatedAt"):
    """Pure preview of where the bookmark lands. Mirrors the real loop minus
    the writeback; what the bookmark tests assert."""
    high_water, processed = current_bookmark, 0
    for r in sort_by_updated_at(records, ts_field):
        if limit and processed >= limit:
            break
        processed += 1
        high_water = advance_bookmark(high_water, r.get(ts_field))
    return high_water, processed


# ------------------------------------------------------------
# Hashing  (stable across field boundaries and None/'' — use this, not
# ad-hoc str concatenation)
# ------------------------------------------------------------
def stable_hash(mapped):
    """md5 over canonical JSON of the OWNED/mapped fields. Pass a dict of the
    fields that define change for this direction; key order does not matter."""
    canonical = json.dumps(mapped, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.md5(canonical.encode()).hexdigest()


# ------------------------------------------------------------
# SQL helpers
# ------------------------------------------------------------
def _sql(value):
    return str(value).replace("'", "''")


def fetch(query):
    try:
        return dbconn.fetch(dw_name, query=query) or []
    except Exception as e:
        st.info(f"Query failed: {e}")
        return []


# ------------------------------------------------------------
# Link table helpers (append-only, with attempt/dead + optional scoping)
# ------------------------------------------------------------
_last_link_id = 0


def _next_link_id():
    global _last_link_id
    candidate = int(time.time() * 1_000_000)
    if candidate <= _last_link_id:
        candidate = _last_link_id + 1
    _last_link_id = candidate
    return candidate


def _err(detail, limit=4000):
    if detail is None:
        return None
    try:
        text = detail if isinstance(detail, str) else json.dumps(detail, default=str)
    except Exception:
        text = str(detail)
    return text[:limit]


def _last_attempt(sync_name, shopify_id=None, odoo_id=None):
    key = "shopify_id" if shopify_id is not None else "odoo_id"
    val = shopify_id if shopify_id is not None else odoo_id
    if val is None:
        return 0
    rows = fetch(f"""
        SELECT attempt FROM {_LT}
        WHERE sync_name = '{_sql(sync_name)}' AND {key} = '{_sql(val)}'
        ORDER BY timestamp DESC LIMIT 1
    """)
    try:
        return int(rows[0]["attempt"]) if rows and rows[0].get("attempt") is not None else 0
    except Exception:
        return 0


def insert_link_row(sync_name, action, status, shopify_id=None, odoo_id=None,
                    shopify_source_hash=None, odoo_source_hash=None,
                    shopify_source_json=None, odoo_source_json=None,
                    store_id=None, company_id=None, error_detail=None):
    # Attempt counting + poison promotion happen here so every sync gets DLQ
    # behaviour for free. ok rows reset attempt to 0.
    if status in ERROR_STATUSES:
        attempt = _last_attempt(sync_name, shopify_id, odoo_id) + 1
        if attempt >= MAX_ATTEMPTS:
            status = "dead"
    else:
        attempt = 0

    def _row():
        row = {
            "id": _next_link_id(), "sync_name": sync_name, "action": action,
            "status": status, "attempt": attempt,
            "shopify_id": str(shopify_id) if shopify_id is not None else None,
            "odoo_id": str(odoo_id) if odoo_id is not None else None,
            "store_id": str(store_id) if store_id is not None else None,
            "company_id": str(company_id) if company_id is not None else None,
            "shopify_source_hash": shopify_source_hash,
            "odoo_source_hash": odoo_source_hash,
            "shopify_source_json": json.dumps(shopify_source_json, default=str) if shopify_source_json is not None else None,
            "odoo_source_json": json.dumps(odoo_source_json, default=str) if odoo_source_json is not None else None,
            "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if error_detail is not None:
            row["error_detail"] = _err(error_detail)
        return row

    last_err = None
    for _ in range(3):
        try:
            dbconn.insert(dw_name, LINK_SCHEMA, LINK_TABLE, _row())
            return True
        except Exception as e:
            last_err = e
            time.sleep(0.01)
    # never drop an error row over an optional column
    if error_detail is not None:
        try:
            row = _row(); row.pop("error_detail", None)
            dbconn.insert(dw_name, LINK_SCHEMA, LINK_TABLE, row)
            st.warning(f"Wrote link row without error_detail ({sync_name}/{status}): {last_err}")
            return True
        except Exception as e:
            last_err = e
    st.warning(f"Could not write link row ({sync_name}/{status}): {last_err}")
    return False


def _scope(store_id, company_id):
    clause = ""
    if MULTI_STORE:
        if store_id is not None:
            clause += f" AND store_id = '{_sql(store_id)}'"
        if company_id is not None:
            clause += f" AND company_id = '{_sql(company_id)}'"
    return clause


def find_target(sync_name, shopify_id, store_id=None, company_id=None):
    """Most recent ok link for a Shopify-driven sync -> (odoo_id, shopify_source_hash)."""
    rows = fetch(f"""
        SELECT odoo_id AS target_id, shopify_source_hash
        FROM {_LT}
        WHERE sync_name = '{_sql(sync_name)}' AND shopify_id = '{_sql(shopify_id)}'
          AND status = 'ok'{_scope(store_id, company_id)}
        ORDER BY timestamp DESC LIMIT 1
    """)
    if rows:
        return rows[0]["target_id"], rows[0]["shopify_source_hash"]
    return None, None


def find_link_by_odoo(sync_name, odoo_id, store_id=None, company_id=None):
    """Most recent ok link keyed by odoo_id -> (shopify_id, odoo_source_hash)."""
    rows = fetch(f"""
        SELECT shopify_id, odoo_source_hash
        FROM {_LT}
        WHERE sync_name = '{_sql(sync_name)}' AND odoo_id = '{_sql(odoo_id)}'
          AND status = 'ok'{_scope(store_id, company_id)}
        ORDER BY timestamp DESC LIMIT 1
    """)
    if rows:
        return rows[0]["shopify_id"], rows[0]["odoo_source_hash"]
    return None, None


# ------------------------------------------------------------
# Run log
# ------------------------------------------------------------
def record_run(sync_name, started_at, counts, status="ok", detail=""):
    counts = counts or {}
    try:
        dbconn.insert(dw_name, LINK_SCHEMA, RUNS_TABLE, {
            "id": _next_link_id(), "sync_name": sync_name,
            "started_at": started_at,
            "ended_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "processed": int(counts.get("processed", 0)),
            "errors": int(counts.get("errors", 0)),
            "skipped": int(counts.get("skipped", 0)),
            "status": status, "detail": _err(detail) or "",
        })
    except Exception as e:
        st.info(f"record_run: {e}")


# ------------------------------------------------------------
# Replay: re-drive error/dead rows from the stored source snapshot.
# process_one must accept (sync_name, source_record). Fan-out syncs that
# need resolved parent context register no replay (documented) and are
# reprocessed by the normal bookmark run instead.
# ------------------------------------------------------------
def replay_source(sync_name, process_one, statuses=("target_error",),
                  include_dead=False, limit=500):
    wanted = list(statuses) + (["dead"] if include_dead else [])
    in_list = ",".join(f"'{s}'" for s in wanted)
    rows = fetch(f"""
        SELECT shopify_source_json, odoo_source_json FROM (
            SELECT DISTINCT ON (sync_name, shopify_id, odoo_id) *
            FROM {_LT} WHERE sync_name = '{_sql(sync_name)}'
            ORDER BY sync_name, shopify_id, odoo_id, timestamp DESC
        ) latest WHERE status IN ({in_list}) LIMIT {int(limit)}
    """)
    replayed = 0
    for r in rows:
        raw = r.get("shopify_source_json") or r.get("odoo_source_json")
        if not raw:
            continue
        try:
            record = json.loads(raw) if isinstance(raw, str) else raw
            process_one(sync_name, record)
            replayed += 1
        except Exception as e:
            st.warning(f"replay {sync_name}: {e}")
    st.write(f"replayed {replayed} record(s) for {sync_name}")
    return replayed


# ------------------------------------------------------------
# Delete reconciliation: find ok-linked source ids no longer present in the
# live source, and hand them to a per-sync handler (unlink vs archive is a
# per-sync decision — the detection is generic).
# ------------------------------------------------------------
def reconcile_deletes(sync_name, live_source_ids, apply_delete, side="shopify"):
    id_col = "shopify_id" if side == "shopify" else "odoo_id"
    live = {str(x) for x in (live_source_ids or [])}
    rows = fetch(f"""
        SELECT DISTINCT ON (sync_name, {id_col}) *
        FROM {_LT}
        WHERE sync_name = '{_sql(sync_name)}' AND {id_col} IS NOT NULL
        ORDER BY sync_name, {id_col}, timestamp DESC
    """)
    gone = [r for r in rows if r.get("status") == "ok" and str(r.get(id_col)) not in live]
    st.write(f"delete reconciliation {sync_name}: {len(gone)} candidate(s)")
    for row in gone:
        try:
            apply_delete(row)   # handler performs unlink/archive + writes a delete link row
        except Exception as e:
            st.warning(f"reconcile_deletes {sync_name}: {e}")
    return len(gone)


# ------------------------------------------------------------
# Shopify transport (single-line queries, 1 record per call)
# ------------------------------------------------------------
def gid_to_numeric(gid):
    if gid is None:
        return None
    return str(gid).rsplit("/", 1)[-1]


def shopify_list_incremental(object_type, bookmark):
    """Incremental read via connector list(bookmark=...). The connector's
    comparator strictness is UNKNOWN: callers must pass
    bookmark_with_overlap(bookmark), never the raw bookmark (contract §6).
    Prefer a cursor-paged GraphQL read with an explicit >= filter for large
    sets (see fetch_changed_* in the examples)."""
    try:
        result = shopify_api.list(object_type, bookmark=bookmark)
    except Exception as e:
        st.error(f"source_error: Shopify list({object_type}) failed: {e}")
        return []
    if isinstance(result, dict):
        return result.get("detail", []) or []
    return result or []


def shopify_graphql(query, variables=None):
    single_line = " ".join(query.split())  # the edge rejects multi-line queries
    return shopify_api.apicall(path="graphql.json", query=single_line, variables=variables or {})


def graphql_user_errors(result, mutation_name):
    detail = result.get("detail", {}) if isinstance(result, dict) else {}
    data = detail.get("data", {}) or {}
    payload = data.get(mutation_name, {}) or {}
    return payload.get("userErrors", []) or []


# ------------------------------------------------------------
# Odoo transport (generic 'object' endpoint)
# ------------------------------------------------------------
def odoo_object_add(model, record):
    return odoo_api.add("object", {"model": model, "payload": [record], "additional_params": {}})


def odoo_object_update(model, target_id, record):
    return odoo_api.update("object", {"model": model, "payload": [[int(target_id)], record], "additional_params": {}})


def odoo_object_search(model, domain, fields):
    result = odoo_api.get("object", {"model": model, "payload": [domain], "additional_params": {"fields": fields}})
    if isinstance(result, dict):
        result = [result]
    return result or []


def odoo_search_read_incremental(model, fields, bookmark, page_size=100):
    """Drain an Odoo model via search_read: write_date >= bookmark, oldest-first,
    offset-paged until empty. Odoo write_date is 'YYYY-MM-DD HH:MM:SS'; keep its
    bookmark SEPARATE from Shopify's."""
    page = 0
    while True:
        try:
            resp = odoo_api.apicall("", odoo_model=model, odoo_method="search_read",
                                    payload=[[["write_date", ">=", bookmark]]],  # v4: >= not > (equal-second boundary; contract §6)
                                    additional_params={"limit": page_size, "offset": page * page_size,
                                                       "order": "write_date asc", "fields": fields})
        except Exception as e:
            st.error(f"source_error: Odoo search_read({model}) page {page} failed: {e}")
            return
        rows = (((resp or {}).get("detail") or {}).get("result") or []) if isinstance(resp, dict) else []
        if not rows:
            return
        yield rows
        page += 1


def extract_new_id(result):
    if not isinstance(result, dict):
        return None
    detail = result.get("detail")
    if isinstance(detail, dict):
        return detail.get("result") or detail.get("id")
    return detail


def is_ok(result):
    return isinstance(result, dict) and result.get("status") == "success"


# ============================================================
# >>> SYNC INSERTION POINT <<<
# The sync-builder appends each sync's trio here and registers it in
# SYNC_REGISTRY below. A process_<sync> loop should RETURN a counts dict
# {"processed": n, "errors": e, "skipped": s} so the run log is populated.
# ============================================================


# ------------------------------------------------------------
# Registry + run loop. Each entry: {"name", "run", "replay"?}.
# Order = dependency order (parents first; Shopify->Odoo before Odoo->Shopify).
# ------------------------------------------------------------
SYNC_REGISTRY = [
    # {"name": SYNC_X, "run": process_x, "replay": process_one_x},
]


def process_all():
    # Schema failure is FATAL: no sync may run if link rows cannot be recorded.
    try:
        ensure_schema()
    except Exception as e:
        st.error(f"ABORTING RUN - warehouse schema not usable: {e}")
        st.text(traceback.format_exc())
        return
    run_summary = []
    for entry in SYNC_REGISTRY:
        label, run = entry["name"], entry["run"]
        st.header(label)
        started = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            counts = run() or {}
            record_run(label, started, counts, status="ok")
            run_summary.append((label, "ok", ""))
        except Exception as e:
            detail = f"{e}"
            st.error(f"Sync {label} failed but the run continues: {detail}")
            st.text(traceback.format_exc())
            record_run(label, started, {}, status="failed", detail=detail)
            run_summary.append((label, "failed", detail))

    st.header("Run summary")
    for label, status, detail in run_summary:
        line = f"[{status.upper()}] {label}" + (f" - {detail}" if detail else "")
        (st.success if status == "ok" else st.error)(line)


try:
    process_all()
except Exception as e:
    # Absolute last-resort guard: the Worker must never end on an
    # unhandled exception.
    st.error(f"Worker aborted unexpectedly: {e}")
    st.text(traceback.format_exc())
