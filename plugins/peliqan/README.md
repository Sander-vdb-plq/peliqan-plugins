# peliqan

One plugin, all internal Peliqan skills and agents. Everything new gets added here as another `skills/<name>/` folder or `agents/<name>.md` file rather than as a new plugin.

## Skills

| Skill | What it does |
|---|---|
| `peliqan-sync` | Builds and extends Reverse-ETL sync workers between two systems as one single-file data app: scaffolds a worker for a system pair, or adds an individual sync (orders, stock, customers, fulfilment, refunds) to an existing one. Holds the framework contract, the worker template and the per-system checklists. |
| `peliqan-sync-support` | Troubleshoots a *deployed* sync worker: reads its code, run logs and link/run tables, matches the symptom to a known cause in the sync framework contract, and reports a root cause with a concrete fix. Read-only until the developer approves a rewind, replay or redeploy. Operate/repair companion to `peliqan-sync`. |
| `medallion-dashboard-builder` | Rebuilds a Power BI report as a custom dashboard (Streamlit or similar) on a Bronze/Silver/Gold/consumer-layer medallion architecture, with the PBIX or its DAX measures as the ground truth to verify every layer against. Also the reference for setting up a medallion architecture for a new data domain. |

Skills are model-invoked: ask "build a Shopify to Odoo sync", "why did the Odoo sync stop" or "rebuild this Power BI report as a dashboard" and Claude picks them up. You can also call them directly as `/peliqan:peliqan-sync`, `/peliqan:peliqan-sync-support` and `/peliqan:medallion-dashboard-builder`.

## Agents

| Agent | What it does |
|---|---|
| `peliqan-builder` | Builds and deploys on the platform: sync workers and individual syncs (`peliqan-sync`), data apps, pipelines, schemas, query tables and API endpoints, medallion dashboards (`medallion-dashboard-builder`) and RAG setups (`create-rag`) — then runs them and verifies from the logs. Reads freely, creates and updates what the request calls for, never deletes and never runs destructive SQL unasked. |
| `peliqan-support` | Triages a breakage in a Peliqan account — failed pipeline run, stopped sync, crashing data app, erroring endpoint, stale table, a dashboard whose numbers drifted — from the runs, logs and lineage, and returns an evidence-backed root cause plus a written-up fix. Read-only in the account: it names the fix, `peliqan-builder` or the developer applies it. Delegates deep sync diagnosis to `peliqan-sync-support`, medallion dashboard/layer diagnosis to `medallion-dashboard-builder`, and the write-up to `peliqan-tech-doc`. |

Delegate to `peliqan-support` when something is broken and to `peliqan-builder` when something needs building — the split is diagnose vs. change, and each hands off to the other when it hits the far side of that line.

Note that `medallion-dashboard-builder` is used from both sides: `peliqan-builder` drives it to build, `peliqan-support` reads it as the contract for what a layer or measure is *supposed* to do. Support never rebuilds a layer itself.

## Install

```
/plugin marketplace add Sander-vdb-plq/peliqan-plugins
/plugin install peliqan@peliqan-plugins-sander
```

## Requirements

Everything here works through the **Peliqan MCP** server (`list_data_apps`, `get_data_app_run_logs`, `get_connection_pipeline_runs`, `get_table_lineage`, `create_data_app`, …). It is not bundled with this plugin — the endpoint contains an account id, so each user connects it themselves.

To bundle it anyway, add a `.mcp.json` at this plugin's root:

```json
{
  "mcpServers": {
    "peliqan": {
      "type": "http",
      "url": "https://api.eu.peliqan.io/<ACCOUNT_ID>/mcp"
    }
  }
}
```

Both agents also expect two account-level Peliqan skills that still live outside this plugin — `peliqan-tech-doc` (write-ups) and `create-rag` (RAG/semantic search) — since they drive those rather than duplicating them. The skills they drive that *are* bundled here (`peliqan-sync`, `medallion-dashboard-builder`) need no separate install.

## Adding a new skill or agent

1. Skill: create `skills/<skill-name>/SKILL.md`. The folder name is what the skill is called; the `description` in its frontmatter is what makes Claude pick it up, so write it as trigger phrases, not a summary.
2. Agent: create `agents/<agent-name>.md` — a single file, not a folder. Only `name` and `description` are required in frontmatter; `description` drives when Claude delegates to it, so write it as trigger phrases, same as a skill.
3. If an agent should be able to reach the new skill, add it to that agent's `skills:` list — that list is what makes it available, not the fact that it sits in this plugin.
4. No manifest changes needed otherwise — everything under this plugin's root is picked up automatically.
