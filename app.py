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

# Revenue over time chart
import pandas as pd

st.subheader("Revenue Over Time")
with conn.cursor() as cur:
    cur.execute("""
        SELECT sale_date, SUM(order_total) AS revenue
        FROM orders
        WHERE sale_date IS NOT NULL
        GROUP BY sale_date
        ORDER BY sale_date
    """)
    rev_rows = cur.fetchall()

conn.close()

if rev_rows:
    rev_df = pd.DataFrame(rev_rows, columns=["date", "revenue"])
    rev_df["revenue"] = pd.to_numeric(rev_df["revenue"], errors="coerce")
    rev_df["cumulative_revenue"] = rev_df["revenue"].cumsum()
    rev_df = rev_df.set_index("date")
    st.line_chart(rev_df["cumulative_revenue"], y_label="Cumulative Revenue ($)", x_label="Date")
else:
    st.info("No orders found. Use the Import page to load your Etsy CSV.")
