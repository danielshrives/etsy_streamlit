import streamlit as st
import pandas as pd
from db import get_connection

st.set_page_config(page_title="Stats", page_icon="📊", layout="wide")
st.title("Stats")

try:
    conn = get_connection()
except Exception as e:
    st.error(f"Database connection failed: {e}")
    st.stop()

# ── Net Revenue per Printer Minute ────────────────────────────────────────────

st.subheader("Net Revenue per Printer Minute")

with conn.cursor() as cur:
    cur.execute("""
        WITH avg_net AS (
            SELECT ll."SKU",
                   AVG(
                       (oli.price - (
                           COALESCE(o.shipping_label_cost, 0)
                           + COALESCE(o.processing_fee, 0)
                           + COALESCE(o.transaction_fee, 0)
                           + COALESCE(o.taxes, 0)
                           - COALESCE(o.credits, 0)
                       ) / NULLIF(item_counts.cnt, 0)) / NULLIF(total_ll.total_qty, 0)
                   ) AS avg_net_revenue
            FROM listing_link ll
            JOIN order_line_item oli
                ON  oli.listing_id = ll.etsy_listing_id
                AND oli.variation IS NOT DISTINCT FROM ll.variation
            JOIN orders o ON o.order_id = oli.order_id
            JOIN (
                SELECT order_id, SUM(COALESCE(qty, 1)) AS cnt
                FROM order_line_item
                GROUP BY order_id
            ) item_counts ON item_counts.order_id = oli.order_id
            JOIN (
                SELECT etsy_listing_id, variation, SUM(qty) AS total_qty
                FROM listing_link
                GROUP BY etsy_listing_id, variation
            ) total_ll
                ON  total_ll.etsy_listing_id = ll.etsy_listing_id
                AND total_ll.variation IS NOT DISTINCT FROM ll.variation
            WHERE oli.price IS NOT NULL
            GROUP BY ll."SKU"
        ),
        machine_mins AS (
            SELECT p."SKU", p.short_name,
                   COALESCE(SUM(pt.machine_minutes), 0) AS total_machine_minutes
            FROM products p
            LEFT JOIN parts pt ON pt.product_id = p.product_id
            GROUP BY p."SKU", p.short_name
        )
        SELECT
            mm."SKU",
            mm.short_name,
            mm.total_machine_minutes,
            an.avg_net_revenue,
            CASE WHEN mm.total_machine_minutes > 0
                 THEN an.avg_net_revenue / mm.total_machine_minutes
                 ELSE NULL
            END AS net_per_machine_minute
        FROM machine_mins mm
        JOIN avg_net an ON an."SKU" = mm."SKU"
        ORDER BY net_per_machine_minute DESC NULLS LAST
    """)
    cols = [desc[0] for desc in cur.description]
    rows = cur.fetchall()

conn.close()

if not rows:
    st.info("Not enough data yet — import orders and link listings to products first.")
    st.stop()

df = pd.DataFrame(rows, columns=cols)
for col in ["avg_net_revenue", "net_per_machine_minute"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")

label_col = df["short_name"].where(df["short_name"].notna() & (df["short_name"] != ""), df["SKU"])

chart_df = df[df["net_per_machine_minute"].notna()].copy()
chart_df["label"] = label_col[chart_df.index]
chart_df = chart_df.set_index("label")

st.bar_chart(chart_df["net_per_machine_minute"], y_label="$ per printer minute", x_label="Product")

st.divider()

display = df.copy()
display["label"] = label_col
display = display[["label", "SKU", "total_machine_minutes", "avg_net_revenue", "net_per_machine_minute"]]
display["avg_net_revenue"] = display["avg_net_revenue"].apply(lambda x: f"${x:.2f}" if pd.notna(x) else "—")
display["net_per_machine_minute"] = display["net_per_machine_minute"].apply(lambda x: f"${x:.4f}" if pd.notna(x) else "—")
display.columns = ["Name", "SKU", "Printer Minutes", "Avg Net Revenue", "$ / Printer Min"]
st.dataframe(display, use_container_width=True, hide_index=True)
