import pandas as pd
import streamlit as st
from db_connection import get_connection


# Helpers
def safe_int(x):
    try:
        return int(float(x))
    except:
        return 0


def safe_float(x):
    try:
        return float(x)
    except:
        return 0.0


def to_date(dt):
    try:
        return pd.Timestamp(dt).strftime("%Y-%m-%d")
    except:
        return str(dt)


def fetch_all(c):
    return [dict(r) for r in c.fetchall() or []]


def get_bid():
    return st.session_state.get("business_id")


# Stock helpers
def cleanup_zero_stock_rows(c, bid, name, cat=None):
    sql = "DELETE FROM inventory WHERE business_id=? AND product_name=? AND stock<=0"
    params = [bid, name]
    if cat:
        sql += " AND category=?"
        params.append(cat)
    c.execute(sql, tuple(params))


def _reduce(c, bid, name, qty, order="ASC", cat=None):
    left = safe_int(qty)

    sql = (
        f"SELECT product_id, stock FROM inventory "
        f"WHERE business_id=? AND product_name=? AND stock>0 "
    )
    params = [bid, name]

    if cat:
        sql += "AND category=? "
        params.append(cat)

    sql += f"ORDER BY added_date {order}, product_id {order}"

    c.execute(sql, tuple(params))

    for r in fetch_all(c):
        if left <= 0:
            break
        use = min(safe_int(r["stock"]), left)
        c.execute("UPDATE inventory SET stock=stock-? WHERE product_id=?", (use, r["product_id"]))
        left -= use

    cleanup_zero_stock_rows(c, bid, name, cat)
    return left


def reduce_fifo(c, bid, name, qty, cat=None):
    return _reduce(c, bid, name, qty, "ASC", cat)


def reduce_rev(c, bid, name, qty, cat=None):
    return _reduce(c, bid, name, qty, "DESC", cat)


def restore(c, bid, name, qty, cat=None, cost=0, sell=0, dt=None):
    qty = safe_int(qty)
    if qty <= 0:
        return

    sql = (
        "SELECT product_id FROM inventory "
        "WHERE business_id=? AND product_name=? "
    )
    params = [bid, name]

    if cat:
        sql += "AND category=? "
        params.append(cat)

    sql += "ORDER BY added_date DESC, product_id DESC LIMIT 1"

    c.execute(sql, tuple(params))
    r = c.fetchone()

    if r:
        c.execute("UPDATE inventory SET stock=stock+? WHERE product_id=?", (qty, dict(r)["product_id"]))
    else:
        c.execute(
            "INSERT INTO inventory(business_id,category,product_name,stock,cost_price,selling_price,added_date) "
            "VALUES(?,?,?,?,?,?,?)",
            (bid, cat or "", name, qty, safe_float(cost), safe_float(sell), to_date(dt or pd.Timestamp.today())),
        )


def reverse(c, bid, row):
    row = row.to_dict() if isinstance(row, pd.Series) else row
    txn_type = str(row.get("type", ""))
    name = str(row.get("product", row.get("category", ""))).strip()
    cat = str(row.get("category", "")).strip()
    qty = safe_int(row.get("quantity", 0))
    cost = safe_float(row.get("cost_price", 0))
    sell = safe_float(row.get("selling_price", 0))
    dt = row.get("transaction_date")

    if not name:
        return

    if txn_type == "Sale":
        restore(c, bid, name, qty, cat=cat, cost=cost, sell=sell, dt=dt)
    elif txn_type == "Purchase":
        reduce_rev(c, bid, name, qty, cat=cat)
        cleanup_zero_stock_rows(c, bid, name, cat)


def get_stock(c, bid, prod, cat=None):
    sql = "SELECT COALESCE(SUM(stock),0) AS t FROM inventory WHERE business_id=? AND product_name=?"
    params = [bid, prod]

    if cat:
        sql += " AND category=?"
        params.append(cat)

    c.execute(sql, tuple(params))
    r = c.fetchone()
    return safe_int(dict(r).get("t", 0)) if r else 0


def apply_txn_effect(c, bid, txn_type, cat, prod, qty, cost, sell, dt):
    qty = safe_int(qty)

    if txn_type == "Sale":
        avail = get_stock(c, bid, prod, cat)
        if qty > avail:
            raise ValueError(f"Insufficient stock. Available: {avail}, Requested: {qty}")
        reduce_fifo(c, bid, prod, qty, cat)

    elif txn_type == "Purchase":
        upsert_inv(c, bid, cat, prod, qty, cost, sell, dt)

    elif txn_type == "Expense":
        return


# DB helpers
def get_cats(c, bid):
    c.execute("SELECT DISTINCT category FROM inventory WHERE business_id=? ORDER BY category", (bid,))
    return [dict(r)["category"] for r in c.fetchall() or []]


def get_prods(c, bid, cat):
    c.execute(
        "SELECT DISTINCT product_name, cost_price, selling_price "
        "FROM inventory WHERE business_id=? AND category=? ORDER BY product_name",
        (bid, cat),
    )
    return fetch_all(c)


def get_inventory_snapshot(c, bid, cat, prod):
    if not cat or not prod:
        return {"cost_price": 0.0, "selling_price": 0.0, "stock": 0}

    c.execute(
        """
        SELECT cost_price, selling_price
        FROM inventory
        WHERE business_id=? AND category=? AND product_name=?
        ORDER BY added_date DESC, product_id DESC
        LIMIT 1
        """,
        (bid, cat, prod),
    )
    row = c.fetchone()
    stock = get_stock(c, bid, prod, cat)
    data = dict(row) if row else {}
    return {
        "cost_price": safe_float(data.get("cost_price", 0)),
        "selling_price": safe_float(data.get("selling_price", 0)),
        "stock": stock,
    }


def sync_price_fields(prefix, cost, sell, cat=None, prod=None):
    cost_key = f"{prefix}_cost"
    sell_key = f"{prefix}_sell"
    sel_key = f"{prefix}_selection"
    current = (cat or "", prod or "")

    if st.session_state.get(sel_key) != current:
        st.session_state[sel_key] = current
        st.session_state[cost_key] = safe_float(cost)
        st.session_state[sell_key] = safe_float(sell)

    return cost_key, sell_key


def upsert_inv(c, bid, cat, name, qty, cost, sell, dt):
    c.execute(
        "SELECT product_id FROM inventory "
        "WHERE business_id=? AND category=? AND product_name=? "
        "ORDER BY added_date DESC, product_id DESC LIMIT 1",
        (bid, cat, name),
    )
    r = c.fetchone()
    if r:
        c.execute(
            "UPDATE inventory SET stock=stock+?, cost_price=?, selling_price=? WHERE product_id=?",
            (qty, cost, sell, dict(r)["product_id"]),
        )
    else:
        c.execute(
            "INSERT INTO inventory(business_id,category,product_name,stock,cost_price,selling_price,added_date) "
            "VALUES(?,?,?,?,?,?,?)",
            (bid, cat, name, qty, cost, sell, to_date(dt)),
        )


def ins_txn(c, bid, txn_type, cat, cost, sell, prod, dt, qty):
    c.execute(
        "INSERT INTO transactions(business_id,type,category,cost_price,selling_price,product,transaction_date,quantity) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (bid, txn_type, cat, cost, sell, prod, to_date(dt), qty),
    )


def load_transactions(c, bid):
    c.execute("SELECT * FROM transactions WHERE business_id=? ORDER BY transaction_id DESC", (bid,))
    return pd.DataFrame(fetch_all(c))


def delete_txns(c, conn, bid, rows_df, msg):
    try:
        for _, r in rows_df.iterrows():
            reverse(c, bid, r)

        ids = rows_df["transaction_id"].tolist()
        if not ids:
            st.warning("No records selected.")
            return

        c.execute(
            f"DELETE FROM transactions WHERE transaction_id IN ({','.join(['?'] * len(ids))}) AND business_id=?",
            (*ids, bid),
        )
        conn.commit()
        st.success(msg)
        st.rerun()
    except Exception as e:
        conn.rollback()
        st.error(f"Error: {e}")


# UI helpers
def profit_preview(cost, sell):
    if cost > 0 and sell > 0:
        margin = sell - cost
        pct = (margin / cost) * 100 if cost else 0
        label = "💰 Profit" if margin > 0 else "📉 Loss" if margin < 0 else "⚖️ Break-even"
        fn = st.success if margin > 0 else st.error if margin < 0 else st.info
        fn(f"{label}/unit: ₹{abs(margin):.2f} ({abs(pct):.1f}%)")


def show_metrics(row):
    cols = st.columns(4)
    data = [
        ("Type", row["type"]),
        ("Qty", safe_int(row["quantity"])),
        ("Cost", f"₹{safe_float(row['cost_price']):.2f}"),
        ("Sell", f"₹{safe_float(row['selling_price']):.2f}"),
    ]
    for col, (k, v) in zip(cols, data):
        col.metric(k, v)


# CSV upload
SAMPLE = pd.DataFrame(
    [
        {"type": "Purchase", "category": "Category A", "product": "Product A", "quantity": 10, "cost_price": 1000, "selling_price": 1500, "transaction_date": "2026-04-06"},
        {"type": "Sale", "category": "Category A", "product": "Product A", "quantity": 2, "cost_price": 1000, "selling_price": 1500, "transaction_date": "2026-04-06"},
        {"type": "Expense", "category": "Expense A", "product": "Expense A", "quantity": 1, "cost_price": 500, "selling_price": 0, "transaction_date": "2026-04-06"},
    ]
)


def csv_upload_section(c, conn, bid):
    with st.expander("📋 CSV Format Guide"):
        st.markdown(
            """
**Required columns**:

| Column | Description | Example |
|---|---|---|
| `type` | Transaction type | `Sale` / `Purchase` / `Expense` |
| `category` | Category name | `Category A` |
| `product` | Product name | `Product A` |
| `quantity` | Units | `5` |
| `cost_price` | Cost per unit | `1000.00` |
| `selling_price` | Sell price | `1500.00` |
| `transaction_date` | `YYYY-MM-DD` | `2026-04-06` |
"""
        )
        st.download_button(
            "⬇️ Download Sample CSV",
            SAMPLE.to_csv(index=False).encode(),
            "transaction_sample.csv",
            "text/csv",
            key=f"dl_{bid}",
        )

    st.divider()

    uploaded = st.file_uploader("📤 Upload CSV File", type=["csv"], key=f"up_{bid}")
    if uploaded is None:
        return

    try:
        raw = pd.read_csv(uploaded)
    except Exception as e:
        st.error(f"❌ Could not read CSV: {e}")
        return

    raw.columns = [col.strip().lower().replace(" ", "_") for col in raw.columns]
    missing = {"type", "category", "product", "quantity", "cost_price", "selling_price"} - set(raw.columns)
    if missing:
        st.error(f"❌ Missing columns: {', '.join(sorted(missing))}")
        return

    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    if "transaction_date" not in raw.columns:
        raw["transaction_date"] = today
    else:
        raw["transaction_date"] = raw["transaction_date"].fillna(today).astype(str).str.strip().replace("", today)

    type_map = {"sale": "Sale", "purchase": "Purchase", "expense": "Expense"}
    raw["type"] = raw["type"].astype(str).str.strip().str.lower().map(type_map)
    bad = raw[raw["type"].isna()]
    if not bad.empty:
        st.error(f"❌ Rows {(bad.index + 2).tolist()} have invalid type.")
        return

    st.markdown("**👀 Preview**")
    st.dataframe(raw, use_container_width=True, hide_index=True)

    if not st.button(" Upload ", type="primary", key=f"proc_{bid}"):
        return

    ok, errs = 0, []
    for idx, row in raw.iterrows():
        txn = row["type"]
        cat = str(row["category"]).strip()
        prod = str(row["product"]).strip()
        qty = safe_int(row["quantity"])
        cost = safe_float(row["cost_price"])
        sell = safe_float(row["selling_price"])
        dt = str(row["transaction_date"]).strip() or today

        try:
            if txn == "Sale":
                avail = get_stock(c, bid, prod, cat)
                if qty > avail:
                    errs.append(f"Row {idx + 2} - {prod}: {avail} available, {qty} requested. Skipped.")
                    continue
                reduce_fifo(c, bid, prod, qty, cat)
                ins_txn(c, bid, "Sale", cat, cost, sell, prod, dt, qty)

            elif txn == "Purchase":
                upsert_inv(c, bid, cat, prod, qty, cost, sell, dt)
                ins_txn(c, bid, "Purchase", cat, cost, sell, prod, dt, qty)

            elif txn == "Expense":
                ins_txn(c, bid, "Expense", cat, cost, 0, prod, dt, qty)

            ok += 1
        except Exception as e:
            errs.append(f"Row {idx + 2} - {prod}: {e}")

    conn.commit()
    st.success(f"✅ {ok} row(s) processed successfully.") if ok else None
    if errs:
        st.warning(f"⚠️ {len(errs)} row(s) skipped.")
        for err in errs:
            st.error(err)
    st.rerun()


def transactions_page():
    st.title("💰 Transaction Management")

    bid = get_bid()
    if not bid:
        st.warning("⚠️ Please select a Business first.")
        return

    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT business_name FROM businesses WHERE business_id=?", (bid,))
    brow = c.fetchone()
    if not brow:
        st.error("❌ Business not found.")
        conn.close()
        return

    st.info(f"🏢 Current Business: **{dict(brow)['business_name']}**")

    st.markdown("#### 📂 Bulk CSV Upload")
    csv_upload_section(c, conn, bid)

    st.divider()

    df = load_transactions(c, bid)

    st.subheader(" Transaction History")
    if df.empty:
        st.info("No transactions available.")
    else:
        col1, col2, col3 = st.columns(3)
        cats = ["All"] + sorted(df["category"].dropna().unique().tolist())
        fp = col1.selectbox(" Filter Category", cats, key=f"vc_{bid}")

        base_df = df if fp == "All" else df[df["category"] == fp]
        prods = ["All"] + sorted(base_df["product"].dropna().unique().tolist())
        fprod = col2.selectbox(" Filter Product", prods, key=f"vp_{bid}")
        ft = col3.selectbox(" Filter Type", ["All"] + list(df["type"].dropna().unique()), key=f"vt_{bid}")

        fdf = df.copy()
        if fp != "All":
            fdf = fdf[fdf["category"] == fp]
        if fprod != "All":
            fdf = fdf[fdf["product"] == fprod]
        if ft != "All":
            fdf = fdf[fdf["type"] == ft]

        if st.checkbox("📅 Filter by Date Range", key=f"vd_{bid}"):
            d1, d2 = st.columns(2)
            fdf["transaction_date"] = pd.to_datetime(fdf["transaction_date"], errors="coerce")
            from_date = d1.date_input("From", key=f"view_from_{bid}")
            to_date_val = d2.date_input("To", key=f"view_to_{bid}")
            fdf = fdf[
                (fdf["transaction_date"].dt.date >= from_date)
                & (fdf["transaction_date"].dt.date <= to_date_val)
            ]

        st.dataframe(fdf, use_container_width=True, hide_index=True)

    st.divider()

    st.subheader("🛠️ Transaction Operations")
    op = st.selectbox(" Operation", ["Select", "Add", "Update", "Delete"], key=f"op_{bid}")

    if op == "Add":
        st.markdown("#### ➕ Add Transaction")
        txn_type = st.selectbox(" Type", ["Sale", "Purchase", "Expense"], key=f"at_{bid}")
        dt = st.date_input(" Date", key=f"adt_{bid}")

        if txn_type == "Expense":
            nm = st.text_input(" Expense Name", key=f"en_{bid}")
            amt = st.number_input(" Amount", min_value=0.0, key=f"ea_{bid}")
            if st.button("➕ Add Expense", key=f"ae_{bid}"):
                ins_txn(c, bid, "Expense", nm, amt, 0, nm, dt, 1)
                conn.commit()
                st.success("✅ Expense added.")
                st.rerun()

        elif txn_type == "Purchase":
            cats_list = get_cats(c, bid)
            cat_options = cats_list + ["➕ New Category"]
            cat_choice = st.selectbox(
                "️ Category",
                cat_options,
                index=None,
                placeholder="Select category",
                key=f"pc_{bid}",
            )

            default_cost = 0.0
            default_sell = 0.0
            avail = 0
            cat = ""
            prod = ""

            if cat_choice == "➕ New Category":
                cat = st.text_input(" New Category", key=f"nc_{bid}")
                prod = st.text_input(" New Product", key=f"np_{bid}")
            elif cat_choice:
                cat = cat_choice
                pdata = get_prods(c, bid, cat)
                pnames = [p["product_name"] for p in pdata] + ["➕ New Product"]
                psel = st.selectbox(
                    " Product",
                    pnames,
                    index=None,
                    placeholder="Select product",
                    key=f"pp_{bid}",
                )

                if psel == "➕ New Product":
                    prod = st.text_input(" New Product Name", key=f"npp_{bid}")
                elif psel:
                    prod = psel
                    snapshot = get_inventory_snapshot(c, bid, cat, prod)
                    default_cost = snapshot["cost_price"]
                    default_sell = snapshot["selling_price"]
                    avail = snapshot["stock"]

            pur_cost_key, pur_sell_key = sync_price_fields(
                f"pur_{bid}",
                default_cost,
                default_sell,
                cat,
                prod,
            )

            c1, c2, c3 = st.columns(3)
            pur_cost = c1.number_input(" Cost Price", min_value=0.0, key=pur_cost_key)
            pur_sell = c2.number_input(" Sell Price", min_value=0.0, key=pur_sell_key)
            pur_qty = c3.number_input(" Quantity", min_value=1, key=f"pur_qty_{bid}")

            if prod:
                c3.caption(f"📦 Available Stock: **{avail}** units")

            profit_preview(pur_cost, pur_sell)

            if st.button("🛒 Add Purchase", type="primary", key=f"ap_{bid}"):
                if not cat or not prod:
                    st.warning("⚠️ Fill Category and Product.")
                else:
                    try:
                        upsert_inv(c, bid, cat, prod, pur_qty, pur_cost, pur_sell, dt)
                        ins_txn(c, bid, "Purchase", cat, pur_cost, pur_sell, prod, dt, pur_qty)
                        conn.commit()
                        st.success("✅ Purchase recorded.")
                        st.rerun()
                    except Exception as e:
                        conn.rollback()
                        st.error(e)

        elif txn_type == "Sale":
            cats_list = get_cats(c, bid)
            if not cats_list:
                st.warning(" No inventory. Add purchases first.")
            else:
                cat = st.selectbox(
                    " Category",
                    cats_list,
                    index=None,
                    placeholder="Select category",
                    key=f"sc_{bid}",
                )
                pdata = get_prods(c, bid, cat) if cat else []
                prod = ""
                default_cost = 0.0
                default_sell = 0.0
                avail = 0

                if cat and not pdata:
                    st.warning("⚠️ No products in this category.")

                if pdata:
                    prod = st.selectbox(
                        " Product",
                        [p["product_name"] for p in pdata],
                        index=None,
                        placeholder="Select product",
                        key=f"sp_{bid}",
                    )
                    if prod:
                        snapshot = get_inventory_snapshot(c, bid, cat, prod)
                        default_cost = snapshot["cost_price"]
                        default_sell = snapshot["selling_price"]
                        avail = snapshot["stock"]

                sal_cost_key, sal_sell_key = sync_price_fields(
                    f"sal_{bid}",
                    default_cost,
                    default_sell,
                    cat,
                    prod,
                )

                c1, c2, c3 = st.columns(3)
                sal_cost = c1.number_input(" Cost Price", min_value=0.0, key=sal_cost_key)
                sal_sell = c2.number_input(" Sell Price", min_value=0.0, key=sal_sell_key)
                sal_qty = c3.number_input(" Quantity", min_value=1, key=f"sal_qty_{bid}")

                if prod:
                    c3.caption(f"📦 Available Stock: **{avail}** units")

                profit_preview(sal_cost, sal_sell)

                if st.button("💰 Add Sale", type="primary", key=f"as_{bid}"):
                    if not cat or not prod:
                        st.warning("⚠️ Select Category and Product.")
                    elif sal_qty > avail:
                        st.error(f"❌ Insufficient stock. Available: {avail}, Requested: {sal_qty}")
                    else:
                        try:
                            reduce_fifo(c, bid, prod, sal_qty, cat)
                            ins_txn(c, bid, "Sale", cat, sal_cost, sal_sell, prod, dt, sal_qty)
                            conn.commit()
                            st.success("✅ Sale recorded.")
                            st.rerun()
                        except Exception as e:
                            conn.rollback()
                            st.error(e)

    elif op == "Update":
        if df.empty:
            st.info("No transactions to update.")
        else:
            st.markdown("#### ✏️ Update Transaction")

            f1, f2, f3 = st.columns(3)
            update_df = df.copy()

            ucat_options = ["All"] + sorted(update_df["category"].dropna().unique().tolist())
            ucat = f1.selectbox("Filter Category", ucat_options, key=f"uc_{bid}")
            if ucat != "All":
                update_df = update_df[update_df["category"] == ucat]

            uprod_options = ["All"] + sorted(update_df["product"].dropna().unique().tolist())
            uprod_filter = f2.selectbox("Filter Product Name", uprod_options, key=f"uprod_filter_{bid}")
            if uprod_filter != "All":
                update_df = update_df[update_df["product"] == uprod_filter]

            tid_options = update_df["transaction_id"].tolist()
            if not tid_options:
                st.info("No matching transactions found.")
            else:
                tid = f3.selectbox("Filter Transaction ID", tid_options, key=f"tid_{bid}")
                row = update_df[update_df["transaction_id"] == tid].iloc[0]
                show_metrics(row)
                st.divider()

                ntype = st.selectbox(
                    "Type",
                    ["Sale", "Purchase", "Expense"],
                    index=["Sale", "Purchase", "Expense"].index(row["type"]),
                    key=f"ntype_{tid}",
                )
                ndt = st.date_input("📅 Date", value=pd.to_datetime(row["transaction_date"]), key=f"ndt_{tid}")

                if ntype == "Expense":
                    ncat = st.text_input("Expense Category", value=str(row["category"]), key=f"ncat_exp_{tid}")
                    nprod = st.text_input("Expense Name", value=str(row["product"]), key=f"nprod_exp_{tid}")
                    c1, c2, c3 = st.columns(3)
                    ncost = c1.number_input("Amount", min_value=0.0, value=safe_float(row["cost_price"]), key=f"nc_exp_{tid}")
                    c2.number_input("Sell", min_value=0.0, value=0.0, key=f"ns_exp_{tid}", disabled=True)
                    newqty = c3.number_input("Quantity", min_value=1, value=safe_int(row["quantity"]), key=f"nq_exp_{tid}")

                    if st.button("Update Transaction", type="primary", key=f"upd_exp_{tid}"):
                        try:
                            reverse(c, bid, row)
                            c.execute(
                                "UPDATE transactions SET type=?,category=?,product=?,transaction_date=?,quantity=?,cost_price=?,selling_price=? "
                                "WHERE transaction_id=? AND business_id=?",
                                (ntype, ncat, nprod, to_date(ndt), newqty, ncost, 0, tid, bid),
                            )
                            conn.commit()
                            st.success("✅ Transaction updated.")
                            st.rerun()
                        except Exception as e:
                            conn.rollback()
                            st.error(e)

                elif ntype == "Purchase":
                    cats_list = get_cats(c, bid)
                    cat_options = list(dict.fromkeys(([str(row["category"])] if row["category"] else []) + cats_list + ["➕ New Category"]))
                    cat_index = cat_options.index(str(row["category"])) if str(row["category"]) in cat_options else 0
                    cat_choice = st.selectbox("Category", cat_options, index=cat_index, key=f"ucat_choice_{tid}")

                    default_cost = safe_float(row["cost_price"])
                    default_sell = safe_float(row["selling_price"])
                    avail = 0
                    ncat = ""
                    nprod = ""

                    if cat_choice == "➕ New Category":
                        ncat = st.text_input("New Category", value=str(row["category"]), key=f"ncat_new_{tid}")
                        nprod = st.text_input("New Product", value=str(row["product"]), key=f"nprod_new_{tid}")
                    else:
                        ncat = cat_choice
                        pdata = get_prods(c, bid, ncat)
                        pnames = [p["product_name"] for p in pdata]
                        if str(row["product"]) not in pnames:
                            pnames = [str(row["product"])] + pnames
                        pnames = list(dict.fromkeys(pnames + ["➕ New Product"]))

                        prod_index = pnames.index(str(row["product"])) if str(row["product"]) in pnames else 0
                        psel = st.selectbox("Product", pnames, index=prod_index, key=f"uprod_choice_{tid}")

                        if psel == "➕ New Product":
                            nprod = st.text_input("New Product Name", value=str(row["product"]), key=f"nprod_text_{tid}")
                        else:
                            nprod = psel
                            snapshot = get_inventory_snapshot(c, bid, ncat, nprod)
                            if ncat == str(row["category"]) and nprod == str(row["product"]):
                                avail = snapshot["stock"]
                            else:
                                default_cost = snapshot["cost_price"]
                                default_sell = snapshot["selling_price"]
                                avail = snapshot["stock"]

                    cost_key, sell_key = sync_price_fields(
                        f"upd_pur_{tid}",
                        default_cost,
                        default_sell,
                        ncat,
                        nprod,
                    )

                    c1, c2, c3 = st.columns(3)
                    ncost = c1.number_input("Cost Price", min_value=0.0, key=cost_key)
                    nsell = c2.number_input("Sell Price", min_value=0.0, key=sell_key)
                    newqty = c3.number_input("Quantity", min_value=1, value=safe_int(row["quantity"]), key=f"nq_pur_{tid}")

                    if nprod:
                        c3.caption(f"📦 Available Stock: **{avail}** units")

                    profit_preview(ncost, nsell)

                    if st.button("Update Transaction", type="primary", key=f"upd_pur_btn_{tid}"):
                        if not ncat or not nprod:
                            st.warning("⚠️ Fill Category and Product.")
                        else:
                            try:
                                reverse(c, bid, row)
                                apply_txn_effect(c, bid, ntype, ncat, nprod, newqty, ncost, nsell, ndt)
                                c.execute(
                                    "UPDATE transactions SET type=?,category=?,product=?,transaction_date=?,quantity=?,cost_price=?,selling_price=? "
                                    "WHERE transaction_id=? AND business_id=?",
                                    (ntype, ncat, nprod, to_date(ndt), newqty, ncost, nsell, tid, bid),
                                )
                                conn.commit()
                                st.success("✅ Transaction updated.")
                                st.rerun()
                            except Exception as e:
                                conn.rollback()
                                st.error(e)

                elif ntype == "Sale":
                    cats_list = get_cats(c, bid)
                    cat_options = list(dict.fromkeys(([str(row["category"])] if row["category"] else []) + cats_list))
                    cat_index = cat_options.index(str(row["category"])) if str(row["category"]) in cat_options else 0
                    ncat = st.selectbox("Category", cat_options, index=cat_index, key=f"ucat_sale_{tid}")

                    pdata = get_prods(c, bid, ncat)
                    pnames = [p["product_name"] for p in pdata]
                    if str(row["product"]) not in pnames:
                        pnames = [str(row["product"])] + pnames
                    pnames = list(dict.fromkeys(pnames))

                    prod_index = pnames.index(str(row["product"])) if str(row["product"]) in pnames else 0
                    nprod = st.selectbox("Product", pnames, index=prod_index, key=f"uprod_sale_{tid}")

                    snapshot = get_inventory_snapshot(c, bid, ncat, nprod)
                    default_cost = snapshot["cost_price"]
                    default_sell = snapshot["selling_price"]
                    avail = snapshot["stock"]

                    cost_key, sell_key = sync_price_fields(
                        f"upd_sal_{tid}",
                        default_cost,
                        default_sell,
                        ncat,
                        nprod,
                    )

                    c1, c2, c3 = st.columns(3)
                    ncost = c1.number_input("Cost Price", min_value=0.0, key=cost_key)
                    nsell = c2.number_input("Sell Price", min_value=0.0, key=sell_key)
                    newqty = c3.number_input("Quantity", min_value=1, value=safe_int(row["quantity"]), key=f"nq_sale_{tid}")
                    c3.caption(f"📦 Available Stock: **{avail}** units")

                    profit_preview(ncost, nsell)

                    if st.button("Update Transaction", type="primary", key=f"upd_sale_btn_{tid}"):
                        if not ncat or not nprod:
                            st.warning("⚠️ Select Category and Product.")
                        else:
                            try:
                                reverse(c, bid, row)
                                apply_txn_effect(c, bid, ntype, ncat, nprod, newqty, ncost, nsell, ndt)
                                c.execute(
                                    "UPDATE transactions SET type=?,category=?,product=?,transaction_date=?,quantity=?,cost_price=?,selling_price=? "
                                    "WHERE transaction_id=? AND business_id=?",
                                    (ntype, ncat, nprod, to_date(ndt), newqty, ncost, nsell, tid, bid),
                                )
                                conn.commit()
                                st.success("✅ Transaction updated.")
                                st.rerun()
                            except Exception as e:
                                conn.rollback()
                                st.error(e)

    elif op == "Delete":
        mode = st.radio("🗑️ Mode", ["Multiple Records", "All"], horizontal=True, key=f"dm_{bid}")

        if mode == "All":
            st.warning("⚠️ This will reset ALL transactions for this business.")
            if st.button("🗑️ Reset All", type="primary", key=f"reset_all_{bid}"):
                try:
                    c.execute("SELECT * FROM transactions WHERE business_id=?", (bid,))
                    all_rows = fetch_all(c)
                    for r in all_rows:
                        reverse(c, bid, r)
                    c.execute("DELETE FROM transactions WHERE business_id=?", (bid,))
                    conn.commit()
                    st.success("✅ All transactions deleted.")
                    st.rerun()
                except Exception as e:
                    conn.rollback()
                    st.error(e)

        else:
            if df.empty:
                st.info("No transactions to delete.")
            else:
                del_df = df.copy()
                del_df["transaction_date"] = pd.to_datetime(del_df["transaction_date"], errors="coerce")

                use_date = st.checkbox("Filter by Date Range", key=f"del_date_cb_{bid}")
                if use_date:
                    d1, d2 = st.columns(2)
                    date_from = d1.date_input("From", key=f"del_from_{bid}")
                    date_to_val = d2.date_input("To", key=f"del_to_{bid}")
                    del_df = del_df[
                        (del_df["transaction_date"].dt.date >= date_from)
                        & (del_df["transaction_date"].dt.date <= date_to_val)
                    ]

                    delete_mode = st.radio(
                        "Delete Option",
                        ["Delete Specific Records", "Delete All Records In Selected Range"],
                        horizontal=True,
                        key=f"range_delete_mode_{bid}",
                    )

                    if delete_mode == "Delete All Records In Selected Range":
                        st.dataframe(del_df, use_container_width=True, hide_index=True)
                        if del_df.empty:
                            st.info("No transactions found in selected date range.")
                        elif st.button("🗑️ Delete All In Selected Range", type="primary", key=f"del_all_range_{bid}"):
                            delete_txns(
                                c,
                                conn,
                                bid,
                                del_df,
                                f"✅ {len(del_df)} record(s) deleted from selected date range.",
                            )
                        conn.close()
                        return

                cats = ["(All)"] + sorted(del_df["category"].dropna().unique().tolist())
                selected_cat = st.selectbox("🏷Filter Category", cats, key=f"dcat_{bid}")
                if selected_cat != "(All)":
                    del_df = del_df[del_df["category"] == selected_cat]

                prods = ["(All)"] + sorted(del_df["product"].dropna().unique().tolist())
                selected_prod = st.multiselect("Filter Products", prods, default=["(All)"], key=f"dprods_{bid}")
                if "(All)" not in selected_prod and selected_prod:
                    del_df = del_df[del_df["product"].isin(selected_prod)]

                st.dataframe(del_df, use_container_width=True, hide_index=True)

                tids = st.multiselect(
                    "Transaction IDs to Delete",
                    sorted(del_df["transaction_id"].tolist(), reverse=True),
                    key=f"dtids_{bid}",
                )

                if tids and st.button("🗑️ Delete Selected", type="primary", key=f"del_sel_{bid}"):
                    delete_txns(
                        c,
                        conn,
                        bid,
                        del_df[del_df["transaction_id"].isin(tids)],
                        f"✅ {len(tids)} record(s) deleted.",
                    )

    conn.close()
