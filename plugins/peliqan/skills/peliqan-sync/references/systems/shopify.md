# System reference: Shopify

Answers the standard system checklist (`_checklist.md`) for Shopify, plus
transport quirks verified live on account 3024 (`Shopify V2` connection,
GraphQL Admin API). The framework contract stays system-agnostic; everything
Shopify-specific belongs here.

## Checklist answers

| question | answer |
| --- | --- |
| Change-timestamp field + format | `updatedAt`, ISO `YYYY-MM-DDTHH:MM:SSZ` |
| Timestamp granularity | **seconds** — equal-timestamp clusters are normal (bulk imports) |
| Comparator under our control? | GraphQL search filter: **yes** → use `updated_at:>='{bookmark}'`. Connector `list(bookmark=)`: **no** → pass `bookmark_with_overlap(bookmark)` |
| Record id shape | gid `gid://shopify/<Type>/<numeric>`; store the numeric (`gid_to_numeric`). MailingAddress gids can carry a query string (`?model_name=...`) — strip it |
| Incremental read | cursor-paged GraphQL: `<objects>(first: N, after: $cursor, query: $q)` with `pageInfo { hasNextPage endCursor }`; page cap as a safety net |
| Functional error on a 200 | TWO layers: top-level `detail.errors` (e.g. ACCESS_DENIED yields 200 + `data: null` — looks like an empty set if unchecked) AND per-mutation `userErrors` (`graphql_user_errors`) |
| Writeback | GraphQL mutations, **one record per call** (e.g. `productVariantsBulkUpdate` with exactly 1 variant) |
| Delete semantics | archive (status) vs true delete; GDPR webhooks for customers — per-sync decision |

## Transport quirks (hard-won)

- **Single-line GraphQL only.** The Peliqan edge rejects multi-line query
  strings: `shopify_api.apicall(path="graphql.json", query=<single line>,
  variables=...)`. The helper collapses whitespace, but write constants
  single-line anyway.
- **Protected Customer Data (PCD).** `customers` (and the `customer` field on
  orders) require separate PCD approval in the **Partner Dashboard** (app →
  API access → Protected customer data access: enable the data level AND the
  field-level toggles name/email/phone/address). This is a different layer
  than API scopes; store-admin custom apps are exempt. Until granted, Shopify
  returns 200 + top-level `errors` (ACCESS_DENIED) + `data: null` — surface it
  loudly and freeze the bookmark; the sync self-heals when access lands. Dev
  stores: immediate, no review.
- **Search filter syntax** supports `updated_at:>=`, `:>`, `:<` etc. with the
  ISO timestamp quoted. Filter granularity is per second.
- **Inventory:** `inventorySetQuantities` fails with "not stocked at the
  location" unless the location is one where the item is stocked — resolve the
  item's OWN stocked location first (`inventoryItem { inventoryLevels }`).
  `tracked: false` items (gift cards) have nothing to set — settle as a no-op.
- **Fulfillment:** create against OPEN/IN_PROGRESS/SCHEDULED fulfillment
  orders; fulfillments are immutable once created.
- **Variant model:** flat Product → ProductVariant; matching to a
  template+variant model (Odoo, SAP) needs option-value matching for
  multi-variant products — a single-variant assumption silently collapses all
  variants onto one target record.
