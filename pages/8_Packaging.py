import streamlit as st
import pandas as pd
from db import get_connection

st.set_page_config(page_title="Packaging", page_icon="📦", layout="wide")
st.title("Packaging")

try:
    conn = get_connection()
except Exception as e:
    st.error(f"Database connection failed: {e}")
    st.stop()

with conn.cursor() as cur:
    cur.execute("""
        SELECT packaging_type_id, packaging_name,
               packaging_cost, bag_cost, pack_material_cost, ship_label_cost, sticker_cost
        FROM packaging
        ORDER BY packaging_name
    """)
    cols = [desc[0] for desc in cur.description]
    rows = cur.fetchall()

df = pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)

# ── All Packaging ──────────────────────────────────────────────────────────────

st.subheader("All Packaging Types")
if not df.empty:
    display = df.copy()
    cost_cols = ["packaging_cost", "bag_cost", "pack_material_cost", "ship_label_cost", "sticker_cost"]
    display["total_cost"] = display[cost_cols].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1)
    for col in cost_cols + ["total_cost"]:
        display[col] = display[col].apply(lambda x: f"${float(x):.2f}" if pd.notna(x) and x != 0 else ("$0.00" if x == 0 else "—"))
    st.dataframe(
        display.drop(columns=["packaging_type_id"]),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No packaging types yet.")

st.divider()

# ── Add Packaging ──────────────────────────────────────────────────────────────

st.subheader("Add Packaging Type")
with st.form("add_packaging"):
    new_name = st.text_input("Packaging Name")
    col3, col4, col5, col6, col7 = st.columns(5)
    with col3:
        new_packaging_cost = st.number_input("Packaging Cost ($)", min_value=0.0, step=0.01, format="%.2f")
    with col4:
        new_bag_cost = st.number_input("Bag Cost ($)", min_value=0.0, step=0.01, format="%.2f")
    with col5:
        new_pack_material_cost = st.number_input("Pack Material Cost ($)", min_value=0.0, step=0.01, format="%.2f")
    with col6:
        new_ship_label_cost = st.number_input("Ship Label Cost ($)", min_value=0.0, step=0.01, format="%.2f")
    with col7:
        new_sticker_cost = st.number_input("Sticker Cost ($)", min_value=0.0, step=0.01, format="%.2f")
    submitted = st.form_submit_button("Add Packaging Type", type="primary")

if submitted:
    if not new_name:
        st.error("Packaging name is required.")
    else:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO packaging
                        (packaging_name, packaging_cost, bag_cost,
                         pack_material_cost, ship_label_cost, sticker_cost)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        new_name,
                        new_packaging_cost or None,
                        new_bag_cost or None,
                        new_pack_material_cost or None,
                        new_ship_label_cost or None,
                        new_sticker_cost or None,
                    ),
                )
            conn.commit()
            st.success(f"Added '{new_name}'.")
            st.rerun()
        except Exception as e:
            conn.rollback()
            st.error(f"Failed: {e}")

st.divider()

# ── Edit Packaging ─────────────────────────────────────────────────────────────

if not df.empty:
    st.subheader("Edit Packaging Type")
    selected_id = st.selectbox(
        "Select packaging type to edit",
        options=df["packaging_type_id"].tolist(),
        format_func=lambda pid: df.loc[df["packaging_type_id"] == pid, "packaging_name"].iloc[0] or "(no name)",
    )
    pkg = df[df["packaging_type_id"] == selected_id].iloc[0]

    with st.form("edit_packaging"):
        edit_name = st.text_input("Packaging Name", value=pkg["packaging_name"] or "")
        col3, col4, col5, col6, col7 = st.columns(5)
        with col3:
            edit_packaging_cost = st.number_input(
                "Packaging Cost ($)", min_value=0.0, step=0.01, format="%.2f",
                value=float(pkg["packaging_cost"] or 0),
            )
        with col4:
            edit_bag_cost = st.number_input(
                "Bag Cost ($)", min_value=0.0, step=0.01, format="%.2f",
                value=float(pkg["bag_cost"] or 0),
            )
        with col5:
            edit_pack_material_cost = st.number_input(
                "Pack Material Cost ($)", min_value=0.0, step=0.01, format="%.2f",
                value=float(pkg["pack_material_cost"] or 0),
            )
        with col6:
            edit_ship_label_cost = st.number_input(
                "Ship Label Cost ($)", min_value=0.0, step=0.01, format="%.2f",
                value=float(pkg["ship_label_cost"] or 0),
            )
        with col7:
            edit_sticker_cost = st.number_input(
                "Sticker Cost ($)", min_value=0.0, step=0.01, format="%.2f",
                value=float(pkg["sticker_cost"] or 0),
            )
        col_save, col_del = st.columns(2)
        with col_save:
            save = st.form_submit_button("Save Changes", type="primary")
        with col_del:
            delete = st.form_submit_button("Delete Packaging Type")

    if save:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE packaging SET
                        packaging_name     = %s,
                        packaging_cost     = %s,
                        bag_cost           = %s,
                        pack_material_cost = %s,
                        ship_label_cost    = %s,
                        sticker_cost       = %s
                    WHERE packaging_type_id = %s
                    """,
                    (
                        edit_name or None,
                        edit_packaging_cost or None,
                        edit_bag_cost or None,
                        edit_pack_material_cost or None,
                        edit_ship_label_cost or None,
                        edit_sticker_cost or None,
                        selected_id,
                    ),
                )
            conn.commit()
            st.success("Packaging type updated.")
            st.rerun()
        except Exception as e:
            conn.rollback()
            st.error(f"Failed: {e}")

    if delete:
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM packaging WHERE packaging_type_id = %s", (selected_id,))
            conn.commit()
            st.success("Packaging type deleted.")
            st.rerun()
        except Exception as e:
            conn.rollback()
            st.error(f"Failed: {e}")

conn.close()
