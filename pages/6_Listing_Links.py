import streamlit as st
import pandas as pd
from db import get_connection

st.set_page_config(page_title="Listing Links", page_icon="🔗", layout="wide")
st.title("Listing Links")

try:
    conn = get_connection()
except Exception as e:
    st.error(f"Database connection failed: {e}")
    st.stop()

# Load products for SKU dropdown
with conn.cursor() as cur:
    cur.execute('SELECT "SKU" FROM products ORDER BY "SKU"')
    sku_rows = cur.fetchall()
sku_options = [None] + [row[0] for row in sku_rows]

# Load existing links
with conn.cursor() as cur:
    cur.execute("""
        SELECT listing_id, etsy_listing_id, "SKU", listing_name, variation, qty
        FROM listing_link
        ORDER BY listing_name, variation, "SKU"
    """)
    link_cols = [desc[0] for desc in cur.description]
    link_rows = cur.fetchall()

links_df = pd.DataFrame(link_rows, columns=link_cols) if link_rows else pd.DataFrame(columns=link_cols)

# Load all distinct (listing_id, variation) pairs from orders
with conn.cursor() as cur:
    cur.execute("""
        SELECT oli.listing_id,
               oli.variation,
               MAX(oli.listing_name) AS listing_name
        FROM order_line_item oli
        WHERE oli.listing_id IS NOT NULL
        GROUP BY oli.listing_id, oli.variation
        ORDER BY listing_name, oli.variation
    """)
    all_pairs = cur.fetchall()

tab_all, tab_unlinked, tab_add, tab_edit = st.tabs(["All Links", "Unlinked", "Add Link", "Edit Link"])

# ── Tab: All Links ────────────────────────────────────────────────────────────

with tab_all:
    search_id = st.text_input("Search by Etsy Listing ID", key="search_all")
    if not links_df.empty:
        display = links_df[["etsy_listing_id", "listing_name", "variation", "SKU", "qty"]].copy()
        display["variation"] = display["variation"].fillna("—")
        if search_id:
            display = display[display["etsy_listing_id"].astype(str).str.contains(search_id.strip(), case=False)]
        st.dataframe(display, use_container_width=True, hide_index=True)
    else:
        st.info("No listing links yet.")

# ── Tab: Unlinked ─────────────────────────────────────────────────────────────

with tab_unlinked:
    if not all_pairs:
        st.info("No orders imported yet.")
    else:
        linked_keys = set()
        if not links_df.empty:
            for _, row in links_df.iterrows():
                linked_keys.add((row["etsy_listing_id"], row["variation"] if pd.notna(row["variation"]) else None))

        unlinked = [
            (listing_id, variation, listing_name)
            for listing_id, variation, listing_name in all_pairs
            if (listing_id, variation) not in linked_keys
        ]

        if not unlinked:
            st.success("All listings are linked.")
        else:
            unlinked_df = pd.DataFrame(unlinked, columns=["etsy_listing_id", "variation", "listing_name"])
            unlinked_df["variation"] = unlinked_df["variation"].fillna("—")
            st.dataframe(
                unlinked_df[["etsy_listing_id", "listing_name", "variation"]],
                use_container_width=True,
                hide_index=True,
            )

# ── Tab: Add Link ─────────────────────────────────────────────────────────────

with tab_add:
    if not all_pairs:
        st.info("No orders imported yet.")
    else:
        pair_map = {(row[0], row[1]): row[2] for row in all_pairs}
        pair_keys = list(pair_map.keys())

        def fmt_pair(key):
            return pair_map[key] or "(no name)"

        selected_key = st.selectbox(
            "Etsy Listing / Variation",
            options=pair_keys,
            format_func=fmt_pair,
        )
        if selected_key:
            col_prev1, col_prev2, col_prev3 = st.columns(3)
            with col_prev1:
                st.text_input(
                    "Etsy Listing ID",
                    value=str(selected_key[0]),
                    disabled=True,
                )
            with col_prev2:
                st.text_area(
                    "Listing Name",
                    value=pair_map[selected_key] or "(no name)",
                    height=80,
                    disabled=True,
                )
            with col_prev3:
                st.text_area(
                    "Variation",
                    value=selected_key[1] or "— none —",
                    height=80,
                    disabled=True,
                )

            # Show SKUs already linked to this listing/variation
            if not links_df.empty:
                existing = links_df[
                    (links_df["etsy_listing_id"] == selected_key[0]) &
                    (links_df["variation"].isna() if selected_key[1] is None
                     else links_df["variation"] == selected_key[1])
                ]
                if not existing.empty:
                    st.caption("Already linked SKUs for this listing/variation:")
                    st.dataframe(
                        existing[["SKU", "qty"]].reset_index(drop=True),
                        use_container_width=False,
                        hide_index=True,
                    )

        with st.form("add_link"):
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                new_sku = st.selectbox(
                    "SKU",
                    options=sku_options,
                    format_func=lambda s: "— none —" if s is None else s,
                )
            with col_f2:
                new_qty = st.number_input("Qty in Listing", min_value=1, step=1, value=1)
            submitted = st.form_submit_button("Add Link", type="primary")

        if submitted:
            if new_sku is None:
                st.error("SKU is required.")
            else:
                sel_listing_id, sel_variation = selected_key
                listing_name = pair_map.get(selected_key)
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO listing_link (etsy_listing_id, "SKU", listing_name, variation, qty)
                            VALUES (%s, %s, %s, %s, %s)
                            """,
                            (sel_listing_id, new_sku, listing_name, sel_variation, new_qty),
                        )
                    conn.commit()
                    label = f"{listing_name}{' — ' + sel_variation if sel_variation else ''}"
                    st.success(f"Linked '{label}' → {new_sku} (qty {new_qty}).")
                    st.rerun()
                except Exception as e:
                    conn.rollback()
                    st.error(f"Failed: {e}")

# ── Tab: Edit Link ────────────────────────────────────────────────────────────

with tab_edit:
    if links_df.empty:
        st.info("No listing links yet.")
    else:
        search_edit = st.text_input("Search by Etsy Listing ID", key="search_edit")
        edit_df = links_df.copy()
        if search_edit:
            edit_df = edit_df[edit_df["etsy_listing_id"].astype(str).str.contains(search_edit.strip(), case=False)]

        if edit_df.empty:
            st.info("No links match that listing ID.")
        else:
            def fmt_link(lid):
                row = links_df.loc[links_df["listing_id"] == lid].iloc[0]
                name = row["listing_name"] or "(no name)"
                var = row["variation"]
                sku = row["SKU"]
                qty = row["qty"]
                return f"{name}{' — ' + var if var else ''} · {sku} ×{qty}"

            selected_id = st.selectbox(
                "Select link to edit",
                options=edit_df["listing_id"].tolist(),
                format_func=fmt_link,
            )
            link = links_df[links_df["listing_id"] == selected_id].iloc[0]

            current_sku_idx = (
                sku_options.index(link["SKU"])
                if link["SKU"] in sku_options
                else 0
            )

            with st.form("edit_link"):
                col1, col2 = st.columns(2)
                with col1:
                    st.text_input("Etsy Listing ID", value=str(link["etsy_listing_id"]), disabled=True)
                    st.text_input("Listing Name", value=link["listing_name"] or "", disabled=True)
                    st.text_input("Variation", value=link["variation"] or "—", disabled=True)
                with col2:
                    edit_sku = st.selectbox(
                        "SKU",
                        options=sku_options,
                        format_func=lambda s: "— none —" if s is None else s,
                        index=current_sku_idx,
                    )
                    edit_qty = st.number_input(
                        "Qty in Listing",
                        min_value=1,
                        step=1,
                        value=int(link["qty"]) if pd.notna(link["qty"]) else 1,
                    )
                col_save, col_del = st.columns(2)
                with col_save:
                    save = st.form_submit_button("Save Changes", type="primary")
                with col_del:
                    delete = st.form_submit_button("Delete Link")

            if save:
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            'UPDATE listing_link SET "SKU" = %s, qty = %s WHERE listing_id = %s',
                            (edit_sku, edit_qty, selected_id),
                        )
                    conn.commit()
                    st.success("Link updated.")
                    st.rerun()
                except Exception as e:
                    conn.rollback()
                    st.error(f"Failed: {e}")

            if delete:
                try:
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM listing_link WHERE listing_id = %s", (selected_id,))
                    conn.commit()
                    st.success("Link deleted.")
                    st.rerun()
                except Exception as e:
                    conn.rollback()
                    st.error(f"Failed: {e}")

conn.close()
