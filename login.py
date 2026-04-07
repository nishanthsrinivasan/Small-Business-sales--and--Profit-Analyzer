import hashlib
import random
import smtplib
import sqlite3
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText

import streamlit as st

from db_connection import get_connection

ADMIN_SECRET = "MySuper$ecret2025"
EMAIL_SENDER = "business.analyzer167@gmail.com"
EMAIL_PASSWORD = "qoqzunpymhbmlxzw"


def hp(password):
    return hashlib.sha256(password.encode()).hexdigest()


def db_query(query, params=(), fetch=False, fetch_all=False, commit=False, retries=5):
    for _ in range(retries):
        conn = None
        try:
            conn = get_connection()
            if conn is None:
                raise Exception("Database connection failed.")

            cur = conn.cursor()
            cur.execute(query, params)

            if commit:
                conn.commit()
                return cur.lastrowid

            if fetch_all:
                return [dict(row) for row in cur.fetchall()]

            if fetch:
                row = cur.fetchone()
                return dict(row) if row else None

            return None

        except sqlite3.OperationalError as e:
            if conn:
                conn.rollback()
            if "locked" in str(e).lower() or "busy" in str(e).lower():
                time.sleep(0.4)
                continue
            raise

        finally:
            if conn:
                conn.close()

    raise Exception("Database is busy. Please try again.")


def safe_log_login(user_id):
    try:
        return db_query(
            "INSERT INTO login_history (user_id) VALUES (?)",
            (user_id,),
            commit=True,
            retries=2,
        )
    except Exception:
        return None


def send_otp(email, otp):
    msg = MIMEText(f"Your OTP: {otp}\nExpires in 10 minutes.")
    msg["Subject"] = "Password Reset OTP"
    msg["From"] = EMAIL_SENDER
    msg["To"] = email

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)
        smtp.sendmail(EMAIL_SENDER, email, msg.as_string())


def generate_otp(email):
    user = db_query("SELECT user_id FROM users WHERE email=?", (email,), fetch=True)
    if not user:
        return False, "No account found with this email."

    otp = str(random.randint(100000, 999999))
    expiry = (datetime.now() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")

    db_query(
        "UPDATE users SET otp_code=?, otp_expiry=? WHERE email=?",
        (otp, expiry, email),
        commit=True,
    )

    send_otp(email, otp)
    return True, "OTP sent to your email."


def verify_otp(email, otp):
    row = db_query(
        "SELECT otp_code, otp_expiry FROM users WHERE email=?",
        (email,),
        fetch=True,
    )

    if not row:
        return False, "Email not found."
    if not row["otp_code"] or row["otp_code"] != otp:
        return False, "Incorrect OTP."
    if not row["otp_expiry"]:
        return False, "OTP not found. Request a new one."

    if datetime.now() > datetime.strptime(row["otp_expiry"], "%Y-%m-%d %H:%M:%S"):
        return False, "OTP expired. Request a new one."

    return True, "OTP verified."


def reset_password(email, password):
    db_query(
        "UPDATE users SET password=?, otp_code=NULL, otp_expiry=NULL WHERE email=?",
        (hp(password), email),
        commit=True,
    )


def clear_forgot():
    st.session_state.otp_sent = False
    st.session_state.otp_verified = False
    st.session_state.forgot_email = ""
    st.session_state.login_view = "login"


def submit_reactivation(email, message):
    user = db_query(
        "SELECT user_id, status FROM users WHERE email=?",
        (email,),
        fetch=True,
    )

    if not user:
        return False, "No account found with this email."
    if user["status"] == "active":
        return False, "Your account is already active. Try logging in."

    pending = db_query(
        "SELECT id FROM reactivation_requests WHERE user_id=? AND status='pending'",
        (user["user_id"],),
        fetch=True,
    )
    if pending:
        return False, "You already have a pending request."

    db_query(
        "INSERT INTO reactivation_requests (user_id, email, message, status) VALUES (?, ?, ?, 'pending')",
        (user["user_id"], email, message),
        commit=True,
    )
    return True, "Request submitted! Admin will review."


def init_login_state():
    defaults = {
        "otp_sent": False,
        "otp_verified": False,
        "forgot_email": "",
        "deactivated_email": "",
        "show_deactivated_msg": False,
        "login_view": "login",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def do_login(identifier, password, is_admin, secret):
    if not identifier or not password:
        st.error("Please fill all fields.")
        return

    if is_admin and secret != ADMIN_SECRET:
        st.error("Invalid admin secret code.")
        return

    user = db_query(
        """
        SELECT user_id, first_name, last_name, username, email, phone, role, status
        FROM users
        WHERE (username=? OR email=?) AND password=? AND role=?
        """,
        (identifier, identifier, hp(password), "Admin" if is_admin else "User"),
        fetch=True,
    )

    if not user:
        st.error("Invalid credentials or role.")
        return

    if user["status"] != "active":
        st.session_state.show_deactivated_msg = True
        st.session_state.deactivated_email = user["email"]
        st.session_state.login_view = "reactivation"
        return

    login_id = safe_log_login(user["user_id"])

    st.session_state.update({
        "logged_in": True,
        "login_id": login_id,
        "user_id": user["user_id"],
        "first_name": user["first_name"],
        "last_name": user["last_name"],
        "username": user["username"],
        "email": user["email"],
        "phone": user["phone"],
        "role": user["role"],
        "page": "admin_dashboard" if is_admin else "dashboard",
    })

    st.success("Login successful!")
    st.rerun()


def forgot_password_page():
    st.subheader("Forgot Password")

    if st.button("Back to Login", type="primary", key="forgot_back"):
        clear_forgot()
        st.rerun()

    email = st.text_input(
        "Registered Email",
        value=st.session_state.forgot_email,
        key="forgot_email_input",
    )
    st.session_state.forgot_email = email

    if not st.session_state.otp_sent:
        if st.button("Send OTP", use_container_width=True):
            ok, msg = generate_otp(email)
            if ok:
                st.session_state.otp_sent = True
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
        return

    otp = st.text_input("Enter OTP", key="forgot_otp")

    if not st.session_state.otp_verified:
        c1, c2 = st.columns(2)

        with c1:
            if st.button("Verify OTP", use_container_width=True):
                ok, msg = verify_otp(email, otp)
                if ok:
                    st.session_state.otp_verified = True
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

        with c2:
            if st.button("Resend OTP", use_container_width=True):
                ok, msg = generate_otp(email)
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)
        return

    new_password = st.text_input("New Password", type="password", key="new_pw")
    confirm_password = st.text_input("Confirm Password", type="password", key="confirm_pw")

    if st.button("Reset Password", type="primary", use_container_width=True):
        if not new_password or not confirm_password:
            st.error("Please fill all fields.")
        elif new_password != confirm_password:
            st.error("Passwords do not match.")
        else:
            reset_password(email, new_password)
            st.success("Password reset successful.")
            clear_forgot()
            st.rerun()


def reactivation_page():
    st.subheader("Account Reactivation")

    if st.button("Back to Login", type="primary", key="reactivation_back"):
        st.session_state.login_view = "login"
        st.session_state.show_deactivated_msg = False
        st.rerun()

    email = st.text_input(
        "Inactive Account Email",
        value=st.session_state.deactivated_email,
        key="reactivation_email",
    )
    message = st.text_area("Why should your account be reactivated?", key="reactivation_msg")

    if st.button("Submit Reactivation Request", type="primary", use_container_width=True):
        if not email or not message.strip():
            st.error("Please enter email and message.")
            return

        ok, msg = submit_reactivation(email, message.strip())
        if ok:
            st.success(msg)
            st.session_state.show_deactivated_msg = False
            st.session_state.login_view = "login"
        else:
            st.error(msg)


def login_page():
    init_login_state()

    _, col, _ = st.columns([1, 2, 1])

    with col:
        if st.session_state.login_view == "forgot":
            forgot_password_page()
            return

        if st.session_state.login_view == "reactivation":
            reactivation_page()
            return

        if st.button("Back", type="primary", key="login_back"):
            st.session_state.page = "home"
            st.rerun()

        st.subheader("Login")

        identifier = st.text_input("Email or Username")
        password = st.text_input("Password", type="password")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Forgot Password?", use_container_width=True):
                st.session_state.login_view = "forgot"
                st.rerun()

        with c2:
            if st.session_state.show_deactivated_msg:
                if st.button("Request Reactivation", use_container_width=True):
                    st.session_state.login_view = "reactivation"
                    st.rerun()

        st.divider()

        is_admin = st.checkbox("Login as Admin")
        secret = st.text_input("Admin Secret Code", type="password") if is_admin else ""

        if st.button("Login", type="primary", use_container_width=True):
            try:
                do_login(identifier, password, is_admin, secret)
            except Exception as e:
                st.error(str(e))
