import streamlit as st, hashlib, pandas as pd, plotly.express as px
from datetime import datetime, timedelta
from db_connection import get_connection
from analysis import analysis_page
from inventory import inventory_page
from forecast import analytics_forecasting_page
from report_generator import generate_full_report
from transactions import transactions_page

DEFAULT_IMAGE = "https://cdn-icons-png.flaticon.com/512/149/149071.png"


def hp(p):
    return hashlib.sha256(p.encode()).hexdigest()


def gv(r, k):
    return (dict(r)[k] if r else 0) if r else 0


def db():
    return get_connection()


def open_section(section):
    st.session_state.dashboard_section = section
    st.rerun()


def load_businesses():
    conn = db()
    c = conn.cursor()
    c.execute("SELECT business_id,business_name FROM businesses WHERE user_id=?", (st.session_state.user_id,))
    d = [dict(r) for r in c.fetchall()]
    conn.close()
    return d


def get_user():
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (st.session_state.user_id,))
    u = c.fetchone()
    conn.close()
    return dict(u) if u else None


def get_kpi():
    if "business_id" not in st.session_state:
        return 0, 0, 0, 0

    bid = st.session_state.business_id
    conn = db()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) AS t FROM transactions WHERE business_id=?", (bid,))
    tx = gv(c.fetchone(), "t")

    c.execute("SELECT COUNT(*) AS t FROM inventory WHERE business_id=?", (bid,))
    prod = gv(c.fetchone(), "t")

    cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    c.execute(
        "SELECT SUM((selling_price-cost_price)*quantity) AS t FROM transactions WHERE business_id=? AND type='Sale' AND transaction_date>=?",
        (bid, cutoff),
    )
    profit = gv(c.fetchone(), "t") or 0

    c.execute("SELECT SUM(selling_price*quantity) AS t FROM transactions WHERE business_id=? AND type='Sale'", (bid,))
    revenue = gv(c.fetchone(), "t") or 0

    conn.close()
    return tx, prod, profit, revenue


def get_sales_trend():
    if "business_id" not in st.session_state:
        return pd.DataFrame(columns=["month", "profit", "revenue"])

    bid = st.session_state.business_id
    conn = db()
    c = conn.cursor()

    c.execute(
        "SELECT transaction_date, selling_price, cost_price, quantity "
        "FROM transactions WHERE business_id=? AND type='Sale'",
        (bid,),
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    if not rows:
        return pd.DataFrame(columns=["month", "profit", "revenue"])

    df = pd.DataFrame(rows)
    df["transaction_date"] = pd.to_datetime(df["transaction_date"], errors="coerce")
    df = df.dropna(subset=["transaction_date"])

    if df.empty:
        return pd.DataFrame(columns=["month", "profit", "revenue"])

    cutoff = pd.Timestamp.now() - pd.DateOffset(months=3)
    df = df[df["transaction_date"] >= cutoff]

    if df.empty:
        return pd.DataFrame(columns=["month", "profit", "revenue"])

    df["selling_price"] = pd.to_numeric(df["selling_price"], errors="coerce").fillna(0)
    df["cost_price"] = pd.to_numeric(df["cost_price"], errors="coerce").fillna(0)
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0)

    df["profit"] = (df["selling_price"] - df["cost_price"]) * df["quantity"]
    df["revenue_value"] = df["selling_price"] * df["quantity"]
    df["month"] = df["transaction_date"].dt.to_period("M").astype(str)

    trend = (
        df.groupby("month", as_index=False)
        .agg(
            profit=("profit", "sum"),
            revenue=("revenue_value", "sum"),
        )
        .sort_values("month")
    )

    return trend


def run_query(sql, params=(), commit=False):
    conn = db()
    c = conn.cursor()
    c.execute(sql, params)
    if commit:
        conn.commit()
    conn.close()


def biz_exists(name, exclude_id=None):
    conn = db()
    c = conn.cursor()
    sql = "SELECT COUNT(*) AS t FROM businesses WHERE user_id=? AND business_name=?"
    args = [st.session_state.user_id, name]
    if exclude_id:
        sql += " AND business_id!=?"
        args.append(exclude_id)
    c.execute(sql, args)
    r = gv(c.fetchone(), "t")
    conn.close()
    return r > 0


def create_business(name):
    name = name.strip()
    if not name:
        return st.error("Name cannot be empty.")
    if biz_exists(name):
        return st.error(f'"{name}" already exists.')
    run_query(
        "INSERT INTO businesses (user_id,business_name) VALUES (?,?)",
        (st.session_state.user_id, name),
        commit=True,
    )
    st.success(f'"{name}" created.')
    st.rerun()


def rename_business(bid, new):
    new = new.strip()
    if not new:
        return st.error("Name cannot be empty.")
    if biz_exists(new, exclude_id=bid):
        return st.error(f'"{new}" already exists.')
    run_query("UPDATE businesses SET business_name=? WHERE business_id=?", (new, bid), commit=True)
    if st.session_state.get("business_id") == bid:
        st.session_state.selected_business_name = new
    st.success(f'Renamed to "{new}".')
    st.rerun()


def delete_business(bid, name):
    conn = db()
    c = conn.cursor()
    try:
        for tbl in ("transactions", "inventory"):
            c.execute(f"DELETE FROM {tbl} WHERE business_id=?", (bid,))
        c.execute("DELETE FROM businesses WHERE business_id=? AND user_id=?", (bid, st.session_state.user_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return st.error(f"Delete failed: {e}")
    conn.close()
    if st.session_state.get("business_id") == bid:
        st.session_state.pop("business_id", None)
        st.session_state.pop("selected_business_name", None)
    st.success(f'"{name}" deleted.')
    st.rerun()


def profile_page():
    st.title("👤 Profile Settings")
    user = get_user()

    st.subheader("🧑 User Details")
    c1, c2 = st.columns(2)
    name = c1.text_input("First Name", user["first_name"])
    last = c2.text_input("Last Name", user.get("last_name", ""))
    email = st.text_input("Email", user["email"])
    phone = st.text_input("Phone", user.get("phone", "") or "")
    username = st.text_input("Username", user.get("username", "") or "")
    st.text_input("Role", user.get("role", ""), disabled=True)

    if st.button("Update Profile", type="primary"):
        run_query(
            "UPDATE users SET first_name=?,last_name=?,email=?,phone=?,username=? WHERE user_id=?",
            (name, last, email, phone, username, st.session_state.user_id),
            commit=True,
        )
        st.session_state.first_name = name
        st.session_state.last_name = last
        st.success("Profile Updated")
        st.rerun()

    st.divider()

    st.subheader("🔐 Change Password")
    old = st.text_input("Old Password", type="password")
    new = st.text_input("New Password", type="password")
    confirm = st.text_input("Confirm Password", type="password")
    if st.button("Change Password", type="primary"):
        if hp(old) != user["password"]:
            st.error("Incorrect old password")
        elif new != confirm:
            st.error("Passwords do not match")
        else:
            run_query(
                "UPDATE users SET password=? WHERE user_id=?",
                (hp(new), st.session_state.user_id),
                commit=True,
            )
            st.success("Password Updated")

    st.divider()
    st.subheader("🏢 Business Settings")
    businesses = load_businesses()

    with st.expander("➕ Add New Business"):
        n = st.text_input("Business Name", key="new_biz")
        if st.button("Create", type="primary", key="btn_create"):
            create_business(n)

    if businesses:
        biz_options = {b["business_id"]: b["business_name"] for b in businesses}
        biz_ids = list(biz_options.keys())
        biz_names = list(biz_options.values())

        if "prof_selected_bid" not in st.session_state:
            st.session_state.prof_selected_bid = biz_ids[0]
        if st.session_state.prof_selected_bid not in biz_ids:
            st.session_state.prof_selected_bid = biz_ids[0]

        current_index = biz_ids.index(st.session_state.prof_selected_bid)

        sel_name = st.selectbox(
            "Select Business to Manage",
            biz_names,
            index=current_index,
            key="prof_biz_select",
        )
        sel_index = biz_names.index(sel_name)
        sel_bid = biz_ids[sel_index]
        st.session_state.prof_selected_bid = sel_bid

        st.info(f"📌 Currently managing: **{sel_name}** (ID: {sel_bid})")
        st.markdown("#### ✏️ Rename Business")
        new_name = st.text_input("New Name", value=sel_name, key=f"rename_input_{sel_bid}")
        if st.button("Rename", type="primary", key="btn_rename"):
            if new_name.strip() == sel_name:
                st.info("No change detected.")
            else:
                rename_business(sel_bid, new_name)

        st.markdown("#### 🗑️ Delete Business")
        st.warning("⚠️ This permanently removes all transactions & inventory. Cannot be undone.")
        conf = st.text_input(
            f'Type **"{sel_name}"** to confirm deletion',
            key=f"confirm_del_{sel_bid}",
            placeholder=sel_name,
        )
        delete_disabled = conf.strip() != sel_name
        if st.button("Delete Business", type="secondary", key="btn_delete", disabled=delete_disabled):
            delete_business(sel_bid, sel_name)
    else:
        st.info("No businesses yet. Create one above!")


def report_page():
    st.title("📄 Smart Report Generator")
    st.write("---")
    if "data" not in st.session_state:
        return st.warning("⚠️ Step 1: Load data in Analytics first.")
    if "forecast_result" not in st.session_state:
        return st.warning("⚠️ Step 2: Run Forecast first.")
    st.success("✅ Ready to generate.")
    if st.button("🛠️ Generate & Download Report", type="primary"):
        with st.spinner("Generating..."):
            fp = generate_full_report()
            if fp:
                with open(fp, "rb") as f:
                    st.download_button(
                        "📥 Download Report",
                        f.read(),
                        file_name=f"Business_Report_{datetime.now().strftime('%Y%m%d')}.pdf",
                        mime="application/pdf",
                        type="primary",
                    )
                st.success("Done!")


def dashboard_page():
    st.session_state.setdefault("dashboard_section", "overview")

    with st.sidebar:
        st.image(DEFAULT_IMAGE, width=80)
        st.markdown(f"### 👤 {st.session_state.get('first_name', '')}")

        if st.button("🚪 Logout", type="secondary"):
            st.session_state.clear()
            st.rerun()

        st.divider()

        if st.button("📊 Overview", type="secondary"):
            open_section("overview")

        st.divider()
        businesses = load_businesses()
        if businesses:
            biz_names = [b["business_name"] for b in businesses]
            cur = st.session_state.get("selected_business_name", biz_names[0])
            sel = st.selectbox(
                "🏢 Select Business",
                biz_names,
                index=biz_names.index(cur) if cur in biz_names else 0,
            )
            bid = next(b["business_id"] for b in businesses if b["business_name"] == sel)
            if st.session_state.get("business_id") != bid:
                st.session_state.business_id = bid
                st.session_state.selected_business_name = sel
                st.rerun()

        st.divider()
        st.markdown("### 📊 Business Tools")
        for lbl, sec in [
            ("💰 Transactions Management", "transactions"),
            ("📦 Inventory Management", "inventory"),
            ("📊 Real time Analytics", "analysis"),
        ]:
            if st.button(lbl, type="secondary"):
                open_section(sec)

        st.divider()
        st.markdown("### 🚀 Advanced Tools")
        for lbl, sec in [("📈 AI Prediction", "forecast"), ("📄 Smart Reporting", "report")]:
            if st.button(lbl, type="secondary"):
                open_section(sec)

        st.divider()
        if st.button("👤 Profile", type="secondary"):
            open_section("profile")

    sec = st.session_state.dashboard_section

    if sec == "overview":
        user = get_user()
        first = user.get("first_name", "") if isinstance(user, dict) else user[1]
        last = user.get("last_name", "") if isinstance(user, dict) else user[2]
        st.title(f"👋 Welcome {first} {last} to {st.session_state.get('selected_business_name', 'Dashboard')}".strip())
        st.markdown("### 📊 Business Overview")

        tx, prod, profit, revenue = get_kpi()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("💰 Transactions", tx)
        c2.metric("📦 Products", prod)
        c3.metric("📈 Last 3M Profit", f"₹{profit:,.0f}")
        c4.metric("💵 Revenue", f"₹{revenue:,.0f}")

        st.divider()
        st.subheader("📈 Profit Trend (Last 3 Months)")
        trend = get_sales_trend()

        if trend.empty or "profit" not in trend.columns:
            st.info("No data available for the selected business.")
        else:
            best = trend.loc[trend["profit"].idxmax()]
            worst = trend.loc[trend["profit"].idxmin()]

            sc1, sc2, sc3 = st.columns(3)
            sc1.metric("📅 Months Shown", len(trend))
            sc2.metric("🏆 Best Month", f"{best['month']} (₹{best['profit']:,.0f})")
            sc3.metric("📉 Worst Month", f"{worst['month']} (₹{worst['profit']:,.0f})")

            fig = px.line(
                trend,
                x="month",
                y="profit",
                markers=True,
                labels={"month": "Month", "profit": "Profit (₹)"},
                title="Monthly Profit – Last 3 Months",
            )
            fig.update_traces(line_color="#2ecc71", marker=dict(size=8, color="#27ae60"))
            fig.update_layout(
                xaxis_title="Month",
                yaxis_title="Profit (₹)",
                hovermode="x unified",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig, use_container_width=True)

    else:
        {
            "transactions": transactions_page,
            "inventory": inventory_page,
            "analysis": analysis_page,
            "forecast": analytics_forecasting_page,
            "report": report_page,
            "profile": profile_page,
        }.get(sec, lambda: None)()
