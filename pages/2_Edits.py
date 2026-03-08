import streamlit as st
import pandas as pd
from db import get_connection

st.set_page_config(page_title="Edit Orders", page_icon="✏️", layout="wide")
st.title("Edit Orders")

try:
    conn = get_connection()
except Exception as e:
    st.error(f"Database connection failed: {e}")
    st.stop()

# Load orders
with conn.cursor() as cur:
    cur.execute("""
        SELECT order_id, etsy_order_id, sale_date, order_total, buyer_paid_shipping,
               shipping_label_cost, processing_fee, transaction_fee, taxes, credits,
               net_revenue, fulfillment_person, date_shipped, coupon_name, coupon_amount
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

# Search / filter
search = st.text_input("Search by Etsy Order ID or fulfillment person")
if search:
    mask = (
        df["etsy_order_id"].astype(str).str.contains(search, case=False) |
        df["fulfillment_person"].astype(str).str.contains(search, case=False, na=False)
    )
    df = df[mask]

st.write(f"**{len(df)}** order(s)")

# Select an order to edit
selected_id = st.selectbox(
    "Select order to edit",
    options=df["order_id"].tolist(),
    format_func=lambda oid: (
        f"#{df.loc[df['order_id'] == oid, 'etsy_order_id'].iloc[0]}  —  "
        f"{df.loc[df['order_id'] == oid, 'sale_date'].iloc[0]}"
    ),
)

order = df[df["order_id"] == selected_id].iloc[0]

st.divider()
st.subheader(f"Order #{order['etsy_order_id']}  ·  {order['sale_date']}")

# ── Financial breakdown ───────────────────────────────────────────────────────

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

# ── Line items ────────────────────────────────────────────────────────────────

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

# ── Edit form ─────────────────────────────────────────────────────────────────

st.markdown("#### Edit")
with st.form("edit_order"):
    col1, col2 = st.columns(2)

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
        fulfillment_person = st.text_input(
            "Fulfillment Person",
            value=order["fulfillment_person"] or "",
        )
        date_shipped = st.date_input(
            "Date Shipped",
            value=order["date_shipped"],
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
                    date_shipped        = %s
                WHERE order_id = %s
                """,
                (
                    shipping_label_cost or None,
                    net_revenue or None,
                    fulfillment_person or None,
                    date_shipped,
                    selected_id,
                ),
            )
        conn.commit()
        st.success("Order updated.")
    except Exception as e:
        conn.rollback()
        st.error(f"Update failed: {e}")

conn.close()
