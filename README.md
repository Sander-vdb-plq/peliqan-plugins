# peliqan-plugins

Claude Code / Cowork plugin marketplace for Peliqan's internal plugins.

## Install

```
/plugin marketplace add Sander-vdb-plq/peliqan-plugins
/plugin install peliqan@peliqan-plugins
```

## Contents

| Plugin | What's in it |
|---|---|
| [`peliqan`](plugins/peliqan) | Skills: `peliqan-sync`, `peliqan-sync-support`, `medallion-dashboard-builder`. Agents: `peliqan-builder`, `peliqan-support`. |

Everything new goes into the existing `peliqan` plugin as another `skills/<name>/`
folder or `agents/<name>.md` file, rather than as a new plugin — see that
plugin's README.

## Layout

```
.claude-plugin/marketplace.json   # what /plugin marketplace add reads
plugins/peliqan/                  # the plugin itself
```
