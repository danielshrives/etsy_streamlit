import streamlit as st
import pandas as pd
from db import get_connection

st.set_page_config(page_title="Products", page_icon="📦", layout="wide")
st.title("Products")

try:
    conn = get_connection()
except Exception as e:
    st.error(f"Database connection failed: {e}")
    st.stop()

# Load people for owner dropdown
with conn.cursor() as cur:
    cur.execute("SELECT person_id, person_name FROM people ORDER BY person_name")
    person_rows = cur.fetchall()
person_options = {row[0]: row[1] for row in person_rows}
person_keys = [None] + list(person_options.keys())

# Load filaments for dropdowns
with conn.cursor() as cur:
    cur.execute("SELECT filament_id, filament_name FROM filaments ORDER BY filament_name")
    filament_rows = cur.fetchall()
filament_options = {row[0]: row[1] for row in filament_rows}
filament_keys = [None] + list(filament_options.keys())

# Load materials for dropdowns
with conn.cursor() as cur:
    cur.execute("SELECT material_id, name FROM materials ORDER BY name")
    material_rows = cur.fetchall()
material_options = {row[0]: row[1] for row in material_rows}
material_keys = [None] + list(material_options.keys())

# Load products (with material name and aggregated cost components)
with conn.cursor() as cur:
    cur.execute("""
        SELECT p.product_id, p."SKU", p.labor_minutes, p.material_id, p.owner_id, m.name AS material_name,
               COALESCE(SUM(pt.grams_material * f.cost_per_gram), 0) AS filament_cost,
               COALESCE(SUM(pt.machine_minutes), 0) * 0.007 AS machine_cost,
               COALESCE(m.cost_per_unit * m.qty, 0) AS material_cost
        FROM products p
        LEFT JOIN materials m ON m.material_id = p.material_id
        LEFT JOIN parts pt ON pt.product_id = p.product_id
        LEFT JOIN filaments f ON f.filament_id = pt.filament_id
        GROUP BY p.product_id, p."SKU", p.labor_minutes, p.material_id, p.owner_id, m.name, m.cost_per_unit, m.qty
        ORDER BY p."SKU"
    """)
    prod_cols = [desc[0] for desc in cur.description]
    prod_rows = cur.fetchall()

prod_df = pd.DataFrame(prod_rows, columns=prod_cols) if prod_rows else pd.DataFrame(columns=prod_cols)
sku_col = prod_cols[1] if len(prod_cols) > 1 else "SKU"

# Load average sale price and net revenue per SKU via listing_link
# Order-level fees are split evenly across line items in that order
with conn.cursor() as cur:
    cur.execute("""
        SELECT ll."SKU",
               AVG(oli.price / NULLIF(total_ll.total_qty, 0)) AS avg_revenue,
               SUM(COALESCE(oli.qty, 1) * ll.qty) AS units_sold,
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
        JOIN order_line_item oli ON oli.listing_id = ll.etsy_listing_id
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
        ) total_ll ON total_ll.etsy_listing_id = ll.etsy_listing_id
            AND total_ll.variation IS NOT DISTINCT FROM ll.variation
        WHERE oli.price IS NOT NULL
        GROUP BY ll."SKU"
    """)
    rev_rows = cur.fetchall()
rev_df = pd.DataFrame(rev_rows, columns=["SKU", "avg_revenue", "units_sold", "avg_net_revenue"]) if rev_rows else pd.DataFrame(columns=["SKU", "avg_revenue", "units_sold", "avg_net_revenue"])

if not prod_df.empty and not rev_df.empty:
    prod_df = prod_df.merge(rev_df, left_on=sku_col, right_on="SKU", how="left")

tab_all, tab_add, tab_edit = st.tabs(["All Products", "Add Product", "Edit Product"])

# ── Tab: All Products ─────────────────────────────────────────────────────────

with tab_all:
    if not prod_df.empty:
        LABOR_RATE = 20.0 / 60.0
        display = prod_df[[sku_col, "labor_minutes", "filament_cost", "machine_cost", "material_cost"]].copy()
        display["total_cost"] = (
            display["filament_cost"].astype(float)
            + display["machine_cost"].astype(float)
            + display["material_cost"].astype(float)
            + display["labor_minutes"].fillna(0).astype(float) * LABOR_RATE
        )
        has_rev = "avg_revenue" in prod_df.columns
        if has_rev:
            display["avg_revenue"] = prod_df["avg_revenue"]
            display["avg_net_revenue"] = prod_df["avg_net_revenue"]
            display["units_sold"] = prod_df["units_sold"].fillna(0).astype(int)
            display["net_margin"] = display["avg_net_revenue"].astype(float) - display["total_cost"]

        cols = [sku_col, "total_cost"]
        if has_rev:
            cols += ["avg_revenue", "avg_net_revenue", "net_margin", "units_sold"]
        display = display[cols]

        display["total_cost"] = display["total_cost"].apply(lambda x: f"${x:.2f}")
        if has_rev:
            for col in ["avg_revenue", "avg_net_revenue", "net_margin"]:
                display[col] = display[col].apply(lambda x: f"${float(x):.2f}" if pd.notna(x) else "—")
        st.dataframe(display, use_container_width=True, hide_index=True)
    else:
        st.info("No products yet.")

# ── Tab: Add Product ──────────────────────────────────────────────────────────

with tab_add:
    with st.form("add_product"):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            new_sku = st.text_input("SKU")
        with col2:
            new_labor = st.number_input("Labor Minutes", min_value=0, step=1)
        with col3:
            new_material_id = st.selectbox(
                "Material",
                options=material_keys,
                format_func=lambda mid: "— none —" if mid is None else material_options[mid],
            )
        with col4:
            new_owner_id = st.selectbox(
                "Owner",
                options=person_keys,
                format_func=lambda pid: "— none —" if pid is None else person_options[pid],
            )
        submitted = st.form_submit_button("Add Product", type="primary")

    if submitted:
        if not new_sku:
            st.error("SKU is required.")
        else:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        'INSERT INTO products ("SKU", labor_minutes, material_id, owner_id) VALUES (%s, %s, %s, %s)',
                        (new_sku, new_labor or None, new_material_id, new_owner_id),
                    )
                conn.commit()
                st.success(f"Added product '{new_sku}'.")
                st.rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"Failed: {e}")

# ── Tab: Edit Product ─────────────────────────────────────────────────────────

with tab_edit:
    if prod_df.empty:
        st.info("No products yet.")
    else:
        selected_pid = st.selectbox(
            "Select product",
            options=prod_df["product_id"].tolist(),
            format_func=lambda pid: prod_df.loc[prod_df["product_id"] == pid, sku_col].iloc[0],
        )
        product = prod_df[prod_df["product_id"] == selected_pid].iloc[0]

        # ── Product fields ────────────────────────────────────────────────────

        current_material_idx = (
            material_keys.index(product["material_id"])
            if product["material_id"] in material_keys
            else 0
        )
        current_owner_idx = (
            person_keys.index(product["owner_id"])
            if pd.notna(product.get("owner_id")) and product["owner_id"] in person_keys
            else 0
        )
        with st.form("edit_product"):
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                edit_sku = st.text_input("SKU", value=product[sku_col] or "")
            with col2:
                edit_labor = st.number_input(
                    "Labor Minutes", min_value=0, step=1, value=int(product["labor_minutes"]) if pd.notna(product["labor_minutes"]) else 0
                )
            with col3:
                edit_material_id = st.selectbox(
                    "Material",
                    options=material_keys,
                    format_func=lambda mid: "— none —" if mid is None else material_options[mid],
                    index=current_material_idx,
                )
            with col4:
                edit_owner_id = st.selectbox(
                    "Owner",
                    options=person_keys,
                    format_func=lambda pid: "— none —" if pid is None else person_options[pid],
                    index=current_owner_idx,
                )
            col_save, col_copy, col_del = st.columns(3)
            with col_save:
                save_product = st.form_submit_button("Save Changes", type="primary")
            with col_copy:
                copy_product = st.form_submit_button("Copy Product")
            with col_del:
                delete_product = st.form_submit_button("Delete Product")

        if copy_product:
            new_copy_sku = product[sku_col] + "-copy"
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        'INSERT INTO products ("SKU", labor_minutes, material_id, owner_id) VALUES (%s, %s, %s, %s) RETURNING product_id',
                        (
                            new_copy_sku,
                            int(product["labor_minutes"]) if pd.notna(product["labor_minutes"]) else None,
                            int(product["material_id"]) if pd.notna(product["material_id"]) else None,
                            int(product["owner_id"]) if pd.notna(product.get("owner_id")) else None,
                        ),
                    )
                    new_pid = cur.fetchone()[0]
                    # Load and copy all parts for this product
                    cur.execute(
                        "SELECT part_name, grams_material, filament_id, machine_minutes FROM parts WHERE product_id = %s",
                        (selected_pid,),
                    )
                    for p in cur.fetchall():
                        cur.execute(
                            """
                            INSERT INTO parts (part_name, product_id, grams_material, filament_id, machine_minutes)
                            VALUES (%s, %s, %s, %s, %s)
                            """,
                            (
                                p[0] or None,
                                new_pid,
                                float(p[1]) if p[1] is not None else None,
                                int(p[2]) if p[2] is not None else None,
                                int(p[3]) if p[3] is not None else None,
                            ),
                        )
                conn.commit()
                st.success(f"Copied to '{new_copy_sku}' — select it from the dropdown to edit.")
                st.rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"Failed: {e}")

        if save_product:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        'UPDATE products SET "SKU"=%s, labor_minutes=%s, material_id=%s, owner_id=%s WHERE product_id=%s',
                        (edit_sku, edit_labor or None, edit_material_id, edit_owner_id, selected_pid),
                    )
                conn.commit()
                st.success("Product updated.")
                st.rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"Failed: {e}")

        if delete_product:
            try:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM products WHERE product_id = %s", (selected_pid,))
                conn.commit()
                st.success("Product deleted.")
                st.rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"Failed: {e}")

        st.divider()

        # ── Parts ─────────────────────────────────────────────────────────────

        with conn.cursor() as cur:
            cur.execute("""
                SELECT p.part_id, p.part_name, p.grams_material,
                       p.machine_minutes, p.filament_id, f.filament_name, f.cost_per_gram
                FROM parts p
                LEFT JOIN filaments f ON f.filament_id = p.filament_id
                WHERE p.product_id = %s
                ORDER BY p.part_name
            """, (selected_pid,))
            part_cols = [desc[0] for desc in cur.description]
            part_rows = cur.fetchall()

        parts_df = pd.DataFrame(part_rows, columns=part_cols) if part_rows else pd.DataFrame(columns=part_cols)

        st.subheader("Parts")
        if not parts_df.empty:
            display = parts_df[["part_name", "grams_material", "machine_minutes", "filament_name"]].copy()
            st.dataframe(display, use_container_width=True, hide_index=True)
        else:
            st.info("No parts for this product yet.")

        # ── Cost breakdown ────────────────────────────────────────────────────

        st.markdown("#### Cost to Produce")

        LABOR_RATE = 20.0 / 60.0
        MACHINE_RATE = 0.007

        filament_cost = 0.0
        if not parts_df.empty:
            for _, p in parts_df.iterrows():
                filament_cost += float(p["grams_material"] or 0) * float(p["cost_per_gram"] or 0)

        machine_cost = 0.0
        if not parts_df.empty:
            machine_cost = float(parts_df["machine_minutes"].fillna(0).astype(float).sum()) * MACHINE_RATE

        labor_cost = float(product["labor_minutes"] or 0) * LABOR_RATE

        material_cost = 0.0
        if pd.notna(product["material_id"]):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT cost_per_unit, qty FROM materials WHERE material_id = %s",
                    (int(product["material_id"]),),
                )
                mat = cur.fetchone()
            if mat:
                material_cost = float(mat[0] or 0) * float(mat[1] or 0)

        total_cost = filament_cost + machine_cost + labor_cost + material_cost

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Filament", f"${filament_cost:.2f}")
        c2.metric("Machine", f"${machine_cost:.2f}")
        c3.metric("Labor", f"${labor_cost:.2f}")
        c4.metric("Material", f"${material_cost:.2f}")
        c5.metric("Total", f"${total_cost:.2f}")

        st.divider()

        # ── Add part ──────────────────────────────────────────────────────────

        st.markdown("#### Add Part")
        with st.form("add_part"):
            col1, col2 = st.columns(2)
            with col1:
                new_part_name = st.text_input("Part Name")
                new_grams = st.number_input("Grams of Material", min_value=0.0, step=0.1, format="%.2f")
            with col2:
                new_machine_min = st.number_input("Machine Minutes", min_value=0, step=1)
                new_filament_id = st.selectbox(
                    "Filament",
                    options=filament_keys,
                    format_func=lambda fid: "— none —" if fid is None else filament_options[fid],
                )
            add_part = st.form_submit_button("Add Part", type="primary")

        if add_part:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO parts (part_name, product_id, grams_material, filament_id, machine_minutes)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            new_part_name or None,
                            selected_pid,
                            new_grams or None,
                            new_filament_id,
                            new_machine_min or None,
                        ),
                    )
                conn.commit()
                st.success("Part added.")
                st.rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"Failed: {e}")

        # ── Edit part ─────────────────────────────────────────────────────────

        if not parts_df.empty:
            st.markdown("#### Edit Part")
            selected_part_id = st.selectbox(
                "Select part to edit",
                options=parts_df["part_id"].tolist(),
                format_func=lambda pid: parts_df.loc[parts_df["part_id"] == pid, "part_name"].iloc[0],
            )
            part = parts_df[parts_df["part_id"] == selected_part_id].iloc[0]

            current_filament_idx = (
                filament_keys.index(part["filament_id"])
                if part["filament_id"] in filament_keys
                else 0
            )

            with st.form("edit_part"):
                col1, col2 = st.columns(2)
                with col1:
                    edit_part_name = st.text_input("Part Name", value=part["part_name"] or "")
                    edit_grams = st.number_input(
                        "Grams of Material", min_value=0.0, step=0.1, format="%.2f", value=float(part["grams_material"]) if pd.notna(part["grams_material"]) else 0.0
                    )
                with col2:
                    edit_machine_min = st.number_input(
                        "Machine Minutes", min_value=0, step=1, value=int(part["machine_minutes"]) if pd.notna(part["machine_minutes"]) else 0
                    )
                    edit_filament_id = st.selectbox(
                        "Filament",
                        options=filament_keys,
                        format_func=lambda fid: "— none —" if fid is None else filament_options[fid],
                        index=current_filament_idx,
                    )
                col_save, col_del = st.columns(2)
                with col_save:
                    save_part = st.form_submit_button("Save Changes", type="primary")
                with col_del:
                    delete_part = st.form_submit_button("Delete Part")

            if save_part:
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE parts SET
                                part_name       = %s,
                                grams_material  = %s,
                                machine_minutes = %s,
                                filament_id     = %s
                            WHERE part_id = %s
                            """,
                            (
                                edit_part_name or None,
                                edit_grams or None,
                                edit_machine_min or None,
                                edit_filament_id,
                                selected_part_id,
                            ),
                        )
                    conn.commit()
                    st.success("Part updated.")
                    st.rerun()
                except Exception as e:
                    conn.rollback()
                    st.error(f"Failed: {e}")

            if delete_part:
                try:
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM parts WHERE part_id = %s", (selected_part_id,))
                    conn.commit()
                    st.success("Part deleted.")
                    st.rerun()
                except Exception as e:
                    conn.rollback()
                    st.error(f"Failed: {e}")

conn.close()
