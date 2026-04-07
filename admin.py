import streamlit as st
import pandas as pd
import hashlib, smtplib, random
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from db_connection import get_connection

DEFAULT_IMAGE = "https://cdn-icons-png.flaticon.com/512/149/149071.png"
ADMIN_SECRET = "MySuper$ecret2025"
EMAIL_SENDER = "business.analyzer167@gmail.com"
EMAIL_PASSWORD = "qoqzunpymhbmlxzw"


def run_query(q, p=(), fetch=None, commit=False):
    conn = get_connection(); cur = conn.cursor(); cur.execute(q, p)
    res = (cur.fetchall() if fetch == "all" else cur.fetchone()) if fetch else None
    if commit: conn.commit()
    conn.close(); return res


def make_df(rows, cur=None):
    if not rows: return pd.DataFrame()
    return pd.DataFrame(rows, columns=[d[0] for d in cur.description] if cur else None)


def hp(p): return hashlib.sha256(p.encode()).hexdigest()


def send_email(to, subject, body):
    msg = MIMEText(body); msg["Subject"] = subject; msg["From"] = EMAIL_SENDER; msg["To"] = to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(EMAIL_SENDER, EMAIL_PASSWORD); s.sendmail(EMAIL_SENDER, to, msg.as_string())


def admin_dashboard_page():
    conn = get_connection(); cur = conn.cursor()

    with st.sidebar:
        st.image(DEFAULT_IMAGE, width=100)
        st.markdown(f"### 👤 {st.session_state.get('first_name', '')}"); st.markdown("**Role: Admin**")
        if st.button("🚪 Logout", type="secondary"):
            if "login_id" in st.session_state:
                run_query("UPDATE login_history SET logout_time=datetime('now') WHERE id=?", (st.session_state.login_id,), commit=True)
            st.session_state.clear(); st.session_state.page = "login"; st.rerun()
        st.divider()
        pending = run_query("SELECT COUNT(*) as t FROM reactivation_requests WHERE status='pending'", fetch="one")
        pending_count = pending["t"] if pending else 0
        for label, key in [("📊 System Overview", "overview"), ("👥 Manage Users", "users"), ("🏢 Business Profiles", "business")]:
            if st.button(label, type="secondary"): st.session_state.admin_section = key
        req_label = f"🔔 Reactivation Requests ({pending_count})" if pending_count else "🔔 Reactivation Requests"
        if st.button(req_label, type="secondary"): st.session_state.admin_section = "requests"
        st.divider()
        if st.button("👤 Profile", type="secondary"): st.session_state.admin_section = "profile"

    st.session_state.setdefault("admin_section", "overview")
    section = st.session_state.admin_section

    # ── OVERVIEW ──────────────────────────────────────────────────────────
    if section == "overview":
        st.title("📊 System Overview")
        for col, (label, table) in zip(st.columns(4), [("Users", "users"), ("Businesses", "businesses"), ("Transactions", "transactions"), ("Inventory", "inventory")]):
            cur.execute(f"SELECT COUNT(*) as t FROM {table}"); col.metric(label, cur.fetchone()["t"])
        if pending_count: st.warning(f"⚠️ {pending_count} pending reactivation request(s).")
        st.divider(); st.subheader("🕒 Login & Logout History")
        cur.execute("SELECT u.first_name,u.last_name,l.login_time,l.logout_time FROM login_history l JOIN users u ON l.user_id=u.user_id ORDER BY l.login_time DESC")
        st.dataframe(make_df(cur.fetchall(), cur), use_container_width=True)

    # ── MANAGE USERS ──────────────────────────────────────────────────────
    elif section == "users":
        st.subheader("👥 Manage Users")

        # 1. All Users List
        st.divider(); st.subheader("👥 All Users")
        fresh_conn = get_connection(); fresh_cur = fresh_conn.cursor()
        fresh_cur.execute("SELECT user_id,first_name,last_name,username,email,phone,role,status FROM users")
        df = make_df(fresh_cur.fetchall(), fresh_cur); fresh_conn.close()
        search = st.text_input("Search by name", key="users_search")
        if search and not df.empty:
            df = df[df["first_name"].str.contains(search, case=False) | df["last_name"].str.contains(search, case=False)]
        st.dataframe(df, use_container_width=True)
        st.download_button("⬇ Export Users CSV", df.to_csv(index=False), "users.csv", "text/csv", use_container_width=True)

        # 2. Inactive Users
        st.divider(); st.subheader("😴 Inactive Users (Not logged in for 30+ days)")
        cur.execute("""SELECT u.user_id,u.first_name,u.last_name,u.email,MAX(l.login_time) as last_login
                       FROM users u LEFT JOIN login_history l ON u.user_id=l.user_id
                       GROUP BY u.user_id,u.first_name,u.last_name,u.email
                       HAVING last_login IS NULL OR last_login < datetime('now','-30 days')""")
        inactive_df = make_df(cur.fetchall(), cur)
        st.info("No inactive users found.") if inactive_df.empty else st.dataframe(inactive_df, use_container_width=True)

        # 3. User Operations (dropdown last)
        st.divider(); st.subheader("⚙️ User Operations")
        op = st.selectbox("Operation", ["Select", "Create", "Update", "Delete", "Activate", "Deactivate"], key="user_op")

        if op == "Create":
            c1, c2 = st.columns(2)
            fn = c1.text_input("First Name", key="au_fn"); ln = c2.text_input("Last Name", key="au_ln")
            uname = st.text_input("Username", key="au_user"); em = st.text_input("Email", key="au_em")
            ph = st.text_input("Phone", key="au_ph"); pw = st.text_input("Password", type="password", key="au_pw")
            role = st.selectbox("Role", ["User", "Admin"], key="au_role")

            if st.button("📧 Save & Send Email", type="primary", use_container_width=True):
                if not all([fn, ln, uname, em, pw]):
                    st.error("All fields except phone are required.")
                elif run_query("SELECT user_id FROM users WHERE email=? OR phone=? OR username=?", (em, ph, uname), fetch="one"):
                    st.error("User already exists with same email, phone, or username.")
                else:
                    run_query("INSERT INTO users (first_name,last_name,username,email,phone,password,role,status) VALUES (?,?,?,?,?,?,?,'active')",
                              (fn, ln, uname, em, ph, hp(pw), role), commit=True)
                    try:
                        body = f"Hello {fn},\n\nYour account has been created by the admin.\n\nUsername: {uname}\nPassword: {pw}"
                        if role == "Admin": body += f"\nAdmin Secret Code: {ADMIN_SECRET}"
                        body += "\n\nPlease login and change your password."
                        send_email(em, "Your Account Details", body)
                        st.success(f"User saved and credentials sent to {em}.")
                    except Exception as e:
                        st.success("User saved."); st.warning(f"Email failed: {e}")
                    st.rerun()

        elif op in ["Update", "Delete", "Activate", "Deactivate"]:
            name_search = st.text_input("Search user by first or last name", key="op_name_search")
            if name_search:
                cur.execute("SELECT user_id,first_name,last_name,username,email,phone,role,status FROM users WHERE first_name LIKE ? OR last_name LIKE ?",
                            (f"%{name_search}%", f"%{name_search}%"))
                matched_df = make_df(cur.fetchall(), cur)
                if matched_df.empty:
                    st.warning("No users found matching that name.")
                else:
                    matched_df["display"] = matched_df["first_name"] + " " + matched_df["last_name"] + " (" + matched_df["username"] + ")"
                    sel = st.selectbox("Select User", matched_df["display"], key="op_user_select")
                    user = matched_df[matched_df["display"] == sel].iloc[0]
                    uid = int(user["user_id"])

                    if op == "Update":
                        fn = st.text_input("First Name", user["first_name"]); ln = st.text_input("Last Name", user["last_name"])
                        em = st.text_input("Email", user["email"]); ph = st.text_input("Phone", str(user["phone"]))
                        if st.button("Update User", type="primary"):
                            run_query("UPDATE users SET first_name=?,last_name=?,email=?,phone=? WHERE user_id=?", (fn, ln, em, ph, uid), commit=True)
                            st.success("User updated."); st.rerun()

                    elif op == "Delete":
                        st.warning(f"Are you sure you want to delete {user['first_name']} {user['last_name']}?")
                        if st.button("Delete User", type="primary"):
                            run_query("DELETE FROM users WHERE user_id=?", (uid,), commit=True)
                            st.success("User deleted."); st.rerun()

                    elif op == "Activate":
                        if user["status"] == "active": st.info(f"{user['first_name']} {user['last_name']} is already active.")
                        if st.button("Activate User", type="primary"):
                            run_query("UPDATE users SET status='active' WHERE user_id=?", (uid,), commit=True)
                            st.success(f"{user['first_name']} {user['last_name']} activated successfully."); st.rerun()

                    elif op == "Deactivate":
                        if user["status"] == "inactive": st.info(f"{user['first_name']} {user['last_name']} is already inactive.")
                        if st.button("Deactivate User", type="primary"):
                            run_query("UPDATE users SET status='inactive' WHERE user_id=?", (uid,), commit=True)
                            st.success(f"{user['first_name']} {user['last_name']} deactivated successfully."); st.rerun()

    # ── BUSINESS ──────────────────────────────────────────────────────────
    elif section == "business":
        st.subheader("🏢 Business Profiles")
        cur.execute("""SELECT b.business_id,b.business_name,
                              (u.first_name || ' ' || u.last_name) as owner,u.email
                       FROM businesses b JOIN users u ON b.user_id=u.user_id""")
        df = make_df(cur.fetchall(), cur)
        search = st.text_input("Search business or owner")
        if search and not df.empty:
            df = df[df["business_name"].str.contains(search, case=False) | df["owner"].str.contains(search, case=False)]
        st.dataframe(df, use_container_width=True)
        st.download_button("⬇ Export CSV", df.to_csv(index=False), "businesses.csv", "text/csv", use_container_width=True)

    # ── REACTIVATION REQUESTS ─────────────────────────────────────────────
    elif section == "requests":
        st.subheader("🔔 Reactivation Requests")
        tab1, tab2 = st.tabs(["🕐 Pending", "✅ Reviewed"])

        with tab1:
            cur.execute("""SELECT r.id,r.user_id,r.email,r.message,r.requested_at,
                                  u.first_name,u.last_name,u.status as user_status
                           FROM reactivation_requests r LEFT JOIN users u ON r.user_id=u.user_id
                           WHERE r.status='pending' ORDER BY r.requested_at DESC""")
            rows = cur.fetchall()
            if not rows:
                st.info("🎉 No pending reactivation requests.")
            else:
                st.warning(f"⚠️ {len(rows)} pending request(s)")
                for row in rows:
                    with st.expander(f"📩 {row['first_name']} {row['last_name']} ({row['email']}) — {row['requested_at']}"):
                        st.markdown(f"**User:** {row['first_name']} {row['last_name']}  \n**Email:** {row['email']}  \n**Requested At:** {row['requested_at']}  \n**Reason:** {row['message']}")
                        if row["user_status"] == "active":
                            st.success("✅ User is already activated from Manage Users.")
                            if st.button("✅ Mark as Reviewed", key=f"review_{row['id']}", type="primary", use_container_width=True):
                                run_query("UPDATE reactivation_requests SET status='approved',reviewed_at=datetime('now'),reviewed_by=? WHERE id=?",
                                         (st.session_state.user_id, row["id"]), commit=True)
                                try:
                                    send_email(row["email"], "Account Reactivated ✅",
                                               f"Hello {row['first_name']},\n\nYour account has been reactivated by the admin.\n\nYou can now login.\n\nThank you!")
                                    st.success(f"✅ Request reviewed & email sent to {row['email']}")
                                except: st.success("✅ Request reviewed. (Email notification failed)")
                                st.rerun()
                        else:
                            st.error("⛔ User is still inactive. Please activate from **Manage Users** first.")
                            if st.button("👥 Go to Manage Users", key=f"goto_users_{row['id']}", use_container_width=True):
                                st.session_state.admin_section = "users"; st.rerun()

        with tab2:
            search_name = st.text_input("Search by user's name (first or last name)", key="reviewed_search")
            base_q = """SELECT r.id,r.email,r.message,r.requested_at,r.reviewed_at,
                               u.first_name,u.last_name,
                               (a.first_name || ' ' || a.last_name) as reviewed_by_name
                        FROM reactivation_requests r
                        LEFT JOIN users u ON r.user_id=u.user_id
                        LEFT JOIN users a ON r.reviewed_by=a.user_id
                        WHERE r.status='approved'"""
            cur.execute(base_q + (" AND (u.first_name LIKE ? OR u.last_name LIKE ?) ORDER BY r.reviewed_at DESC" if search_name else " ORDER BY r.reviewed_at DESC"),
                        (f"%{search_name}%", f"%{search_name}%") if search_name else ())
            reviewed_rows = cur.fetchall()
            if not reviewed_rows:
                st.info("No reviewed requests found." if search_name else "No reviewed requests yet.")
            else:
                st.success(f"📋 {len(reviewed_rows)} reviewed request(s)")
                for row in reviewed_rows:
                    with st.expander(f"✅ {row['first_name']} {row['last_name']} ({row['email']})"):
                        c1, c2 = st.columns(2)
                        c1.markdown(f"**User:** {row['first_name']} {row['last_name']}  \n**Requested At:** {row['requested_at']}")
                        c2.markdown(f"**Email:** {row['email']}  \n**Reviewed At:** {row['reviewed_at']}")
                        st.markdown(f"**Reviewed By:** {row['reviewed_by_name']}  \n**Reason:** {row['message']}")

    # ── PROFILE ───────────────────────────────────────────────────────────
    elif section == "profile":
        st.title("👤 Admin Profile")
        cur.execute("SELECT first_name,last_name,email,phone,password FROM users WHERE user_id=?", (st.session_state.user_id,))
        u = cur.fetchone()
        fn = st.text_input("First Name", u["first_name"]); ln = st.text_input("Last Name", u["last_name"])
        em = st.text_input("Email", u["email"]); ph = st.text_input("Phone", u["phone"])
        if st.button("Update Profile", type="primary"):
            run_query("UPDATE users SET first_name=?,last_name=?,email=?,phone=? WHERE user_id=?", (fn, ln, em, ph, st.session_state.user_id), commit=True)
            st.success("Profile updated."); st.rerun()
        st.divider(); st.subheader("🔐 Change Password")
        old_pw = st.text_input("Old Password", type="password", key="ap_old")
        new_pw = st.text_input("New Password", type="password", key="ap_new")
        con_pw = st.text_input("Confirm New Password", type="password", key="ap_con")
        if st.button("Change Password", type="primary"):
            if not all([old_pw, new_pw, con_pw]): st.error("All fields are required.")
            elif hp(old_pw) != u["password"]: st.error("Incorrect old password.")
            elif new_pw != con_pw: st.error("Passwords do not match.")
            else:
                run_query("UPDATE users SET password=? WHERE user_id=?", (hp(new_pw), st.session_state.user_id), commit=True)
                st.success("Password updated.")

    conn.close()