# System reference: Odoo

Answers the standard system checklist (`_checklist.md`) for Odoo, plus
transport quirks verified live (connection `Odoo`, generic `object` endpoint).

## Checklist answers

| question | answer |
| --- | --- |
| Change-timestamp field + format | `write_date`, `YYYY-MM-DD HH:MM:SS` (**no T, no Z** — never compare against an ISO bookmark; separate bookmark namespace per contract §6) |
| Timestamp granularity | **seconds** — equal-timestamp clusters are normal (batch writes) |
| Comparator under our control? | **yes** — search_read domain: `[["write_date", ">=", bookmark]]` (v4) |
| Record id shape | integer `id`; many2one fields return `[id, display_name]` — take `[0]` |
| Incremental read | `search_read` with `order: "write_date asc"`, offset-paged until an empty page |
| Functional error on a 200 | `is_ok(result)` (`status == "success"`); a single-row search may return a dict — normalise to list |
| Writeback | generic `object` endpoint: `add` / `update` / `search`, one record per call |
| Delete semantics | `active = False` (archive) vs `unlink` — per-sync decision; consequences differ for open SO lines, accounting refs, GDPR |

## Transport quirks (hard-won)

- **Implicit `active = true` filter.** Odoo search silently excludes archived
  records. Anywhere inactive records matter (auto-variants of DRAFT/archived
  templates, archived partners), add `["active", "in", [True, False]]` to the
  domain — a missing record here looks like a target_error, not a filter.
- **Quant changes don't bump `product.write_date`.** Stock cannot be drained
  by write_date on the product; use a reconciliation sweep over linked records
  reading `qty_available` (hash-skip keeps it cheap).
- **Template/variant split.** `product.template` (definition) vs
  `product.product` (variant with SKU). Standard mapping: one template per
  source product, variants as `product.product`. Creating a template
  auto-creates a first variant; multi-variant matching requires reconciling
  attribute values on the template first.
- **Kit stock** (`mrp.bom` type=phantom) derives from the least-available
  component — never read `stock.quant` for the kit itself.
- **Customers/addresses:** parent/child `res.partner` hierarchy (child
  `type='delivery'`/`'invoice'`); reconcile on `parent_id + type` + source
  address id, not on email. Flattening silently drops address history.
- **Datetime writes:** Odoo expects `YYYY-MM-DD HH:MM:SS` — convert ISO by
  stripping `T`/`Z`.
