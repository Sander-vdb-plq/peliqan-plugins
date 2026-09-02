#!/usr/bin/env python3
"""Pure offline tests for the v4 bookmark rules (contract §6).

Run BEFORE deploying a worker or adding a sync:

    python scripts/test_bookmarks.py [path/to/worker.py]

Extracts the pure bookmark functions (sort_by_updated_at, advance_bookmark,
bookmark_with_overlap, simulate_bookmark_run) from the worker file — default:
assets/worker_template.py relative to the skill root — and asserts:

1. THE v4 REGRESSION: a truncated run over an equal-timestamp cluster parks
   the bookmark ON the shared second, so any strict `>` refetch would lose the
   rest of the cluster; a `>=` refetch sees them again. This is the live
   incident of 2026-07-15 (3 records silently lost) encoded as a test.
2. bookmark_with_overlap rewinds by 1s in the given format and falls back to
   the input on an unparseable bookmark.
3. advance_bookmark is monotonic and ignores missing timestamps.
"""
import ast
import sys
from pathlib import Path

FUNCS = ["sort_by_updated_at", "advance_bookmark", "bookmark_with_overlap",
         "simulate_bookmark_run"]


def load_pure_functions(worker_path):
    tree = ast.parse(Path(worker_path).read_text())
    wanted = [n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name in FUNCS]
    missing = set(FUNCS) - {n.name for n in wanted}
    if missing:
        raise SystemExit(f"FAIL: worker is missing pure fn(s) {sorted(missing)} "
                         f"- framework older than v4? Upgrade per contract §11.")
    module = ast.Module(body=wanted, type_ignores=[])
    ns = {}
    exec(compile(module, worker_path, "exec"), ns)
    return ns


def main():
    default = Path(__file__).resolve().parent.parent / "assets" / "worker_template.py"
    worker = sys.argv[1] if len(sys.argv) > 1 else str(default)
    ns = load_pure_functions(worker)
    sort_by_updated_at = ns["sort_by_updated_at"]
    advance_bookmark = ns["advance_bookmark"]
    bookmark_with_overlap = ns["bookmark_with_overlap"]
    simulate_bookmark_run = ns["simulate_bookmark_run"]

    # --- 1. the v4 regression: equal-timestamp cluster + truncation ---------
    T = "2026-07-03T11:03:37Z"
    cluster = [{"id": i, "updatedAt": T} for i in range(6)]          # 6 records, one second
    later = [{"id": 99, "updatedAt": "2026-07-03T11:03:47Z"}]
    records = cluster + later

    hw, processed = simulate_bookmark_run(records, "2020-01-01T00:00:00Z", limit=4)
    assert processed == 4, processed
    assert hw == T, hw  # bookmark parks ON the shared second

    # strict `>` refetch loses the remaining 2 cluster records; `>=` re-sees the
    # whole cluster (processed ones settle as hash-skips) + the later record
    strict = {r["id"] for r in records if r["updatedAt"] > hw}
    gte = {r["id"] for r in records if r["updatedAt"] >= hw}
    unprocessed = {4, 5}  # the cluster records the truncated run never reached
    assert strict == {99}, "sanity: strict > sees only the later record"
    assert unprocessed <= gte, ("v4 REGRESSION: >= must re-see the unprocessed "
                                "cluster records that strict > loses forever")
    assert unprocessed.isdisjoint(strict), "strict > must demonstrably lose them"

    # --- 2. bookmark_with_overlap ------------------------------------------
    assert bookmark_with_overlap("2026-07-15T00:00:00Z") == "2026-07-14T23:59:59Z"
    assert bookmark_with_overlap("not-a-date") == "not-a-date"
    import inspect
    if "fmt" in inspect.signature(bookmark_with_overlap).parameters:
        assert bookmark_with_overlap("2026-07-15 00:00:00", fmt="%Y-%m-%d %H:%M:%S") \
            == "2026-07-14 23:59:59"
    else:
        print("NOTE: bookmark_with_overlap lacks the v4 `fmt` parameter "
              "(ISO-only hotfix signature) - upgrade the framework block "
              "per contract §11 when convenient.")

    # --- 3. advance_bookmark monotonic + None-safe --------------------------
    assert advance_bookmark(T, None) == T
    assert advance_bookmark(T, "2020-01-01T00:00:00Z") == T
    assert advance_bookmark(T, "2026-07-03T11:03:47Z") == "2026-07-03T11:03:47Z"
    assert sort_by_updated_at([{"updatedAt": None}, {"updatedAt": T}])[0]["updatedAt"] == T

    print(f"OK: v4 bookmark rules hold for {worker}")


if __name__ == "__main__":
    main()
