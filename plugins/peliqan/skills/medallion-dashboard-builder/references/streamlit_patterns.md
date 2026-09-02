# Streamlit Dashboard Patterns

Reusable, tested code patterns for building Streamlit dashboards that
mirror Power BI report visuals.

## Multi-select filters with a clear-all button

Power BI slicers typically support multi-selection and have a native "clear
all filters" affordance. Replicate both in Streamlit using `session_state`
so a single button can reset every filter at once:

```python
for _k in ["f_project", "f_category", "f_year", "f_month"]:
    if _k not in st.session_state:
        st.session_state[_k] = []

def _clear_all_filters():
    st.session_state["f_project"] = []
    st.session_state["f_category"] = []
    st.session_state["f_year"] = []
    st.session_state["f_month"] = []

c_f1, c_f2, c_f3, c_f4, c_clear = st.columns([1, 1, 1, 1, 0.5])
with c_f1:
    f_project = st.multiselect("Project", project_codes, key="f_project")
# ... repeat for other filters ...
with c_clear:
    st.markdown('<div style="height:28px;"></div>', unsafe_allow_html=True)
    st.button("", icon=":material/ink_eraser:", help="Clear all filters",
              on_click=_clear_all_filters, use_container_width=True)
```

Empty selection means "no filter applied" (equivalent to Power BI's "All"),
applied downstream as: `if f_project: df = df[df["project_code"].isin(f_project)]`.

Streamlit's `st.button(icon=":material/<name>:")` supports Material Symbols
icons natively — useful for getting a specific icon (e.g. an eraser) without
hand-drawing SVG. Icon color can be set via CSS targeting `button svg` if
there's only one button in the app; if there are multiple buttons, scope the
CSS more specifically.

## Hand-drawn SVG gauge chart with hover tooltip

Standard chart libraries (Altair, Plotly) don't have a clean half-donut gauge
primitive with a target-line marker. Building it as raw SVG gives full
control:

```python
def gauge(pct, color, label, target=None):
    p_ = max(0.0, min(float(pct), 1.0))
    cx, cy = 100, 95
    r_out, r_in = 85, 58

    def pt(v, r):
        a = math.pi * (1 - v)
        return cx + r * math.cos(a), cy - r * math.sin(a)

    def arc_path(v0, v1, r_o, r_i):
        x0o, y0o = pt(v0, r_o); x1o, y1o = pt(v1, r_o)
        x1i, y1i = pt(v1, r_i); x0i, y0i = pt(v0, r_i)
        # Half-donut spans exactly 180 degrees, so the large-arc-flag is
        # always 0 -- no sub-arc drawn here can ever exceed 180 degrees.
        return (f"M {x0o:.2f} {y0o:.2f} A {r_o} {r_o} 0 0 1 {x1o:.2f} {y1o:.2f} "
                f"L {x1i:.2f} {y1i:.2f} A {r_i} {r_i} 0 0 0 {x0i:.2f} {y0i:.2f} Z")

    bg_path = arc_path(0, 1, r_out, r_in)
    val_svg = f'<path d="{arc_path(0, p_, r_out, r_in)}" fill="{color}"/>' if p_ > 0 else ""

    target_svg = ""
    if target is not None:
        t_ = max(0.0, min(float(target), 1.0))
        tx0, ty0 = pt(t_, r_in - 6); tx1, ty1 = pt(t_, r_out + 8)
        lx, ly = pt(t_, r_out + 22)
        anchor = "end" if t_ < 0.5 else "start"
        target_svg = (
            f'<line x1="{tx0:.2f}" y1="{ty0:.2f}" x2="{tx1:.2f}" y2="{ty1:.2f}" '
            f'stroke="orange" stroke-width="2.5"/>'
            f'<text x="{lx:.2f}" y="{ly:.2f}" fill="orange" font-size="13" '
            f'font-weight="600" text-anchor="{anchor}" dominant-baseline="middle">'
            f'{int(round(target*100))}%</text>'
        )

    # A native browser tooltip via the title attribute -- no JS needed --
    # gives hover-to-see-value without a charting library.
    tooltip = f"{label}: {int(round(pct*100))}%"
    if target is not None:
        tooltip += f" (target: {int(round(target*100))}%)"

    return (
        f'<div title="{tooltip}" style="text-align:center; cursor: default;">'
        f'<div style="font-size:16px;font-weight:600;color:#333;margin-bottom:4px;">{label}</div>'
        f'<svg viewBox="0 0 200 140" width="100%" style="max-width:260px;">'
        f'<path d="{bg_path}" fill="#e9ecef"/>{val_svg}{target_svg}'
        f'<text x="100" y="78" font-size="30" font-weight="600" fill="#4a5a66" '
        f'text-anchor="middle" dominant-baseline="middle">{int(round(pct*100))}%</text>'
        f'</svg></div>'
    )
```

Render with `st.markdown(gauge(...), unsafe_allow_html=True)`.

## Stable custom color scale for categorical pie/donut charts

When one category needs a fixed, meaningful color (e.g. "Revenue" always
green) and the rest need distinct-but-arbitrary colors that don't shift
around as the data is filtered, build an explicit Altair scale rather than
relying on the default categorical palette:

```python
_other_palette = ["#2b6cb0", "#e8833a", "#c0392b", "#8e44ad", "#7f8c8d",
                   "#16a085", "#d4ac0d", "#34495e", "#e91e8c", "#5d4037"]
_categories_sorted = sorted(df["category"].unique().tolist())  # sort for stability
_color_domain, _color_range = [], []
_i = 0
for cat in _categories_sorted:
    _color_domain.append(cat)
    if cat == "SPECIAL_CATEGORY":
        _color_range.append("#90C695")
    else:
        _color_range.append(_other_palette[_i % len(_other_palette)])
        _i += 1

chart = alt.Chart(df).mark_arc().encode(
    theta="value:Q",
    color=alt.Color("category:N", scale=alt.Scale(domain=_color_domain, range=_color_range)),
)
```

Sorting the categories before assigning colors is what keeps colors stable
across reruns/filters — without it, colors shift depending on which
categories happen to appear first in the currently-filtered data.

## Row-matrix table pattern (bold subtotal rows + indented line items)

A common Power BI matrix visual pattern: a bold summary row per group,
followed by indented individual line rows. Reproduce with a flat DataFrame
plus a boolean flag column driving conditional row styling:

```python
rows = []
for _, group_row in summary_df.iterrows():
    rows.append({"Label": group_row["name"], "_is_group": True, ...})
    for _, line in detail_df[detail_df["group_id"] == group_row["id"]].iterrows():
        rows.append({"Label": f"{'  ' * 17}{line['description']}", "_is_group": False, ...})

df = pd.DataFrame(rows)
flags = df["_is_group"].tolist()

def _highlight(row):
    return ["font-weight: 700; background-color: #eef3f8"] * len(row) if flags[row.name] else [""] * len(row)

st.dataframe(df.drop(columns=["_is_group"]).style.apply(_highlight, axis=1),
             use_container_width=True, hide_index=True)
```

Use a fixed number of leading spaces (not tabs) for the indentation string —
this renders consistently across browsers inside a dataframe cell.
