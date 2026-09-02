# peliqan

One plugin, all internal Peliqan skills and agents. Everything new gets added here as another `skills/<name>/` folder or `agents/<name>.md` file rather than as a new plugin.

## Skills

| Skill | What it does |
|---|---|
| `timesheet-workday` | Read-only. Pulls calendar, mail, chat, tasks, docs and code activity for a given day and merges it into a chronological, timesheet-ready log. |
| `timesheet-logger` | Write side. Takes that log and creates real time entries, resolving or creating clients/projects/tasks as needed, then reports what it did. |
| `peliqan-sync-support` | Troubleshoots a *deployed* sync worker: reads its code, run logs and link/run tables, matches the symptom to a known cause in the sync framework contract, and reports a root cause with a concrete fix. Read-only until the developer approves a rewind, replay or redeploy. Operate/repair companion to the account-level `peliqan-sync` skill, which builds them. |

Skills are model-invoked: ask "what did I work on yesterday", "log these hours" or "why did the Odoo sync stop" and Claude picks them up. You can also call them directly as `/peliqan:timesheet-workday`, `/peliqan:timesheet-logger` and `/peliqan:peliqan-sync-support`.

## Agents

| Agent | What it does |
|---|---|
| `timesheet-backfill` | Runs `timesheet-workday` + `timesheet-logger` across a whole date range (a week, "since last Monday"), day by day, in its own context — then returns one consolidated report instead of per-day noise in the main conversation. |
| `peliqan-support` | Triages a breakage in a Peliqan account — failed pipeline run, stopped sync, crashing data app, erroring endpoint, stale table — from the runs, logs and lineage, and returns an evidence-backed root cause plus a written-up fix. Read-only in the account: it names the fix, `peliqan-builder` or the developer applies it. Delegates deep sync diagnosis to `peliqan-sync-support` and the write-up to `peliqan-tech-doc`. |
| `peliqan-builder` | Builds and deploys on the platform: sync workers and individual syncs (`peliqan-sync`), data apps, pipelines, schemas, query tables and API endpoints, medallion dashboards (`medallion-dashboard-builder`) and RAG setups (`create-rag`) — then runs them and verifies from the logs. Reads freely, creates and updates what the request calls for, never deletes and never runs destructive SQL unasked. |
| `timesheet-auditor` | Read-only QA pass over a range of *already-logged* entries: reconstructs each day independently via `timesheet-workday` and diffs it against the log to surface gap days, shortfalls, duplicates, and stale project/task references. Never writes anything — it names fixes, `timesheet-backfill`/`timesheet-logger` apply them. |

Delegate to `peliqan-support` when something is broken and to `peliqan-builder` when something needs building — the split is diagnose vs. change, and each hands off to the other when it hits the far side of that line. Delegate to `timesheet-backfill` for multi-day catch-up ("catch up my timesheet for last week"); to `timesheet-auditor` to sanity-check what's already logged before submitting ("audit my timesheet," "did I forget to log anything"). For a single day with nothing logged yet, the two skills above are enough on their own.

## Install

```
/plugin marketplace add peliqan/peliqan-plugins
/plugin install peliqan@peliqan-plugins
```

## Requirements

`timesheet-logger` writes through the **Peliqan Timesheet MCP** server, which is not bundled with this plugin — the endpoint contains an account id, so each user connects it themselves.

To bundle it anyway, add a `.mcp.json` at this plugin's root:

```json
{
  "mcpServers": {
    "peliqan-timesheet": {
      "type": "http",
      "url": "https://api.eu.peliqan.io/<ACCOUNT_ID>/timesheet/mcp"
    }
  }
}
```

`peliqan-sync-support`, `peliqan-support` and `peliqan-builder` all work through the **Peliqan MCP** server (`list_data_apps`, `get_data_app_run_logs`, `get_connection_pipeline_runs`, `get_table_lineage`, `create_data_app`, …), which is likewise per-account and connected by each user rather than bundled here. `peliqan-builder` and `peliqan-support` also expect the account-level Peliqan skills to be installed — `peliqan-sync`, `peliqan-tech-doc`, `medallion-dashboard-builder`, `create-rag` — since they drive those rather than duplicating them.

`timesheet-workday` has no hard requirement — it uses whatever read-capable connectors are present and degrades gracefully when one is missing.

## Note on autonomy

`timesheet-logger` is deliberately written to run unattended, including in scheduled jobs: it creates entries without a chat confirmation, on the basis that entries still need downstream approval and are easy to correct. Read the "Why this is allowed to run unattended" section in its `SKILL.md` before changing that behaviour.

## Adding a new skill or agent

1. Skill: create `skills/<skill-name>/SKILL.md`. The folder name is what the skill is called; the `description` in its frontmatter is what makes Claude pick it up, so write it as trigger phrases, not a summary.
2. Agent: create `agents/<agent-name>.md` — a single file, not a folder. Only `name` and `description` are required in frontmatter; `description` drives when Claude delegates to it, so write it as trigger phrases, same as a skill.
3. No manifest changes needed — everything under this plugin's root is picked up automatically.
