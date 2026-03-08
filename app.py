import streamlit as st
from db import get_connection

st.set_page_config(page_title="Etsy Dashboard", page_icon="🛍️", layout="wide")
st.title("Dashboard")

try:
    conn = get_connection()
except Exception as e:
    st.error(f"Database connection failed: {e}")
    st.stop()

with conn.cursor() as cur:
    cur.execute("""
        SELECT
            COUNT(*)                        AS total_orders,
            COALESCE(SUM(order_total), 0)   AS total_revenue,
            COALESCE(AVG(order_total), 0)   AS avg_order_value,
            COUNT(CASE WHEN sale_date >= date_trunc('month', CURRENT_DATE) THEN 1 END)
                                            AS orders_this_month,
            COALESCE(SUM(CASE WHEN sale_date >= date_trunc('month', CURRENT_DATE)
                         THEN order_total END), 0)
                                            AS revenue_this_month
        FROM orders
    """)
    row = cur.fetchone()

total_orders, total_revenue, avg_order, orders_this_month, revenue_this_month = row

col1, col2, col3 = st.columns(3)
col1.metric("Total Orders", f"{total_orders:,}")
col2.metric("Total Revenue", f"${total_revenue:,.2f}")
col3.metric("Avg Order Value", f"${avg_order:,.2f}")

st.divider()

col4, col5 = st.columns(2)
col4.metric("Orders This Month", f"{orders_this_month:,}")
col5.metric("Revenue This Month", f"${revenue_this_month:,.2f}")

st.divider()

# Recent orders table
st.subheader("Recent Orders")
with conn.cursor() as cur:
    cur.execute("""
        SELECT etsy_order_id, sale_date, order_total, buyer_paid_shipping,
               coupon_name, coupon_amount, date_shipped
        FROM orders
        ORDER BY sale_date DESC
        LIMIT 20
    """)
    cols = [desc[0] for desc in cur.description]
    rows = cur.fetchall()

conn.close()

import pandas as pd
if rows:
    df = pd.DataFrame(rows, columns=cols)
    df["order_total"] = df["order_total"].apply(lambda x: f"${x:,.2f}" if x else "")
    df["buyer_paid_shipping"] = df["buyer_paid_shipping"].apply(lambda x: f"${x:,.2f}" if x else "")
    df["coupon_amount"] = df["coupon_amount"].apply(lambda x: f"${x:,.2f}" if x else "")
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("No orders found. Use the Import page to load your Etsy CSV.")
