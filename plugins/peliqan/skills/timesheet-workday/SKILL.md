---
name: timesheet-workday
description: "Reconstructs what the user actually worked on during a given work day (default today) by pulling activity from every connected source available — calendar, email, Slack, task trackers, docs, code hosts, CRMs, etc. — plus any Claude chat transcripts the user supplies, then merges everything into a structured, chronological, timesheet-ready log with project/client tags where they can be inferred. Use this whenever the user asks to \"fill in my timesheet,\" \"log my hours,\" \"what did I work on today/yesterday,\" \"recreate my day,\" \"reconstruct my workday,\" \"help me remember what I did,\" or anything similar — even if they don't name a specific source, a specific date, or say the word \"timesheet.\" Trigger proactively any time timesheet, time-tracking, or \"what did I do\" language shows up, since this is exactly the gap-filling and multi-source reconciliation this skill is built for. This is the read-side companion to timesheet-logger — this skill only reconstructs the data, that one submits it."
---

# Timesheet Workday

Rebuilds a work day as a chronological activity log suitable for pasting into a timesheet, by combining every data source the user currently has connected. Because available connectors vary session to session, this skill is written to be **source-agnostic**: check what's actually available each time, use all of it, and degrade gracefully when something isn't connected.

## Ground rules

- **Read-only, always.** Only ever list/search/read from calendar, mail, chat, task, doc, or code sources. Never send an email, post a Slack message, create a calendar event, or modify anything. This skill's job is reconstruction, not action.
- **Never invent activity.** If there's no evidence for a stretch of time, say so as an open gap — don't guess a plausible-sounding task to fill it.
- **Prefer specific over generic.** "Reviewed Q3 pricing doc with Sam" beats "Worked on documents."
- **Redact sensitive detail by default.** See the Privacy section below before pulling or merging any signal — 1:1s, personal chat, and email need special handling.
- **The user's own data only.** Everything pulled is the user's own mail/calendar/messages — normal read access, nothing extra to flag.

## Privacy: use sensitive signals, never expose sensitive detail

A timesheet log is often shared with a manager, HR, or a client — it should describe **what work was done**, not expose personal or private substance. The rule is not to exclude sensitive sources from the reconstruction — their timestamps are still real evidence of how the day was spent — it's to strip the sensitive detail out of what gets *shown*. Apply this whenever pulling raw signals (Step 3) and merging them (Step 5):

- **1:1 meetings**: Use them as a firm timing anchor like any other calendar block. Never surface discussion content, performance-related notes, or anything from the title/description that reads as personal rather than task-related. Label it generically, e.g. "1:1 with [Name]", and stop there unless the user explicitly asks for more.
- **Personal/private chat (DMs, personal channels)**: Use the fact that messages were sent, and their timestamps, as activity signal — this can anchor or extend a block just like any other source. But never surface or paraphrase the content, even briefly, and never name the channel or DM counterpart. Label the row generically, e.g. "Personal messages."
- **Email**: Use send/receive timestamps as signal that time was spent. Only surface the subject line and recipient/domain when they're clearly work-related (e.g., "Client follow-up — Acme Corp"); if a subject reads as personal or private, generalize the label instead (e.g., "Personal correspondence") rather than showing it verbatim. Don't drop the row for being sensitive — the time is still real, only the label changes.

When in doubt whether something is sensitive, default to less detail in the output, never to leaving the underlying signal out of the reconstruction — a generic row still counts toward the day's logged time.

## Step 1 — Nail down the date range

Default to **today** (the user's local day, midnight to midnight) unless they specify otherwise ("yesterday," "last Tuesday," "this week"). Don't ask for confirmation on an unambiguous "today" request — just proceed.

## Step 2 — Inventory what's actually available

Check the current tool list for anything in these categories. Treat this list as illustrative, not exhaustive — use whatever fits the category even if it's not named here:

| Category | Examples | Signal it gives |
|---|---|---|
| Calendar | Google Calendar, Outlook | Firm time-blocked events: title, start/end, attendees |
| Email | Gmail, Outlook Mail | Sent/received timestamps, subject, counterpart |
| Chat | Slack, Teams | Messages sent by the user — timestamp + channel/DM + gist |
| Tasks | Todoist, Asana, Linear, Jira | Tasks created/completed/updated in the window |
| Docs | Google Drive, Notion, Confluence | Files/pages edited, with edit timestamps |
| Code | GitHub, GitLab | Commits, PRs opened/reviewed, with timestamps |
| CRM/Sales | HubSpot, Apollo, Salesforce | Calls logged, deals touched, emails sent via CRM |
| Data/Ops | Peliqan or similar | Pipelines run, tables built, data-apps touched |

For each category, note connected vs. not. **Don't block on missing sources** — reconstruct from whatever exists. At the end of the run, mention which categories had nothing connected, and if it looks like connecting one would meaningfully fill gaps, this is a good moment to check `search_mcp_registry` and offer it via `suggest_connectors` (only offer, never auto-connect).

## Step 3 — Pull raw signals from each connected source

For the date range, pull activity from each available category. Keep it read-only and scoped to the day in question. Apply the Privacy rules above while pulling — don't pull full content you won't be allowed to surface:

- **Calendar**: every event overlapping the window — title, start, end, attendees/domains. For 1:1s, keep only what the Privacy section allows.
- **Email**: messages sent by the user (received mail is weaker evidence of active work and mostly useful for context, not time blocks) — subject, recipient/domain, send time. Generalize subjects that read as personal rather than dropping the row.
- **Chat**: messages sent by the user — timestamp, channel or DM name, a short gist of content (not a full transcript). For personal/private DMs and channels, keep the timestamp as signal but generalize the row — no channel/DM name, no gist.
- **Tasks**: items completed, created, or moved during the window — task name, project/list name.
- **Docs**: files edited during the window — file name, containing folder/workspace, last-edit time.
- **Code**: commits/PRs in the window — repo name, commit message or PR title, time.
- **CRM/Sales, Data/Ops**: same idea — named activity + timestamp.

For each signal, capture just enough to identify *what* happened and *when* — don't pull full email bodies or full chat threads, just enough context to describe the activity in one line.

## Step 4 — Fold in Claude chat activity (fills the biggest gaps)

Work done inside Claude conversations (writing, coding, research, drafting) often leaves no trace in calendar/email/Slack, so this is usually the single biggest source of "missing" hours. Two ways to pull this in:

1. **If the user has chat search/memory enabled and mentions or references past sessions**, treat relevant past conversations surfaced in context as activity signals: rough time, topic, and what was produced.
2. **If the user pastes or uploads an exported conversation** (markdown/JSON export, or just a pasted transcript), read it like any other file — check `file-reading` skill guidance if it's an uploaded file — and extract: approximate time (from timestamps in the export, or ask the user if missing), topic, and what was produced (a doc, a piece of code, an analysis, etc.).

Ask the user directly if they have chat exports to paste in when there are unexplained gaps — this is the most natural way to close them.

## Step 5 — Merge into one timeline

1. Calendar events are the firm skeleton — they define blocks with real start/end times.
2. Any other signal (email, Slack, doc edit, commit, chat) that falls *inside* a calendar block gets folded into that block's description rather than becoming its own row (e.g. "1:00–2:00 Client sync w/ Sam — incl. 3 follow-up Slack messages and a pricing doc edit"). Apply the Privacy rules when folding in — a personal DM inside a work block still counts toward that block's time but gets folded in generically ("incl. personal messages"), never with channel name or content.
3. Signals *outside* any calendar block become their own rows. Estimate duration as running from that signal to the next signal's start, capped at ~90 minutes for a single row — beyond that, close the row and mark the remainder as a gap.
4. Sort everything chronologically.

## Step 6 — Infer project/client tags where possible

Pull tags from whatever's available: calendar event title/attendee domains, Slack channel name, email recipient domain, task-tracker project/list name, doc folder/workspace name, repo name. If nothing points to a project, leave the tag blank — don't guess. Note it as unlabeled so the user can fill it in by hand.

## Step 7 — Surface the gaps

After building the timeline, explicitly list any stretches of the working day (use a reasonable default like 9–5 unless the user's calendar implies otherwise) with no signal from any source. Don't paper over these — ask the user if they remember what filled them, or if they have a chat export that covers that window.

## Step 8 — Output

The timetracking system this log typically feeds into (via the `timesheet-logger` skill) enforces a 30-minute minimum per entry, so split rows by duration before laying out the table rather than mixing them:

Produce the main chronological table with only entries **30 minutes or longer**:

| Time | Duration | Activity | Source | Project/Client |
|---|---|---|---|---|

Followed by:
- **Under 30 minutes** — a short bullet list, not table rows, of any entries below that floor (e.g. "10:14–10:22 (8m) — Quick Slack thread w/ Sam on invoice numbers"). Don't drop these and don't round them up into the table — that's a call for the employee (or `timesheet-logger`, which flags them the same way at logging time), not something to decide here. Skip this bullet entirely if there are none.
- **Total time accounted for** — sum the Duration column across *both* the table and the under-30 list, since it's all real time worked. If the total comes in under 8 hours, flag this explicitly and state the shortfall (e.g., "Only 6h15m accounted for — 1h45m short of a full day") right at the top of this section, rather than letting it blend into the gaps list below. This is the detail most likely to get missed before submitting a timesheet.
- **Unexplained gaps** — bullet list of time ranges with no signal.
- **Sources not checked** — categories with nothing connected this session, so the user knows the log is partial, not exhaustive.

## Notes

- If literally nothing is connected (no calendar, email, chat, tasks, docs), say so plainly and ask the user to either connect a source or paste in raw material (calendar screenshot, exported chats, a rough memory of the day) to work from.
- Time zone: use the calendar's time zone if one is connected; otherwise ask once if it's ambiguous, then proceed.
- This skill never needs to write anywhere — if a tool call would send, post, or modify something, that's a sign of a wrong turn; stop and reconsider.