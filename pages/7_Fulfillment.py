import streamlit as st
import pandas as pd
from db import get_connection

st.set_page_config(page_title="Fulfillment", page_icon="📬", layout="wide")
st.title("Fulfillment")

try:
    conn = get_connection()
except Exception as e:
    st.error(f"Database connection failed: {e}")
    st.stop()

# Load people
with conn.cursor() as cur:
    cur.execute("SELECT person_id, person_name FROM people ORDER BY person_name")
    person_rows = cur.fetchall()

if not person_rows:
    st.info("No people in the database yet.")
    conn.close()
    st.stop()

person_options = {row[0]: row[1] for row in person_rows}

selected_person_id = st.selectbox(
    "Fulfillment Person",
    options=list(person_options.keys()),
    format_func=lambda pid: person_options[pid],
)
selected_person_name = person_options[selected_person_id]

st.divider()

# ── Query ─────────────────────────────────────────────────────────────────────
# One row per (order, SKU) where the product owner != fulfillment person.
# Revenue is split proportionally by ll.qty / total listing qty.
# Fulfiller cost = (filament + machine + labor) × units produced.
# Net proceeds = revenue − fulfiller cost.
# Fulfiller payment = 30% × net proceeds.

with conn.cursor() as cur:
    cur.execute("""
        WITH total_qty_per_listing AS (
            SELECT etsy_listing_id, variation, SUM(qty) AS total_qty
            FROM listing_link
            GROUP BY etsy_listing_id, variation
        ),
        product_unit_costs AS (
            SELECT
                p.product_id,
                COALESCE(SUM(pt.grams_material * f.cost_per_gram), 0) AS filament_cost,
                COALESCE(SUM(pt.machine_minutes), 0) * 0.007             AS machine_cost,
                COALESCE(p.labor_minutes, 0) * (20.0 / 60)              AS labor_cost
            FROM products p
            LEFT JOIN parts     pt ON pt.product_id  = p.product_id
            LEFT JOIN filaments f  ON f.filament_id  = pt.filament_id
            GROUP BY p.product_id, p.labor_minutes
        )
        SELECT
            o.etsy_order_id,
            o.sale_date,
            p."SKU",
            p.short_name,
            owner_p.person_name                                                     AS owner,
            COALESCE(oli.qty, 1) * ll.qty                                          AS total_units,
            -- Revenue for this SKU: proportional share of line-item price
            CAST(COALESCE(oli.price, 0) AS numeric)
                * ll.qty / NULLIF(tq.total_qty, 0)                                 AS revenue,
            -- Fulfiller cost breakdown × units
            CAST(COALESCE(oli.qty, 1) * ll.qty AS numeric) * puc.filament_cost     AS filament_total,
            CAST(COALESCE(oli.qty, 1) * ll.qty AS numeric) * puc.machine_cost      AS machine_total,
            CAST(COALESCE(oli.qty, 1) * ll.qty AS numeric) * puc.labor_cost        AS labor_total,
            -- Fulfiller cost total
            CAST(COALESCE(oli.qty, 1) * ll.qty AS numeric)
                * (puc.filament_cost + puc.machine_cost + puc.labor_cost)           AS fulfiller_cost,
            o.order_id
        FROM orders o
        JOIN order_line_item oli ON oli.order_id = o.order_id
        JOIN listing_link ll
            ON  ll.etsy_listing_id = oli.listing_id
            AND ll.variation IS NOT DISTINCT FROM oli.variation
        JOIN products p ON p."SKU" = ll."SKU"
        LEFT JOIN product_unit_costs    puc     ON puc.product_id     = p.product_id
        LEFT JOIN total_qty_per_listing tq
            ON  tq.etsy_listing_id = ll.etsy_listing_id
            AND tq.variation IS NOT DISTINCT FROM ll.variation
        LEFT JOIN people owner_p ON owner_p.person_id = p.owner_id
        WHERE o.fulfillment_person = %s
          AND p.owner_id IS NOT NULL
          AND p.owner_id != %s
        ORDER BY o.sale_date DESC, o.etsy_order_id, p."SKU"
    """, (selected_person_name, selected_person_id))
    cols = [desc[0] for desc in cur.description]
    rows = cur.fetchall()

if not rows:
    st.info(f"No cross-owner fulfilled items found for **{selected_person_name}**.")
    conn.close()
    st.stop()

df = pd.DataFrame(rows, columns=cols)

for col in ["revenue", "fulfiller_cost", "filament_total", "machine_total", "labor_total"]:
    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

df["markup"]            = df["fulfiller_cost"] * 0.40
df["total_to_fulfiller"]= df["fulfiller_cost"] + df["markup"]
df["net_proceeds"]      = df["revenue"]
df["owner_payment"]     = df["net_proceeds"] - df["total_to_fulfiller"]

# ── Summary metrics ───────────────────────────────────────────────────────────

c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
c1.metric("Line Items", len(df))
c2.metric("Revenue", f"${df['revenue'].sum():,.2f}")
c3.metric("Fulfiller Cost", f"${df['fulfiller_cost'].sum():,.2f}")
c4.metric("Markup (40%)", f"${df['markup'].sum():,.2f}")
c5.metric("Total to Fulfiller", f"${df['total_to_fulfiller'].sum():,.2f}")
c6.metric("Net Proceeds", f"${df['net_proceeds'].sum():,.2f}")
c7.metric("Owner Payment", f"${df['owner_payment'].sum():,.2f}")

st.divider()

# ── Per-owner summary ─────────────────────────────────────────────────────────

st.subheader("Summary by Owner")
owner_summary = (
    df.groupby("owner", as_index=False)
    .agg(
        items=("revenue", "count"),
        revenue=("revenue", "sum"),
        fulfiller_cost=("fulfiller_cost", "sum"),
        markup=("markup", "sum"),
        total_to_fulfiller=("total_to_fulfiller", "sum"),
        owner_payment=("owner_payment", "sum"),
    )
)
for col in ["revenue", "fulfiller_cost", "markup", "total_to_fulfiller", "owner_payment"]:
    owner_summary[col] = owner_summary[col].apply(lambda x: f"${x:,.2f}")
owner_summary.columns = ["Owner", "Items", "Revenue", "Fulfiller Cost", "Markup (40%)", "Total to Fulfiller", "Owner Payment"]
st.dataframe(owner_summary, use_container_width=True, hide_index=True)

st.divider()

# ── Detail table ──────────────────────────────────────────────────────────────

st.subheader("Detail")
display = df[[
    "etsy_order_id", "sale_date", "SKU", "short_name", "owner",
    "total_units",
    "revenue",
    "filament_total", "machine_total", "labor_total", "fulfiller_cost",
    "markup", "total_to_fulfiller",
    "net_proceeds", "owner_payment",
]].copy()

for col in ["revenue", "filament_total", "machine_total", "labor_total",
            "fulfiller_cost", "markup", "total_to_fulfiller",
            "net_proceeds", "owner_payment"]:
    display[col] = display[col].apply(lambda x: f"${x:,.2f}")

display.columns = [
    "Order ID", "Date", "SKU", "Short Name", "Owner",
    "Units",
    "Revenue",
    "Filament", "Machine", "Labor", "Fulfiller Cost",
    "Markup (40%)", "Total to Fulfiller",
    "Net Proceeds", "Owner Payment",
]

st.dataframe(display, use_container_width=True, hide_index=True)

conn.close()
