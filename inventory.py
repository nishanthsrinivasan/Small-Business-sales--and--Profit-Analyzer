import streamlit as st
import pandas as pd
from datetime import date
from db_connection import get_connection


# --- HELPERS ---
def safe_int(x):
    return int(float(x)) if x else 0


def safe_float(x):
    return float(x) if x else 0.0


def fmt_date(dt):
    return dt.strftime("%Y-%m-%d") if isinstance(dt, (date, pd.Timestamp)) else str(dt)


def db_exec(c, conn, sql, params, msg):
    try:
        c.execute(sql, params)
        conn.commit()
        st.success(f"✅ {msg}")
        st.rerun()
    except Exception as e:
        conn.rollback()
        st.error(f"❌ {e}")


def get_inv(c, bid):
    c.execute("SELECT * FROM inventory WHERE business_id=? ORDER BY product_id DESC", (bid,))
    rows = [dict(row) for row in c.fetchall()]
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["product_id", "product_name", "stock", "cost_price", "selling_price", "added_date", "category"]
    )


def get_threshold(c, bid):
    c.execute(
        "SELECT setting_value FROM system_settings WHERE setting_name='low_stock_threshold' AND business_id=?",
        (bid,),
    )
    r = c.fetchone()
    return int(dict(r)["setting_value"]) if r else 5


def delete_inventory_only(c, conn, bid, rows_df, msg):
    try:
        if rows_df.empty:
            st.warning("No records selected.")
            return

        ids = rows_df["product_id"].tolist()
        c.execute(
            f"DELETE FROM inventory WHERE product_id IN ({','.join(['?'] * len(ids))}) AND business_id=?",
            (*ids, bid),
        )
        conn.commit()
        st.success(msg)
        st.rerun()
    except Exception as e:
        conn.rollback()
        st.error(f"❌ {e}")


# --- MAIN PAGE ---
def inventory_page():
    st.title("📦 Inventory Management")
    bid = st.session_state.get("business_id")
    if not bid:
        st.warning("⚠️ Select a Business first.")
        return

    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT business_name FROM businesses WHERE business_id=?", (bid,))
    brow = c.fetchone()
    if not brow:
        st.error("❌ Business not found.")
        conn.close()
        return

    st.info(f"📌 Business: **{dict(brow)['business_name']}**")
    threshold = get_threshold(c, bid)

    # --- PREVIEW & STATUS ---
    df = get_inv(c, bid)
    st.subheader("📋 Inventory Preview")

    if not df.empty:
        fdf = df.copy()
        c1, c2 = st.columns(2)

        cat_list = ["All"] + sorted(df["category"].dropna().unique().tolist())
        sel_f_cat = c1.selectbox("Filter Category", cat_list, key=f"inv_fcat_{bid}")

        prod_list = ["All"] + (
            sorted(df[df["category"] == sel_f_cat]["product_name"].unique().tolist())
            if sel_f_cat != "All"
            else sorted(df["product_name"].unique().tolist())
        )
        sel_f_prod = c2.selectbox("Filter Product", prod_list, key=f"inv_fprod_{bid}")

        if sel_f_cat != "All":
            fdf = fdf[fdf["category"] == sel_f_cat]
        if sel_f_prod != "All":
            fdf = fdf[fdf["product_name"] == sel_f_prod]

        if st.checkbox("📅 Filter by Date Range", key=f"inv_preview_date_cb_{bid}"):
            fdf["added_date"] = pd.to_datetime(fdf["added_date"], errors="coerce")
            d1, d2 = st.columns(2)
            date_from = d1.date_input("From", key=f"inv_preview_from_{bid}")
            date_to_val = d2.date_input("To", key=f"inv_preview_to_{bid}")
            fdf = fdf[
                (fdf["added_date"].dt.date >= date_from)
                & (fdf["added_date"].dt.date <= date_to_val)
            ]

        st.dataframe(fdf, use_container_width=True, hide_index=True)

        st.subheader("📊 Stock Status Details")
        low_df = df[(df["stock"] > 0) & (df["stock"] <= threshold)]
        oos_df = df[df["stock"] <= 0]

        m1, m2 = st.columns(2)
        m1.metric("🚨 Low Stock Count", len(low_df))
        m2.metric("🚫 Out of Stock Count", len(oos_df))

        if not low_df.empty:
            with st.expander("View Low Stock Products"):
                st.dataframe(low_df, use_container_width=True, hide_index=True)

        if not oos_df.empty:
            with st.expander("View Out of Stock Products"):
                st.dataframe(oos_df, use_container_width=True, hide_index=True)
    else:
        st.info("Inventory is currently empty.")

    st.divider()
    st.subheader("🛠️ Inventory Operations")
    op = st.selectbox("Operation", ["Select", "Delete"], key=f"inv_op_{bid}")

    # --- DELETE ---
    if op == "Delete" and not df.empty:
        mode = st.radio("Delete Mode", ["Select Records", "All"], horizontal=True)

        if mode == "All":
            st.warning("⚠️ This will delete ALL inventory for this business. Transaction history will be kept.")
            if st.text_input("Type 'DELETE ALL'") == "DELETE ALL":
                if st.button("🗑️ Confirm Delete All", type="primary"):
                    db_exec(c, conn, "DELETE FROM inventory WHERE business_id=?", (bid,), "Inventory Cleared")

        else:
            del_df = df.copy()
            del_df["added_date"] = pd.to_datetime(del_df["added_date"], errors="coerce")

            use_date = st.checkbox("Filter by Date Range", key=f"inv_del_date_cb_{bid}")
            if use_date:
                d1, d2 = st.columns(2)
                date_from = d1.date_input("From", key=f"inv_del_from_{bid}")
                date_to_val = d2.date_input("To", key=f"inv_del_to_{bid}")

                del_df = del_df[
                    (del_df["added_date"].dt.date >= date_from)
                    & (del_df["added_date"].dt.date <= date_to_val)
                ]

                delete_mode = st.radio(
                    "Delete Option",
                    ["Delete Specific Records", "Delete All Records In Selected Range"],
                    horizontal=True,
                    key=f"inv_range_delete_mode_{bid}",
                )

                if delete_mode == "Delete All Records In Selected Range":
                    st.dataframe(del_df, use_container_width=True, hide_index=True)

                    if del_df.empty:
                        st.info("No inventory records found in selected date range.")
                    elif st.button("🗑️ Delete All In Selected Range", type="primary", key=f"inv_del_all_range_{bid}"):
                        delete_inventory_only(
                            c,
                            conn,
                            bid,
                            del_df,
                            f"{len(del_df)} inventory record(s) deleted from selected date range.",
                        )
                    conn.close()
                    return

            cats = ["(All)"] + sorted(del_df["category"].dropna().unique().tolist())
            selected_cat = st.selectbox("🏷 Filter Category", cats, key=f"inv_dcat_{bid}")
            if selected_cat != "(All)":
                del_df = del_df[del_df["category"] == selected_cat]

            prods = ["(All)"] + sorted(del_df["product_name"].dropna().unique().tolist())
            selected_prod = st.multiselect("Filter Products", prods, default=["(All)"], key=f"inv_dprods_{bid}")
            if "(All)" not in selected_prod and selected_prod:
                del_df = del_df[del_df["product_name"].isin(selected_prod)]

            st.dataframe(del_df, use_container_width=True, hide_index=True)

            target_ids = st.multiselect(
                "Product ID(s) to Delete",
                sorted(del_df["product_id"].tolist(), reverse=True),
                key=f"inv_dp_ids_{bid}",
            )

            if target_ids and st.button("🗑️ Delete Selected ID(s)", type="primary", key=f"inv_del_sel_{bid}"):
                delete_inventory_only(
                    c,
                    conn,
                    bid,
                    del_df[del_df["product_id"].isin(target_ids)],
                    f"{len(target_ids)} record(s) deleted.",
                )

    # --- SETTINGS ---
    st.divider()
    st.subheader("⚙️ Inventory Settings")
    val = st.number_input("Low Stock Threshold Value", min_value=0, value=threshold)

    if st.button("💾 Save"):
        c.execute(
            "UPDATE system_settings SET setting_value=? WHERE setting_name='low_stock_threshold' AND business_id=?",
            (val, bid),
        )
        if c.rowcount == 0:
            c.execute(
                "INSERT INTO system_settings(setting_name,setting_value,business_id) VALUES('low_stock_threshold',?,?)",
                (val, bid),
            )
        conn.commit()
        st.success("Threshold Saved")
        st.rerun()

    conn.close()
