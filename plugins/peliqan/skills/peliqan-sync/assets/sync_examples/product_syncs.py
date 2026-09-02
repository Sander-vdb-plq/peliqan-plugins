# ============================================================
# SYNC EXAMPLES — the three product syncs, adapted to framework v4
# ============================================================
# Reference trios the sync-builder copies. Transport helpers live in the
# worker template; these add only sync-SPECIFIC constants/helpers.
# v2 conventions shown here:
#   - hash via stable_hash({owned fields}), NOT ad-hoc str concatenation
#   - process_<sync> RETURNS {"processed","errors","skipped"} for the run log
#   - registered in SYNC_REGISTRY with an optional "replay" handler
#
# The three examples are a PATTERN, not a menu — see sync-build.md for the
# full mechanism list (fan-out, branching, derived values, reconciliation…).
#
# Constants (declared near the other SYNC_* names):
#   SYNC_TEMPLATES   = "shopify_products_to_odoo_product_templates"
#   SYNC_VARIANTS    = "shopify_variants_to_odoo_product_products"
#   SYNC_VARIANT_OPS = "odoo_product_products_to_shopify_variants"


# ============================================================
# SYNC 1: shopify products -> odoo product templates (content)
# ============================================================
def fieldmapping_shopify_product_to_odoo_product_template(p):
    odoo_record = {
        "name": p.get("title") or "(no title)",
        "description_sale": p.get("descriptionHtml") or "",
        "active": (p.get("status") == "ACTIVE"),
        "sale_ok": True,
    }
    # hash ONLY the owned/mapped fields, via stable_hash
    owned = {"title": p.get("title"), "descriptionHtml": p.get("descriptionHtml"), "status": p.get("status")}
    return odoo_record, stable_hash(owned)


def process_shopify_product_to_odoo_product_template(sync_name, p):
    """Single-record 6 steps. Returns 'ok' | 'skip' | 'error' for counting."""
    source_id = gid_to_numeric(p.get("id"))
    st.subheader(f"[templates] {source_id} - {p.get('title')}")

    if not source_id or not p.get("title"):
        st.error("source_error: id or title missing")
        insert_link_row(sync_name, "insert", "source_error", shopify_id=source_id, shopify_source_json=p,
                        error_detail="source validation failed: id or title missing")
        return "error"

    target_id, last_hash = find_target(sync_name, source_id)
    odoo_record, new_hash = fieldmapping_shopify_product_to_odoo_product_template(p)
    if target_id and last_hash == new_hash:
        st.text("no change in hash -> skip")
        return "skip"

    action = "update" if target_id else "insert"
    try:
        result = odoo_object_update("product.template", target_id, odoo_record) if target_id \
            else odoo_object_add("product.template", odoo_record)
    except Exception as e:
        st.error(f"target_error: {e}")
        insert_link_row(sync_name, action, "target_error", shopify_id=source_id,
                        odoo_id=target_id, shopify_source_json=p, error_detail=e)
        return "error"

    ok = is_ok(result)
    if ok and not target_id:
        target_id = extract_new_id(result)
    insert_link_row(sync_name, action, "ok" if ok else "target_error",
                    shopify_id=source_id, odoo_id=target_id,
                    shopify_source_hash=new_hash if ok else None, shopify_source_json=p,
                    error_detail=None if ok else result)
    st.success(f"{action} ok - odoo_id = {target_id}") if ok else st.error(f"target_error: {result}")
    return "ok" if ok else "error"


def process_shopify_products_to_odoo_product_templates():
    sync_name = SYNC_TEMPLATES
    bookmark = get_bookmark(sync_name) or "2020-01-01T00:00:00Z"
    st.write(f"Sync: {sync_name} | bookmark: {bookmark}")

    products = sort_by_updated_at(shopify_list_incremental("products", bookmark_with_overlap(bookmark)))  # v4: overlap on connector-list paths (contract §6)
    st.write(f"Source records: {len(products)} (max {TEST_LIMIT if TEST_LIMIT else 'all'})")

    c = {"processed": 0, "errors": 0, "skipped": 0}
    high_water = bookmark
    for p in products:
        if _limit_reached(c["processed"]):
            st.info("TEST_LIMIT reached")
            break
        try:
            outcome = process_shopify_product_to_odoo_product_template(sync_name, p)
        except Exception as e:
            st.error(f"Unexpected error; recorded and continuing: {e}")
            insert_link_row(sync_name, "insert", "source_error",
                            shopify_id=gid_to_numeric(p.get("id")), shopify_source_json=p, error_detail=e)
            outcome = "error"
        if outcome == "error":
            c["errors"] += 1
        elif outcome == "skip":
            c["skipped"] += 1
        c["processed"] += 1
        high_water = advance_bookmark(high_water, p.get("updatedAt"))

    if str(high_water) > str(bookmark):
        set_bookmark(sync_name, high_water)
    st.write(f"New bookmark: {high_water} | {c}")
    return c


# ============================================================
# SYNC 2: shopify variants -> odoo product.product (ops SEED once)
# Parent dependency + orphan-freeze. Bookmark on variant updatedAt.
# ============================================================
CHANGED_VARIANTS_QUERY = (
    "query getChangedVariants($cursor: String, $q: String) { "
    "productVariants(first: 100, after: $cursor, query: $q) { "
    "edges { node { id title updatedAt sku barcode product { id } "
    "inventoryItem { measurement { weight { value unit } } } } } "
    "pageInfo { hasNextPage endCursor } } }"
)


def fetch_changed_shopify_variants(bookmark):
    variants, cursor = [], None
    query_filter = f"updated_at:>='{bookmark}'"  # v4: >= not > (equal-second boundary; contract §6)
    for _ in range(200):  # 200 pages * 100 = 20000 variants safety cap
        result = shopify_graphql(CHANGED_VARIANTS_QUERY, {"cursor": cursor, "q": query_filter})
        if not is_ok(result):
            st.warning("GraphQL productVariants query not ok")
            break
        block = (result.get("detail", {}).get("data", {}) or {}).get("productVariants") or {}
        variants.extend(e["node"] for e in (block.get("edges") or []) if e.get("node"))
        page_info = block.get("pageInfo", {}) or {}
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        if not cursor:
            break
    return variants


def weight_to_kg(value, unit):
    try:
        v = float(value)
    except Exception:
        return None
    return {"GRAMS": v / 1000.0, "POUNDS": v * 0.45359237, "OUNCES": v * 0.028349523}.get(unit, v)


def fieldmapping_shopify_variant_to_odoo_product_product(v):
    odoo_record = {}
    if v.get("sku"):
        odoo_record["default_code"] = v.get("sku")
    if v.get("barcode"):
        odoo_record["barcode"] = v.get("barcode")
    weight_info = (v.get("inventoryItem") or {}).get("measurement", {}).get("weight") or {}
    weight_kg = weight_to_kg(weight_info.get("value"), weight_info.get("unit")) if weight_info.get("value") else None
    if weight_kg:
        odoo_record["weight"] = weight_kg
    owned = {"sku": v.get("sku"), "barcode": v.get("barcode"),
             "weight": weight_info.get("value"), "title": v.get("title")}
    return odoo_record, stable_hash(owned)


def process_shopify_variant_to_odoo_product_product(sync_name, v, parent_odoo_id):
    source_id = gid_to_numeric(v.get("id"))
    st.subheader(f"[variants] {source_id} - {v.get('title')}")
    if not source_id:
        insert_link_row(sync_name, "insert", "source_error", shopify_source_json=v,
                        error_detail="source validation failed: variant id missing")
        return "error"

    target_id, _ = find_target(sync_name, source_id)
    if target_id:
        st.text("already linked; ops fields Odoo-owned -> skip")
        return "skip"

    try:
        variants = odoo_object_search("product.product", [["product_tmpl_id", "=", int(parent_odoo_id)]],
                                      ["id", "default_code", "barcode", "weight"])
    except Exception as e:
        insert_link_row(sync_name, "update", "target_error", shopify_id=source_id, shopify_source_json=v, error_detail=e)
        return "error"
    if not variants:
        insert_link_row(sync_name, "update", "target_error", shopify_id=source_id, shopify_source_json=v,
                        error_detail=f"no odoo product.product for product_tmpl_id={parent_odoo_id}")
        return "error"
    odoo_variant_id = variants[0]["id"]  # single-variant assumption; multi-variant = next phase

    odoo_record, new_hash = fieldmapping_shopify_variant_to_odoo_product_product(v)
    if odoo_record:
        try:
            result = odoo_object_update("product.product", odoo_variant_id, odoo_record)
        except Exception as e:
            insert_link_row(sync_name, "update", "target_error", shopify_id=source_id,
                            odoo_id=odoo_variant_id, shopify_source_json=v, error_detail=e)
            return "error"
        if not is_ok(result):
            insert_link_row(sync_name, "update", "target_error", shopify_id=source_id,
                            odoo_id=odoo_variant_id, shopify_source_json=v, error_detail=result)
            return "error"

    insert_link_row(sync_name, "update", "ok", shopify_id=source_id, odoo_id=odoo_variant_id,
                    shopify_source_hash=new_hash, shopify_source_json=v)
    st.success(f"variant linked + seeded - odoo id = {odoo_variant_id}")
    return "ok"


def _resolve_parent_odoo_id(v):
    parent_shopify_id = gid_to_numeric((v.get("product") or {}).get("id"))
    if not parent_shopify_id:
        return None
    parent_odoo_id, _ = find_target(SYNC_TEMPLATES, parent_shopify_id)
    return parent_odoo_id


def replay_one_variant(sync_name, v):
    """Replay adapter: resolves the parent before calling process_one (the fan-in
    context a plain replay can't supply). Skips if the parent still isn't linked."""
    parent = _resolve_parent_odoo_id(v)
    if not parent:
        st.text("replay skipped: parent still unlinked")
        return
    process_shopify_variant_to_odoo_product_product(sync_name, v, parent)


def process_shopify_variants_to_odoo_product_products():
    sync_name = SYNC_VARIANTS
    bookmark = get_bookmark(sync_name) or "2020-01-01T00:00:00Z"
    st.write(f"Sync: {sync_name} | bookmark: {bookmark}")

    variants = sort_by_updated_at(fetch_changed_shopify_variants(bookmark))
    st.write(f"Changed variants: {len(variants)} (max {TEST_LIMIT if TEST_LIMIT else 'all'})")

    c = {"processed": 0, "errors": 0, "skipped": 0}
    high_water, frozen, orphans = bookmark, False, 0
    for v in variants:
        if _limit_reached(c["processed"]):
            st.info("TEST_LIMIT reached")
            break
        parent_odoo_id = _resolve_parent_odoo_id(v)
        if not parent_odoo_id:
            # orphan: freeze bookmark; linking the parent later won't bump updatedAt
            orphans += 1
            frozen = True
            continue
        try:
            outcome = process_shopify_variant_to_odoo_product_product(sync_name, v, parent_odoo_id)
        except Exception as e:
            insert_link_row(sync_name, "update", "target_error",
                            shopify_id=gid_to_numeric(v.get("id")), shopify_source_json=v, error_detail=e)
            outcome = "error"
        if not frozen:
            high_water = advance_bookmark(high_water, v.get("updatedAt"))
        if outcome == "error":
            c["errors"] += 1
        elif outcome == "skip":
            c["skipped"] += 1
        c["processed"] += 1

    if str(high_water) > str(bookmark):
        set_bookmark(sync_name, high_water)
    c["skipped"] += orphans
    st.write(f"orphans deferred: {orphans} | new bookmark: {high_water} | {c}")
    return c


# ============================================================
# SYNC 3: odoo product.product -> shopify variants (ops fields)
# write_date drain; SEPARATE Odoo-format bookmark.
# ============================================================
VARIANT_UPDATE_MUTATION = (
    "mutation updateVariant($productId: ID!, $variants: [ProductVariantsBulkInput!]!) { "
    "productVariantsBulkUpdate(productId: $productId, variants: $variants) { "
    "productVariants { id sku barcode } userErrors { field message } } }"
)


def fieldmapping_odoo_product_product_to_shopify_variant(odoo_variant, shopify_variant_gid):
    variant_input = {"id": shopify_variant_gid}
    inventory_item = {}
    if odoo_variant.get("default_code"):
        inventory_item["sku"] = odoo_variant.get("default_code")
    if odoo_variant.get("weight"):
        inventory_item["measurement"] = {"weight": {"value": float(odoo_variant["weight"]), "unit": "KILOGRAMS"}}
    if inventory_item:
        variant_input["inventoryItem"] = inventory_item
    if odoo_variant.get("barcode"):
        variant_input["barcode"] = odoo_variant.get("barcode")
    owned = {"default_code": odoo_variant.get("default_code"), "barcode": odoo_variant.get("barcode"),
             "weight": odoo_variant.get("weight")}
    return variant_input, stable_hash(owned)


def process_odoo_product_product_to_shopify_variant(sync_name, odoo_variant, shopify_variant_id, parent_shopify_id):
    odoo_id = odoo_variant.get("id")
    st.subheader(f"[variant ops] odoo {odoo_id} -> shopify {shopify_variant_id}")

    _, last_hash = find_link_by_odoo(sync_name, odoo_id)
    variant_gid = f"gid://shopify/ProductVariant/{shopify_variant_id}"
    variant_input, new_hash = fieldmapping_odoo_product_product_to_shopify_variant(odoo_variant, variant_gid)
    if last_hash == new_hash:
        st.text("no change in hash -> skip")
        return "skip"

    if len(variant_input) == 1:
        insert_link_row(sync_name, "update", "ok", shopify_id=shopify_variant_id, odoo_id=odoo_id,
                        odoo_source_hash=new_hash, odoo_source_json=odoo_variant)
        return "ok"

    variables = {"productId": f"gid://shopify/Product/{parent_shopify_id}", "variants": [variant_input]}
    try:
        result = shopify_graphql(VARIANT_UPDATE_MUTATION, variables)
    except Exception as e:
        insert_link_row(sync_name, "update", "target_error", shopify_id=shopify_variant_id, odoo_id=odoo_id,
                        odoo_source_json=odoo_variant, error_detail=e)
        return "error"

    user_errors = graphql_user_errors(result, "productVariantsBulkUpdate")
    if not is_ok(result) or user_errors:
        insert_link_row(sync_name, "update", "target_error", shopify_id=shopify_variant_id, odoo_id=odoo_id,
                        odoo_source_json=odoo_variant, error_detail=user_errors or result)
        return "error"

    insert_link_row(sync_name, "update", "ok", shopify_id=shopify_variant_id, odoo_id=odoo_id,
                    odoo_source_hash=new_hash, odoo_source_json=odoo_variant)
    st.success(f"variant ops pushed - variant {shopify_variant_id}")
    return "ok"


def process_odoo_product_products_to_shopify_variants():
    sync_name = SYNC_VARIANT_OPS
    bookmark = get_bookmark(sync_name) or "2020-01-01 00:00:00"   # Odoo write_date format
    st.write(f"Sync: {sync_name} | bookmark: {bookmark}")

    fields = ["id", "product_tmpl_id", "default_code", "barcode", "weight", "write_date"]
    c = {"processed": 0, "errors": 0, "skipped": 0}
    high_water, limit_hit = bookmark, False

    for rows in odoo_search_read_incremental("product.product", fields, bookmark):
        for odoo_variant in rows:
            if _limit_reached(c["processed"]):
                st.info("TEST_LIMIT reached"); limit_hit = True; break
            odoo_id = odoo_variant.get("id")
            shopify_variant_id, _ = find_link_by_odoo(SYNC_VARIANTS, odoo_id)
            if not shopify_variant_id:
                high_water = advance_bookmark(high_water, odoo_variant.get("write_date")); continue
            tmpl = odoo_variant.get("product_tmpl_id")
            tmpl_id = tmpl[0] if isinstance(tmpl, (list, tuple)) else tmpl
            parent_shopify_id, _ = find_link_by_odoo(SYNC_TEMPLATES, tmpl_id)
            if not parent_shopify_id:
                high_water = advance_bookmark(high_water, odoo_variant.get("write_date")); continue
            try:
                outcome = process_odoo_product_product_to_shopify_variant(
                    sync_name, odoo_variant, shopify_variant_id, parent_shopify_id)
            except Exception as e:
                insert_link_row(sync_name, "update", "target_error", shopify_id=shopify_variant_id, odoo_id=odoo_id,
                                odoo_source_json=odoo_variant, error_detail=e)
                outcome = "error"
            high_water = advance_bookmark(high_water, odoo_variant.get("write_date"))
            if outcome == "error":
                c["errors"] += 1
            elif outcome == "skip":
                c["skipped"] += 1
            c["processed"] += 1
        if limit_hit:
            break

    if str(high_water) > str(bookmark):
        set_bookmark(sync_name, high_water)
    st.write(f"new bookmark: {high_water} | {c}")
    return c


# --- SYNC_REGISTRY entries (dependency order) ---
#   {"name": SYNC_TEMPLATES,   "run": process_shopify_products_to_odoo_product_templates,
#    "replay": process_shopify_product_to_odoo_product_template},          # direct replay
#   {"name": SYNC_VARIANTS,    "run": process_shopify_variants_to_odoo_product_products,
#    "replay": replay_one_variant},                                        # adapter (resolves parent)
#   {"name": SYNC_VARIANT_OPS, "run": process_odoo_product_products_to_shopify_variants},
#                                                                          # no replay: reprocessed by the drain
