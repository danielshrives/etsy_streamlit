import streamlit as st
import pandas as pd
from db import get_connection

st.set_page_config(page_title="Orders", page_icon="✏️", layout="wide")
st.title("Orders")

try:
    conn = get_connection()
except Exception as e:
    st.error(f"Database connection failed: {e}")
    st.stop()

# Load people for dropdowns
with conn.cursor() as cur:
    cur.execute("SELECT person_id, person_name FROM people ORDER BY person_name")
    person_rows = cur.fetchall()
person_options = {row[0]: row[1] for row in person_rows}  # person_id → person_name
person_keys = [None] + list(person_options.keys())
person_name_to_id = {v: k for k, v in person_options.items()}
person_name_list = [""] + list(person_options.values())  # for SelectboxColumn

# Load packaging types for dropdowns
with conn.cursor() as cur:
    cur.execute('SELECT packaging_type_id, packaging_name FROM packaging ORDER BY packaging_name')
    pack_rows = cur.fetchall()
pack_options = {row[0]: row[1] for row in pack_rows}  # id → short_name
pack_keys = [None] + list(pack_options.keys())
pack_name_to_id = {v: k for k, v in pack_options.items()}
pack_name_list = [""] + list(pack_options.values())  # for SelectboxColumn

# Load orders
with conn.cursor() as cur:
    cur.execute("""
        SELECT order_id, etsy_order_id, sale_date, order_total, buyer_paid_shipping,
               shipping_label_cost, processing_fee, transaction_fee, taxes, credits,
               net_revenue, fulfillment_person, date_shipped, coupon_name, coupon_amount,
               packing_cost_id
        FROM orders
        ORDER BY sale_date DESC
    """)
    cols = [desc[0] for desc in cur.description]
    rows = cur.fetchall()

if not rows:
    st.info("No orders in the database yet. Use the Import page to load your Etsy CSV.")
    conn.close()
    st.stop()

df = pd.DataFrame(rows, columns=cols)

tab_table, tab_edit = st.tabs(["Table View", "Edit Order"])

# ── Tab: Table View ───────────────────────────────────────────────────────────

with tab_table:
    # Build display table for the editor
    table_df = df[["order_id", "sale_date", "etsy_order_id", "order_total",
                   "shipping_label_cost", "fulfillment_person", "packing_cost_id"]].copy()
    # Normalize types for data_editor
    table_df["shipping_label_cost"] = pd.to_numeric(table_df["shipping_label_cost"], errors="coerce")
    table_df["fulfillment_person"] = table_df["fulfillment_person"].fillna("")
    # Translate packing_cost_id → short_name for SelectboxColumn
    table_df["packaging"] = table_df["packing_cost_id"].map(lambda x: pack_options.get(x, "") if pd.notna(x) else "")

    edited_df = st.data_editor(
        table_df.drop(columns=["packing_cost_id"]),
        key="orders_table_editor",
        column_config={
            "order_id": None,  # hidden
            "sale_date": st.column_config.DateColumn("Date", disabled=True),
            "etsy_order_id": st.column_config.TextColumn("Order ID", disabled=True),
            "order_total": st.column_config.NumberColumn(
                "Order Total", format="$%.2f", disabled=True
            ),
            "shipping_label_cost": st.column_config.NumberColumn(
                "Shipping Label Cost", format="$%.2f", min_value=0.0, step=0.01
            ),
            "fulfillment_person": st.column_config.SelectboxColumn(
                "Fulfillment Person", options=person_name_list
            ),
            "packaging": st.column_config.SelectboxColumn(
                "Packaging", options=pack_name_list
            ),
        },
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
    )

    # Detect changes: numeric columns (NaN-aware) and string columns
    slc_orig = table_df["shipping_label_cost"]
    slc_edit = edited_df["shipping_label_cost"]
    slc_changed = ~((slc_edit == slc_orig) | (slc_edit.isna() & slc_orig.isna()))

    fp_changed = edited_df["fulfillment_person"] != table_df["fulfillment_person"]
    pkg_changed = edited_df["packaging"] != table_df["packaging"]

    changed_mask = slc_changed | fp_changed | pkg_changed
    n_changed = int(changed_mask.sum())

    if n_changed > 0:
        st.caption(f"**{n_changed}** row(s) with unsaved changes (shown below):")
        changed_preview = edited_df[changed_mask][
            ["etsy_order_id", "sale_date", "shipping_label_cost", "fulfillment_person", "packaging"]
        ].copy()
        changed_preview["shipping_label_cost"] = changed_preview["shipping_label_cost"].apply(
            lambda x: f"${x:.2f}" if pd.notna(x) else "—"
        )
        changed_preview["fulfillment_person"] = changed_preview["fulfillment_person"].replace("", "— none —")
        changed_preview["packaging"] = changed_preview["packaging"].replace("", "— none —")
        st.dataframe(changed_preview, use_container_width=False, hide_index=True)

        if st.button("Save All Changes", type="primary"):
            errors = []
            saved = 0
            for idx in edited_df[changed_mask].index:
                row = edited_df.loc[idx]
                slc_val = row["shipping_label_cost"]
                fp_val = row["fulfillment_person"] or None
                pkg_name = row["packaging"] or None
                pkg_id = pack_name_to_id.get(pkg_name) if pkg_name else None
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE orders SET shipping_label_cost=%s, fulfillment_person=%s, packing_cost_id=%s WHERE order_id=%s",
                            (
                                float(slc_val) if pd.notna(slc_val) else None,
                                fp_val,
                                pkg_id,
                                int(row["order_id"]),
                            ),
                        )
                    conn.commit()
                    saved += 1
                except Exception as e:
                    conn.rollback()
                    errors.append(f"Order {row['etsy_order_id']}: {e}")
            if errors:
                st.error("Some saves failed:\n" + "\n".join(errors))
            if saved > 0:
                st.success(f"Saved {saved} row(s).")
                st.rerun()
    else:
        st.caption("No unsaved changes.")

# ── Tab: Edit Order ───────────────────────────────────────────────────────────

with tab_edit:
    search = st.text_input("Search by Etsy Order ID or fulfillment person")
    filtered_df = df.copy()
    if search:
        mask = (
            filtered_df["etsy_order_id"].astype(str).str.contains(search, case=False) |
            filtered_df["fulfillment_person"].astype(str).str.contains(search, case=False, na=False)
        )
        filtered_df = filtered_df[mask]

    st.write(f"**{len(filtered_df)}** order(s)")

    if filtered_df.empty:
        st.info("No orders match that search.")
    else:
        selected_id = st.selectbox(
            "Select order to edit",
            options=filtered_df["order_id"].tolist(),
            format_func=lambda oid: (
                f"#{filtered_df.loc[filtered_df['order_id'] == oid, 'etsy_order_id'].iloc[0]}  —  "
                f"{filtered_df.loc[filtered_df['order_id'] == oid, 'sale_date'].iloc[0]}"
            ),
        )

        order = df[df["order_id"] == selected_id].iloc[0]

        st.divider()
        st.subheader(f"Order #{order['etsy_order_id']}  ·  {order['sale_date']}")

        # ── Financial breakdown ────────────────────────────────────────────────

        def fmt(val):
            return f"${float(val):,.2f}" if val is not None else "—"

        st.markdown("#### Buyer Paid")
        c1, c2, c3 = st.columns(3)
        c1.metric("Order Total", fmt(order["order_total"]))
        c2.metric("Buyer Paid Shipping", fmt(order["buyer_paid_shipping"]))
        coupon_label = f"Coupon ({order['coupon_name']})" if order["coupon_name"] else "Coupon"
        c3.metric(coupon_label, fmt(order["coupon_amount"]))

        st.markdown("#### Fees & Taxes")
        c4, c5, c6 = st.columns(3)
        c4.metric("Processing Fee", fmt(order["processing_fee"]))
        c5.metric("Transaction Fee", fmt(order["transaction_fee"]))
        c6.metric("Shipping Label Cost", fmt(order["shipping_label_cost"]))

        c7, c8, c9 = st.columns(3)
        c7.metric("Taxes", fmt(order["taxes"]))
        c8.metric("Credits", fmt(order["credits"]))
        c9.metric("Net Revenue", fmt(order["net_revenue"]))

        # ── Line items ─────────────────────────────────────────────────────────

        with conn.cursor() as cur:
            cur.execute("""
                SELECT listing_name, listing_id, qty, price
                FROM order_line_item
                WHERE order_id = %s
            """, (selected_id,))
            item_cols = [desc[0] for desc in cur.description]
            item_rows = cur.fetchall()

        if item_rows:
            st.markdown("#### Line Items")
            items_df = pd.DataFrame(item_rows, columns=item_cols)
            items_df["price"] = items_df["price"].apply(lambda x: f"${float(x):,.2f}" if x else "—")
            st.dataframe(items_df, use_container_width=True, hide_index=True)

        # ── Edit form ──────────────────────────────────────────────────────────

        st.markdown("#### Edit")
        with st.form("edit_order"):
            col1, col2, col3 = st.columns(3)

            with col1:
                shipping_label_cost = st.number_input(
                    "Shipping Label Cost ($)",
                    value=float(order["shipping_label_cost"] or 0),
                    min_value=0.0,
                    step=0.01,
                    format="%.2f",
                )
                net_revenue = st.number_input(
                    "Net Revenue ($)",
                    value=float(order["net_revenue"] or 0),
                    step=0.01,
                    format="%.2f",
                )

            with col2:
                current_person_id = person_name_to_id.get(order["fulfillment_person"])
                current_person_idx = person_keys.index(current_person_id) if current_person_id in person_keys else 0
                selected_person_id = st.selectbox(
                    "Fulfillment Person",
                    options=person_keys,
                    format_func=lambda pid: "— none —" if pid is None else person_options[pid],
                    index=current_person_idx,
                )
                date_shipped = st.date_input(
                    "Date Shipped",
                    value=order["date_shipped"] if pd.notna(order["date_shipped"]) else None,
                )

            with col3:
                current_pack_id = order["packing_cost_id"]
                current_pack_idx = pack_keys.index(current_pack_id) if current_pack_id in pack_keys else 0
                selected_pack_id = st.selectbox(
                    "Packaging",
                    options=pack_keys,
                    format_func=lambda pid: "— none —" if pid is None else pack_options[pid],
                    index=current_pack_idx,
                )

            submitted = st.form_submit_button("Save Changes", type="primary")

        if submitted:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE orders SET
                            shipping_label_cost = %s,
                            net_revenue         = %s,
                            fulfillment_person  = %s,
                            date_shipped        = %s,
                            packing_cost_id        = %s
                        WHERE order_id = %s
                        """,
                        (
                            shipping_label_cost or None,
                            net_revenue or None,
                            person_options[selected_person_id] if selected_person_id else None,
                            date_shipped,
                            selected_pack_id,
                            selected_id,
                        ),
                    )
                conn.commit()
                st.success("Order updated.")
                st.rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"Update failed: {e}")

conn.close()
