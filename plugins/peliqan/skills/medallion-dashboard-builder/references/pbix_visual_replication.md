# Replicating PBIX Visuals: Type and Styling, Not Just Data

Matching a Power BI report's numbers is only half the job — replicating
"look and feel" is part of parity too. This file covers how to catalog and
replicate each visual's *type* and *styling*, independent of whatever data
verification (see `dax_comparison.md`) confirms about its formulas.

## Catalog every visual before writing any dashboard code

For each visual on the confirmed target page, record two things:

- **Visual type**: card, half-donut/gauge, matrix/pivot table (with
  expandable groups and subtotal rows), pie/donut chart, bar chart, slicer
  (dropdown vs. multi-select list vs. button list), plain table, etc. —
  from the layout JSON's visual type field, confirmed against the rendered
  screenshot.
- **Styling**: colors (including any per-category or conditional color
  rules, e.g. a specific category always rendered in a specific color, or a
  value colored differently above/below zero), borders, fonts, card
  layout, and any visual hierarchy (bold subtotal rows, indentation on
  child rows, collapsed vs. expanded groups by default).

## Replicate the same visual metaphor, not a "close enough" substitute

- A matrix with bold project subtotal rows and indented line-item rows
  underneath should become an indented, hierarchy-preserving table (bold
  parent rows, indented child rows) on the target platform, not a
  flattened generic dataframe.
- A half-donut gauge should be built to actually look like a half-donut
  gauge, not approximated with a generic progress bar.
- A pie chart's specific category-to-color assignment (e.g. one category
  always shown in a particular color, everything else from a stable
  palette) should carry over exactly, not be left to whatever the charting
  library assigns by default.

If the target platform's default widgets don't have a built-in equivalent
for a PBIX visual type, build a custom equivalent (e.g. a hand-drawn SVG for
a gauge shape a charting library doesn't offer natively) rather than
substituting a different chart type and calling it close enough. Where the
target platform is Streamlit, `streamlit_patterns.md` has working, tested
implementations of several of these (SVG gauges, a stable custom color
scale, the indented matrix-table pattern) — check there before building one
from scratch.

## Match the PBIX's own color palette and card/border styling

Where color/border choices are a distinctive part of the report's identity,
carry them forward rather than defaulting to whatever theme the target
platform ships with — e.g. if KPI cards use a specific accent color and
border style, or gauges use a specific fill color, use those specific
colors rather than generic default styling that happens to be easy to
build.

## If no PBIX or screenshot exists, ask — don't guess

Ask the user directly what visuals they want: chart types, layout, and any
color/branding preferences. This extends the same "no PBIX = ask, don't
assume" principle already applied to business logic to visual design as
well — an assumed KPI formula and an assumed chart type are both guesses
standing in for a decision the user hasn't actually made yet.
