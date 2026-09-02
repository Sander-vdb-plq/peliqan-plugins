# peliqan-plugins

Claude Code / Cowork plugin marketplace for Peliqan's internal plugins.

## Install

```
/plugin marketplace add <owner>/peliqan-plugins
/plugin install peliqan@peliqan-plugins
```

Replace `<owner>` with whatever account this repo lives under.

## Contents

| Plugin | What's in it |
|---|---|
| [`peliqan`](plugins/peliqan) | Skills: `timesheet-workday`, `timesheet-logger`, `peliqan-sync-support`. Agents: `peliqan-support`, `peliqan-builder`, `timesheet-backfill`, `timesheet-auditor`. |

Everything new goes into the existing `peliqan` plugin as another `skills/<name>/`
folder or `agents/<name>.md` file, rather than as a new plugin — see that
plugin's README.

## Layout

```
.claude-plugin/marketplace.json   # what /plugin marketplace add reads
plugins/peliqan/                  # the plugin itself
```
