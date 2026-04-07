import streamlit as st
import pandas as pd
import plotly.express as px
import numpy as np
from db_connection import get_connection


def run_query(sql, params=()):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return pd.DataFrame(rows)


def get_transactions():
    return run_query(
        "SELECT * FROM transactions WHERE business_id=? ORDER BY transaction_id DESC",
        (st.session_state.business_id,),
    )


def get_inventory():
    return run_query(
        "SELECT * FROM inventory WHERE business_id=? ORDER BY added_date DESC",
        (st.session_state.business_id,),
    )


def get_low_stock_threshold():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT setting_value FROM system_settings WHERE setting_name='low_stock_threshold' AND business_id=?",
        (st.session_state.business_id,),
    )
    r = cursor.fetchone()
    conn.close()
    try:
        return int(dict(r)["setting_value"]) if r else 10
    except:
        return 10


def safe_numeric_series(df, col, default=0):
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").fillna(default)
    return pd.Series([default] * len(df), index=df.index, dtype="float64")


def safe_category_counts(df, col_name):
    if col_name not in df.columns or df.empty:
        return pd.DataFrame(columns=[col_name, "count"])
    counts = df[col_name].fillna("Unknown").value_counts().reset_index()
    counts.columns = [col_name, "count"]
    return counts


def analysis_page():
    st.title("📊 Analytics")

    option = st.radio("Select Source", ["Transactions", "Inventory", "Upload CSV"], horizontal=True)

    if "last_option" not in st.session_state:
        st.session_state.last_option = option

    if st.session_state.last_option != option:
        st.session_state.pop("data", None)
        st.session_state.last_option = option

    if option == "Transactions":
        if st.button("Load Data", type="primary"):
            st.session_state.data = get_transactions()

    elif option == "Inventory":
        if st.button("Load Data", type="primary"):
            st.session_state.data = get_inventory()

    else:
        file = st.file_uploader("Upload CSV")
        if file:
            df_up = pd.read_csv(file)
            df_up.columns = df_up.columns.str.lower().str.strip()
            st.session_state.data = df_up

    if "data" not in st.session_state:
        st.info("Load data to see analytics.")
        return

    df = st.session_state.data.copy()

    if df.empty:
        st.info("No data available for the selected business.")
        return

    product_col = "product_name" if "product_name" in df.columns else "product"
    qty_col = "stock" if "stock" in df.columns else "quantity"
    date_col = "added_date" if "added_date" in df.columns else "transaction_date"

    df["cost_price"] = safe_numeric_series(df, "cost_price", 0)
    df["selling_price"] = safe_numeric_series(df, "selling_price", 0)
    df["quantity_fixed"] = safe_numeric_series(df, qty_col, 0)

    if date_col in df.columns:
        df["date"] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=["date"])
        if not df.empty:
            df["year"] = df["date"].dt.year
            df["month_name"] = df["date"].dt.strftime("%b")

    if df.empty:
        st.info("No data available for the selected business.")
        return

    month_order = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    threshold = get_low_stock_threshold()
    df["Status"] = df["quantity_fixed"].apply(
        lambda q: "Out of Stock" if q == 0 else "Low Stock" if q <= threshold else "In Stock"
    )

    if option in ["Transactions", "Upload CSV"]:
        type_series = df["type"] if "type" in df.columns else pd.Series([""] * len(df), index=df.index)
        df["revenue"] = np.where(type_series == "Sale", df["selling_price"] * df["quantity_fixed"], 0)
        df["expenses"] = np.where(
            type_series.isin(["Purchase", "Expense"]),
            df["cost_price"] * df["quantity_fixed"],
            0,
        )
        df["profit"] = df["revenue"] - df["expenses"]
    else:
        df["inv_value"] = df["cost_price"] * df["quantity_fixed"]

    st.session_state.data = df
    tab1, tab2 = st.tabs(["📋 Summary Overview", "📈 Visual Analytics"])

    with tab1:
        st.subheader("📊 Summary Metrics")

        inv_df = get_inventory()
        if inv_df.empty:
            inv_df = pd.DataFrame(columns=["product_name", "stock", "cost_price", "category"])

        product_col_inv = "product_name" if "product_name" in inv_df.columns else "product"
        qty_col_inv = "stock" if "stock" in inv_df.columns else "quantity"

        inv_df["cost_price"] = safe_numeric_series(inv_df, "cost_price", 0)
        inv_df["quantity_fixed"] = safe_numeric_series(inv_df, qty_col_inv, 0)
        inv_df["inv_value"] = inv_df["cost_price"] * inv_df["quantity_fixed"]

        total_inv = inv_df["inv_value"].sum() if not inv_df.empty else 0
        total_prod = inv_df[product_col_inv].nunique() if product_col_inv in inv_df.columns else 0
        low = inv_df[(inv_df["quantity_fixed"] > 0) & (inv_df["quantity_fixed"] <= threshold)].shape[0]
        out = inv_df[inv_df["quantity_fixed"] == 0].shape[0]

        if option == "Inventory":
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("📦 Total Inventory Value", f"₹ {total_inv:,.0f}")
            c2.metric("📦 Total Products", total_prod)
            c3.metric("⚠️ Low Stock Products", low)
            c4.metric("🚫 Out of Stock Products", out)
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("💰 Revenue", f"₹ {df['revenue'].sum():,.0f}")
            c2.metric("💸 Expenses", f"₹ {df['expenses'].sum():,.0f}")
            c3.metric("📈 Profit", f"₹ {df['profit'].sum():,.0f}")

        st.subheader("📄 Data Table")
        clean_df = df.copy()
        for col in ["quantity_fixed", "year", "month_name", "Status", "date", "business_id", "profit", "revenue", "expenses"]:
            if col in clean_df.columns:
                clean_df = clean_df.drop(columns=[col])

        clean_df = clean_df.rename(columns={"product_name": "product", "added_date": "transaction_date", "stock": "quantity"})

        if option == "Transactions":
            req = ["transaction_id", "type", "category", "product", "quantity", "cost_price", "selling_price", "transaction_date"]
            for c in req:
                if c not in clean_df.columns:
                    clean_df[c] = 0
            st.dataframe(clean_df[req], use_container_width=True)
            if st.button("🚀 Send Data to Forecast", type="primary"):
                st.session_state["sales_data"] = df
                st.success("Data sent to Forecast module!")

        elif option == "Inventory":
            req = ["product", "category", "quantity", "cost_price", "selling_price", "inv_value"]
            for c in req:
                if c not in clean_df.columns:
                    clean_df[c] = 0
            st.dataframe(clean_df[req], use_container_width=True)

        else:
            st.dataframe(clean_df, use_container_width=True)
            if st.button("🚀 Send Data to Forecast", type="primary"):
                st.session_state["sales_data"] = df
                st.success("Data sent to Forecast module!")

    with tab2:
        if option in ["Transactions", "Upload CSV"] and "year" in df.columns and not df.empty:
            years = sorted(df["year"].dropna().unique())

            if len(years) == 0:
                st.info("No dated transaction data available for analytics.")
                return

            st.subheader("📊 Monthly Financial Analysis")
            y1 = st.selectbox("Select Year", years, key="y1")
            monthly = (
                df[df["year"] == y1]
                .groupby("month_name")[["revenue", "expenses", "profit"]]
                .sum()
                .reindex(month_order, fill_value=0)
                .reset_index()
            )
            st.plotly_chart(px.bar(monthly, x="month_name", y=["revenue", "expenses", "profit"], barmode="group"), use_container_width=True)

            st.subheader("📅 Monthly Transactions Count")
            y2 = st.selectbox("Select Year", years, key="y2")
            tx = (
                df[df["year"] == y2]
                .groupby("month_name")
                .size()
                .reindex(month_order, fill_value=0)
                .reset_index(name="count")
            )
            st.plotly_chart(px.bar(tx, x="month_name", y="count"), use_container_width=True)

            st.subheader("💸 Expense Distribution (Category)")
            y3 = st.selectbox("Select Year", years, key="y3")
            edf = df[(df["year"] == y3) & (df["type"].isin(["Purchase", "Expense"]))].copy()
            if "category" in edf.columns and not edf.empty:
                es = edf.groupby("category")["expenses"].sum().reset_index()
                st.plotly_chart(px.pie(es, names="category", values="expenses"), use_container_width=True)
            else:
                st.info("No expense data available.")

            st.subheader("🏆 Top Selling Products")
            y4 = st.selectbox("Select Year", years, key="y4")
            m4 = st.selectbox("Select Month", month_order, key="m4")
            df_y4 = df[(df["year"] == y4) & (df["month_name"] == m4) & (df["type"] == "Sale")]
            tp = df_y4.groupby(product_col)["quantity_fixed"].sum().reset_index()
            if not tp.empty:
                st.plotly_chart(
                    px.bar(tp.sort_values(by="quantity_fixed", ascending=False), x=product_col, y="quantity_fixed"),
                    use_container_width=True,
                )
            else:
                st.warning("No sales data")

        else:
            if df.empty:
                st.info("No inventory data available for analytics.")
                return

            st.subheader("📦 Inventory Value by Category")
            cat_value = df.groupby("category")["inv_value"].sum().reset_index() if "category" in df.columns else pd.DataFrame()
            if not cat_value.empty:
                st.plotly_chart(px.bar(cat_value, x="category", y="inv_value"), use_container_width=True)
            else:
                st.info("No category data available.")

            st.subheader("🥧 Category Distribution")
            cat_dist = safe_category_counts(df, "category")
            if not cat_dist.empty:
                st.plotly_chart(px.pie(cat_dist, names="category", values="count"), use_container_width=True)
            else:
                st.info("No category distribution available.")

            st.subheader("📊 Stock Status Levels")
            status_dist = safe_category_counts(df, "Status")
            if not status_dist.empty:
                st.plotly_chart(px.pie(status_dist, names="Status", values="count"), use_container_width=True)
            else:
                st.info("No stock status data available.")
