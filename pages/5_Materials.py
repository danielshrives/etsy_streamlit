import streamlit as st
import pandas as pd
from db import get_connection

st.set_page_config(page_title="Materials", page_icon="🧱", layout="wide")
st.title("Materials")

try:
    conn = get_connection()
except Exception as e:
    st.error(f"Database connection failed: {e}")
    st.stop()

# Load products for dropdown
with conn.cursor() as cur:
    cur.execute('SELECT product_id, "SKU" FROM products ORDER BY "SKU"')
    product_rows = cur.fetchall()
product_options = {row[0]: row[1] for row in product_rows}
product_keys = [None] + list(product_options.keys())

# Load all materials
with conn.cursor() as cur:
    cur.execute("""
        SELECT m.material_id, m.name, m.cost_per_unit, m.qty, p."SKU" AS product
        FROM materials m
        LEFT JOIN products p ON p.product_id = m.part_id
        ORDER BY m.name
    """)
    cols = [desc[0] for desc in cur.description]
    rows = cur.fetchall()

df = pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)

# ── All materials ─────────────────────────────────────────────────────────────

st.subheader("All Materials")
if not df.empty:
    display = df[["name", "product", "cost_per_unit", "qty"]].copy()
    display["cost_per_unit"] = display["cost_per_unit"].apply(
        lambda x: f"${float(x):.2f}" if x is not None else "—"
    )
    st.dataframe(display, use_container_width=True, hide_index=True)
else:
    st.info("No materials yet.")

st.divider()

# ── Add material ──────────────────────────────────────────────────────────────

st.subheader("Add Material")
with st.form("add_material"):
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        new_name = st.text_input("Name")
    with col2:
        new_product_id = st.selectbox(
            "Product",
            options=product_keys,
            format_func=lambda pid: "— none —" if pid is None else product_options[pid],
        )
    with col3:
        new_cost = st.number_input("Cost per Unit ($)", min_value=0.0, step=0.01, format="%.2f")
    with col4:
        new_qty = st.number_input("Qty", min_value=0, step=1)
    submitted = st.form_submit_button("Add Material", type="primary")

if submitted:
    if not new_name:
        st.error("Name is required.")
    else:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO materials (name, part_id, cost_per_unit, qty) VALUES (%s, %s, %s, %s)",
                    (new_name, new_product_id, new_cost or None, new_qty or None),
                )
            conn.commit()
            st.success(f"Added '{new_name}'.")
            st.rerun()
        except Exception as e:
            conn.rollback()
            st.error(f"Failed: {e}")

st.divider()

# ── Edit material ─────────────────────────────────────────────────────────────

if not df.empty:
    st.subheader("Edit Material")
    selected_id = st.selectbox(
        "Select material to edit",
        options=df["material_id"].tolist(),
        format_func=lambda mid: df.loc[df["material_id"] == mid, "name"].iloc[0],
    )
    material = df[df["material_id"] == selected_id].iloc[0]

    # Resolve current product index
    current_product_id = None
    for pid, sku in product_options.items():
        if sku == material["product"]:
            current_product_id = pid
            break
    current_product_idx = (
        product_keys.index(current_product_id)
        if current_product_id in product_keys
        else 0
    )

    with st.form("edit_material"):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            edit_name = st.text_input("Name", value=material["name"] or "")
        with col2:
            edit_product_id = st.selectbox(
                "Product",
                options=product_keys,
                format_func=lambda pid: "— none —" if pid is None else product_options[pid],
                index=current_product_idx,
            )
        with col3:
            edit_cost = st.number_input(
                "Cost per Unit ($)",
                value=float(material["cost_per_unit"] or 0),
                min_value=0.0,
                step=0.01,
                format="%.2f",
            )
        with col4:
            edit_qty = st.number_input(
                "Qty", min_value=0, step=1, value=int(material["qty"] or 0)
            )
        col_save, col_del = st.columns(2)
        with col_save:
            save = st.form_submit_button("Save Changes", type="primary")
        with col_del:
            delete = st.form_submit_button("Delete Material")

    if save:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE materials SET name=%s, part_id=%s, cost_per_unit=%s, qty=%s WHERE material_id=%s",
                    (edit_name, edit_product_id, edit_cost or None, edit_qty or None, selected_id),
                )
            conn.commit()
            st.success("Material updated.")
            st.rerun()
        except Exception as e:
            conn.rollback()
            st.error(f"Failed: {e}")

    if delete:
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM materials WHERE material_id = %s", (selected_id,))
            conn.commit()
            st.success("Material deleted.")
            st.rerun()
        except Exception as e:
            conn.rollback()
            st.error(f"Failed: {e}")

conn.close()
