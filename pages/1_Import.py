import streamlit as st
import pandas as pd
from datetime import datetime
from db import get_connection

st.set_page_config(page_title="Import Orders", page_icon="📥", layout="wide")
st.title("Import Orders")


# ── Parsing helpers ───────────────────────────────────────────────────────────

def parse_numeric(val):
    try:
        s = str(val).strip().replace(",", "")
        return float(s) if s else None
    except (ValueError, TypeError):
        return None


def parse_int(val):
    try:
        s = str(val).strip()
        return int(float(s)) if s else None
    except (ValueError, TypeError):
        return None


def parse_date(val):
    if not val or str(val).strip() in ("", "nan"):
        return None
    s = str(val).strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def clean_str(val):
    s = str(val).strip()
    return s if s and s.lower() != "nan" else None


# ── File type detection ───────────────────────────────────────────────────────

def detect_file_type(df):
    if "Listing ID" in df.columns and "Item Name" in df.columns:
        return "items"
    if "Card Processing Fees" in df.columns and "Order Net" in df.columns:
        return "orders"
    if "Fees & Taxes" in df.columns and "Availability Date" in df.columns:
        return "statement"
    return "unknown"


# ── Import: EtsySoldOrderItems ────────────────────────────────────────────────

def get_existing_etsy_order_ids(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT etsy_order_id FROM orders WHERE etsy_order_id IS NOT NULL")
        return {row[0] for row in cur.fetchall()}


def import_order_items(conn, df):
    existing_ids = get_existing_etsy_order_ids(conn)

    new_orders = 0
    skipped_orders = 0
    new_line_items = 0
    updated_names = 0
    errors = []

    with conn.cursor() as cur:
        for etsy_order_id, group in df.groupby("Order ID"):
            etsy_order_id = parse_int(etsy_order_id)
            if etsy_order_id is None:
                continue

            if etsy_order_id in existing_ids:
                # Order exists — update listing_name and variation on its line items
                try:
                    for _, row in group.iterrows():
                        listing_id = parse_int(row["Listing ID"])
                        listing_name = clean_str(row["Item Name"])
                        variation = clean_str(row.get("Variations", ""))
                        cur.execute(
                            """
                            UPDATE order_line_item
                            SET listing_name = %s, variation = %s
                            WHERE order_id = (
                                SELECT order_id FROM orders WHERE etsy_order_id = %s
                            ) AND listing_id = %s
                            """,
                            (listing_name, variation, etsy_order_id, listing_id),
                        )
                        updated_names += cur.rowcount
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    errors.append(f"Order {etsy_order_id} (name update): {e}")
                skipped_orders += 1
                continue

            first = group.iloc[0]
            sale_date = parse_date(first["Sale Date"])
            date_shipped = parse_date(first["Date Shipped"])
            buyer_paid_shipping = parse_numeric(first["Order Shipping"])
            coupon_amount = parse_numeric(first["Discount Amount"])
            coupon_name = clean_str(first["Coupon Code"])
            transaction_id = parse_int(first["Transaction ID"])
            order_total = sum(
                parse_numeric(r["Item Total"]) or 0.0 for _, r in group.iterrows()
            )

            try:
                cur.execute(
                    """
                    INSERT INTO orders (
                        etsy_order_id, sale_date, order_total, buyer_paid_shipping,
                        date_shipped, transaction_id, coupon_amount, coupon_name
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING order_id
                    """,
                    (
                        etsy_order_id, sale_date, order_total, buyer_paid_shipping,
                        date_shipped, transaction_id, coupon_amount, coupon_name,
                    ),
                )
                db_order_id = cur.fetchone()[0]
                new_orders += 1

                for _, row in group.iterrows():
                    cur.execute(
                        """
                        INSERT INTO order_line_item (listing_id, price, order_id, qty, listing_name, variation)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            parse_int(row["Listing ID"]),
                            parse_numeric(row["Price"]),
                            db_order_id,
                            parse_int(row["Quantity"]) or 1,
                            clean_str(row["Item Name"]),
                            clean_str(row.get("Variations", "")),
                        ),
                    )
                    new_line_items += 1

                conn.commit()

            except Exception as e:
                conn.rollback()
                errors.append(f"Order {etsy_order_id}: {e}")

    return new_orders, skipped_orders, new_line_items, updated_names, errors


# ── Import: EtsySoldOrders ────────────────────────────────────────────────────

def import_sold_orders(conn, df):
    updated = 0
    skipped = 0
    errors = []

    with conn.cursor() as cur:
        for _, row in df.iterrows():
            etsy_order_id = parse_int(row["Order ID"])
            if etsy_order_id is None:
                continue

            processing_fee = parse_numeric(row["Card Processing Fees"])
            order_total = parse_numeric(row["Order Total"])
            date_shipped = parse_date(row["Date Shipped"])

            try:
                cur.execute(
                    """
                    UPDATE orders SET
                        processing_fee = COALESCE(%s, processing_fee),
                        order_total    = COALESCE(%s, order_total),
                        date_shipped   = COALESCE(date_shipped, %s)
                    WHERE etsy_order_id = %s
                    RETURNING order_id
                    """,
                    (processing_fee, order_total, date_shipped, etsy_order_id),
                )
                if cur.rowcount:
                    updated += 1
                    conn.commit()
                else:
                    skipped += 1

            except Exception as e:
                conn.rollback()
                errors.append(f"Order {etsy_order_id}: {e}")

    return updated, skipped, errors


# ── Import: etsy_statement ────────────────────────────────────────────────────

def parse_fee(val):
    """Parse values like '-$1.66' or '--' into a float."""
    s = str(val).strip().replace("$", "").replace(",", "")
    if s in ("--", "", "nan"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def import_statement(conn, df):
    updated = 0
    skipped = 0
    errors = []

    order_rows = df[df["Info"].str.startswith("Order #")].copy()
    order_rows["etsy_order_id"] = order_rows["Info"].str.extract(r"Order #(\d+)")[0].apply(parse_int)
    order_rows["amount"] = order_rows["Fees & Taxes"].apply(parse_fee)

    # Transaction fees: Type=Fee, Title starts with "Transaction fee:"
    txn_fees = (
        order_rows[
            (order_rows["Type"] == "Fee") &
            (order_rows["Title"].str.startswith("Transaction fee:"))
        ]
        .groupby("etsy_order_id")["amount"]
        .sum()
        .abs()
    )

    # Taxes: all Type=Tax rows
    taxes = (
        order_rows[order_rows["Type"] == "Tax"]
        .groupby("etsy_order_id")["amount"]
        .sum()
        .abs()
    )

    # Credits: Share & Save refunds (positive amounts)
    credits = (
        order_rows[
            (order_rows["Type"] == "Fee") &
            (order_rows["Title"].str.contains("Share & Save", case=False))
        ]
        .groupby("etsy_order_id")["amount"]
        .sum()
        .abs()
    )

    all_order_ids = set(txn_fees.index) | set(taxes.index) | set(credits.index)

    with conn.cursor() as cur:
        for etsy_order_id in all_order_ids:
            if etsy_order_id is None:
                continue
            try:
                cur.execute(
                    """
                    UPDATE orders SET
                        transaction_fee = %s,
                        taxes           = %s,
                        credits         = %s
                    WHERE etsy_order_id = %s
                    RETURNING order_id
                    """,
                    (
                        float(round(txn_fees.get(etsy_order_id, 0), 2)),
                        float(round(taxes.get(etsy_order_id, 0), 2)),
                        float(round(credits.get(etsy_order_id, 0), 2)),
                        etsy_order_id,
                    ),
                )
                if cur.rowcount:
                    updated += 1
                    conn.commit()
                else:
                    skipped += 1
            except Exception as e:
                conn.rollback()
                errors.append(f"Order {etsy_order_id}: {e}")

    return updated, skipped, errors



# ── UI ────────────────────────────────────────────────────────────────────────

try:
    conn = get_connection()
except Exception as e:
    st.error(f"Database connection failed: {e}")
    st.stop()

st.info(
    "Upload any Etsy export file — the type is detected automatically:\n"
    "- **EtsySoldOrderItems** — creates new orders and line items\n"
    "- **EtsySoldOrders** — fills in processing fees, order totals, and ship dates\n"
    "- **etsy_statement** — fills in transaction fees (item + shipping fees combined)"
)

uploaded_file = st.file_uploader("Upload Etsy CSV export", type="csv")

if uploaded_file:
    try:
        df = pd.read_csv(uploaded_file, dtype=str).fillna("")
    except Exception as e:
        st.error(f"Could not read CSV: {e}")
        st.stop()

    file_type = detect_file_type(df)

    if file_type == "unknown":
        st.error("Unrecognized file format. Please upload an EtsySoldOrderItems or EtsySoldOrders CSV.")
        st.stop()

    if file_type == "items":
        st.success("Detected: **EtsySoldOrderItems** — will create orders and line items")
        unique_orders = df["Order ID"].nunique()
        st.write(f"**{len(df)}** rows · **{unique_orders}** unique orders")
        st.dataframe(df.head(10), use_container_width=True)

        if st.button("Import Orders", type="primary"):
            with st.spinner("Importing..."):
                new_orders, skipped, new_items, updated_names, errors = import_order_items(conn, df)
            if errors:
                st.warning(f"{len(errors)} order(s) failed:")
                for err in errors:
                    st.text(err)
            st.success(
                f"Done — **{new_orders}** order(s) added · "
                f"**{new_items}** line item(s) added · "
                f"**{updated_names}** listing name(s) updated · "
                f"**{skipped}** order(s) already existed"
            )

    elif file_type == "orders":
        st.success("Detected: **EtsySoldOrders** — will update processing fees, net revenue, and ship dates")
        st.write(f"**{len(df)}** orders")
        st.dataframe(df[["Order ID", "Date Shipped", "Card Processing Fees", "Order Total"]].head(10), use_container_width=True)

        if st.button("Update Orders", type="primary"):
            with st.spinner("Updating..."):
                updated, skipped, errors = import_sold_orders(conn, df)
            if errors:
                st.warning(f"{len(errors)} order(s) failed:")
                for err in errors:
                    st.text(err)
            st.success(
                f"Done — **{updated}** order(s) updated · "
                f"**{skipped}** skipped (not found in database)"
            )

    elif file_type == "statement":
        st.success("Detected: **etsy_statement** — will update transaction fees per order")
        fee_rows = df[
            (df["Type"] == "Fee") &
            (df["Title"].str.startswith("Transaction fee:")) &
            (df["Info"].str.startswith("Order #"))
        ]
        st.write(f"**{fee_rows['Info'].nunique()}** orders with transaction fees found")
        st.dataframe(
            fee_rows[["Date", "Title", "Info", "Fees & Taxes"]].head(10),
            use_container_width=True,
        )

        if st.button("Update Transaction Fees", type="primary"):
            with st.spinner("Updating..."):
                updated, skipped, errors = import_statement(conn, df)
            if errors:
                st.warning(f"{len(errors)} order(s) failed:")
                for err in errors:
                    st.text(err)
            st.success(
                f"Done — **{updated}** order(s) updated · "
                f"**{skipped}** skipped (not found in database)"
            )

conn.close()
