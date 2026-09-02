# Dashboard Build Gotchas

Detailed guidance for step 5 (building the dashboard) — covers logo/branding
handling, display-vs-filter mismatches, and formatting/naming consistency
checks that are easy to get subtly wrong even once the underlying formulas
are correct.

## Check for an existing sibling dashboard's solution first

Before inventing a UI solution for a tricky layout problem (logos, headers,
custom widgets), check whether another dashboard already deployed in the
same account solved it. List the account's existing data-apps and read
their scripts — a sibling dashboard that already renders a logo, header, or
similar element correctly is a faster and more reliable source of a working
pattern than guessing from general framework knowledge, since it's already
been visually confirmed to work in this specific environment.

## Ask before assuming anything about a logo/branding image

A PBIX file's `Report/StaticResources` often contains multiple embedded
images (some are the client's own branding, others may be unrelated icons
pulled in for other visuals — payment provider logos, connector icons,
etc.). Don't default to using any of them, and don't default to omitting a
logo either. Ask the user:
- Whether they want a logo/branding image at all
- If yes, where it should come from — an image already embedded in the
  PBIX (name the specific file so they can confirm it's actually their
  branding, not an unrelated icon), a fresh upload from the user, or a URL
  the user provides

A logo the user uploads directly (already cropped/cleaned) should be
preferred over one extracted from the PBIX's embedded resources when both
are available, since the extracted version may include background/padding
baked in from its original placement in the report.

## Never manually retype or relay a large base64 string

This is itself a source of silent data corruption, not just a transmission
inconvenience. A single dropped, duplicated, or altered character partway
through a 15,000+ character string produces a PNG that still opens without
an error in many tools, but renders visibly wrong (clipped, flipped,
garbled) in a browser — and the corrupted string still "looks right" at a
glance, matches in approximate length, and can pass a casual review. If a
rendered image appears broken, don't assume it's a CSS/layout problem and
start iterating on styling — first hash-compare (e.g. SHA-256) the exact
bytes stored in persisted state against a freshly-generated known good
copy, and decode-and-view whatever is actually stored, fetched fresh from
the server (not from your own earlier message).

**The reliable fix is to eliminate the manual relay step entirely, not to
retype more carefully.** Add a temporary native upload control to the
dashboard itself so the binary data flows directly from the user's browser
into persisted state, with no human or model transcription in between —
and give "no logo at all" an explicit, first-class option rather than
leaving it as an unlabeled default someone reaches by just not uploading
anything:

```python
with st.expander("⚙️ Logo settings", expanded=not bool(LOGO_B64)):
    no_logo = st.checkbox("No logo — don't show a header image", value=(LOGO_B64 == "__none__"))
    if no_logo:
        if st.button("Confirm no logo"):
            pq.set_state({"logo_b64": "__none__"})
            st.success("Saved. Refresh to apply — no logo will be shown.")
    else:
        uploaded = st.file_uploader("Upload logo image", type=["png", "jpg", "jpeg"])
        if uploaded is not None:
            new_b64 = base64.b64encode(uploaded.read()).decode("ascii")
            st.image(uploaded, caption="Preview", width=200)
            if st.button("Save this logo"):
                pq.set_state({"logo_b64": new_b64})
                st.success("Saved. Refresh to see it applied.")
```

Using a sentinel like `"__none__"` (rather than just leaving the key unset)
records the choice as deliberate — an empty/missing state key is ambiguous
between "hasn't decided yet" and "actively doesn't want one," which matters
when deciding whether to keep prompting for a logo later. The render logic
should treat both an empty string and the sentinel as "don't show a logo":
`if LOGO_B64 and LOGO_B64 != "__none__":`.

The `expanded=not bool(LOGO_B64)` only auto-**collapses** the panel once a
logo exists (a small UI nicety) — it does not remove the panel from the
code. Removing it is a separate, deliberate edit, and it should be offered
immediately, not left for later: as soon as the person uploads through this
control (or confirms "no logo") and confirms the result is correct,
proactively offer to strip the upload UI out of the script in that same
reply. It's served its purpose the moment the choice is made, and a
collapsed-but-present settings panel is still unnecessary clutter on a
dashboard meant for daily use. This same pattern — temporary native upload
control with an explicit opt-out, verify, then explicitly offer to strip
the control back out — applies to any large binary payload a dashboard
needs (logos, icons, certificates), not just this one case.

## Render a header logo with `position: fixed` CSS

Not nested inside a layout column, and not via `st.image()` inside a column
either. Placing a logo `<img>` (raw HTML or `st.image()`) inside an
`st.columns()` cell is fragile — the image can get clipped by the column's
own flex/box layout even when the image data itself is completely correct.
Both a raw `<img>` with `max-width` and a column-nested `st.image()` have
been observed clipping in production. The pattern confirmed reliable in
production takes the logo out of the normal content flow entirely and
floats it independently over the page:

```python
st.markdown("""
<style>
.logo-top-right { position: fixed; top: 14px; right: 25px; z-index: 1000; }
.logo-top-right img { height: 42px; width: auto; }
</style>
""", unsafe_allow_html=True)
if LOGO_B64 and LOGO_B64 != "__none__":
    st.markdown(f'<div class="logo-top-right"><img src="data:image/png;base64,{LOGO_B64}"></div>',
                unsafe_allow_html=True)
```

Place this markdown call on its own, not inside any `st.columns()` block.
If a rendered screenshot shows an image only partially visible or visually
distorted, first suspect data corruption from a manual relay step (see
above) before touching layout CSS — clipping and corruption look
superficially similar in a small screenshot, but only one of them is fixed
by changing styles.

## Verify what's actually displayed, not just what's filtered

When a dashboard filter must show a literal source field (per the binding
rule in `dax_comparison.md`), verify what you're actually displaying, not
just what column you're technically filtering on. It's possible to
correctly filter on the right column while still visually leaking the
wrong one — e.g. building a dropdown label like `f"{code} — {name}"` still
surfaces the description even though the filter's `isin()` check uses the
code. If the person asks for the raw code and nothing else, show only the
raw code value with no appended label, matching the source visual exactly.

## Check number formatting and rounding against the source report

Don't let raw float precision leak into the display. A raw numeric column
pulled straight from the warehouse can carry many more decimal places than
any report would show (e.g. `4213.750000` instead of `4,213.75`), and
`st.dataframe()` will happily render that raw precision with no warning.
Compare every numeric column's displayed format against the PBIX (decimal
places, thousands separators, currency symbols) before considering the
table done — this is a separate check from getting the *value* correct,
since a correctly-computed number can still display wrong. If the PBIX
isn't available to check against, or its formatting is ambiguous, ask the
person directly how they want each numeric column rounded/formatted rather
than guessing or leaving raw precision in place. Apply the format via the
dataframe's own `.style.format({...})` (e.g. `"{:,.2f}"` for 2-decimal
comma-thousands) rather than pre-rounding the underlying values, so the
full-precision numbers remain available for any further calculation.

## Check column display names for consistency, not just correctness

A column can be computing the exact right value while still being labeled
inconsistently with how the rest of the account names the same concept
(e.g. `"Amount (gross)"` vs. an existing sibling dashboard's `"Gross
Amount"` for the same field) — this is a naming/consistency check,
independent of whether the math or the rounding is correct, and is easy to
skip because the column "looks right" once the numbers match.
