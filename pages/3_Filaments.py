import streamlit as st
import pandas as pd
from db import get_connection

st.set_page_config(page_title="Filaments", page_icon="🧵", layout="wide")
st.title("Filaments")

try:
    conn = get_connection()
except Exception as e:
    st.error(f"Database connection failed: {e}")
    st.stop()

with conn.cursor() as cur:
    cur.execute("""
        SELECT filament_id, filament_name, filament_vendor, cost_per_gram
        FROM filaments
        ORDER BY filament_name
    """)
    cols = [desc[0] for desc in cur.description]
    rows = cur.fetchall()

df = pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)

# ── All filaments ─────────────────────────────────────────────────────────────

st.subheader("All Filaments")
if not df.empty:
    display = df.copy()
    display["cost_per_gram"] = display["cost_per_gram"].apply(
        lambda x: f"${float(x):.4f}" if x is not None else "—"
    )
    st.dataframe(display, use_container_width=True, hide_index=True)
else:
    st.info("No filaments yet.")

st.divider()

# ── Add filament ──────────────────────────────────────────────────────────────

st.subheader("Add Filament")
with st.form("add_filament"):
    col1, col2, col3 = st.columns(3)
    with col1:
        new_name = st.text_input("Filament Name")
    with col2:
        new_vendor = st.text_input("Vendor")
    with col3:
        new_cost = st.number_input("Cost per Gram ($)", min_value=0.0, step=0.0001, format="%.4f")
    submitted = st.form_submit_button("Add Filament", type="primary")

if submitted:
    if not new_name:
        st.error("Filament name is required.")
    else:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO filaments (filament_name, filament_vendor, cost_per_gram) VALUES (%s, %s, %s)",
                    (new_name, new_vendor or None, new_cost or None),
                )
            conn.commit()
            st.success(f"Added '{new_name}'.")
            st.rerun()
        except Exception as e:
            conn.rollback()
            st.error(f"Failed: {e}")

st.divider()

# ── Edit filament ─────────────────────────────────────────────────────────────

if not df.empty:
    st.subheader("Edit Filament")
    selected_id = st.selectbox(
        "Select filament to edit",
        options=df["filament_id"].tolist(),
        format_func=lambda fid: df.loc[df["filament_id"] == fid, "filament_name"].iloc[0],
    )
    filament = df[df["filament_id"] == selected_id].iloc[0]

    with st.form("edit_filament"):
        col1, col2, col3 = st.columns(3)
        with col1:
            edit_name = st.text_input("Filament Name", value=filament["filament_name"] or "")
        with col2:
            edit_vendor = st.text_input("Vendor", value=filament["filament_vendor"] or "")
        with col3:
            edit_cost = st.number_input(
                "Cost per Gram ($)",
                value=float(filament["cost_per_gram"] or 0),
                min_value=0.0,
                step=0.0001,
                format="%.4f",
            )
        col_save, col_del = st.columns(2)
        with col_save:
            save = st.form_submit_button("Save Changes", type="primary")
        with col_del:
            delete = st.form_submit_button("Delete Filament")

    if save:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE filaments SET filament_name=%s, filament_vendor=%s, cost_per_gram=%s WHERE filament_id=%s",
                    (edit_name, edit_vendor or None, edit_cost or None, selected_id),
                )
            conn.commit()
            st.success("Filament updated.")
            st.rerun()
        except Exception as e:
            conn.rollback()
            st.error(f"Failed: {e}")

    if delete:
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM filaments WHERE filament_id = %s", (selected_id,))
            conn.commit()
            st.success("Filament deleted.")
            st.rerun()
        except Exception as e:
            conn.rollback()
            st.error(f"Failed: {e}")

conn.close()
