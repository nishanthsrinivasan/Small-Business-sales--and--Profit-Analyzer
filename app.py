import streamlit as st
import time

from login import login_page
from register import register_page
from dashboard import dashboard_page
from admin import admin_dashboard_page


# ===============================
# PAGE CONFIG
# ===============================
st.set_page_config(
    page_title="Small Business Sales & Profit Analyzer",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Small Business Sales & Profit Analyzer")
st.divider()


# ===============================
# SESSION VARIABLES
# ===============================
if "page" not in st.session_state:
    st.session_state.page = "home"

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "last_activity" not in st.session_state:
    st.session_state.last_activity = time.time()

# ✅ NEW: Prevent multiple reruns
if "timeout_checked" not in st.session_state:
    st.session_state.timeout_checked = False

SESSION_TIMEOUT = 300


# ===============================
# SESSION TIMEOUT
# ===============================
def check_timeout():

    # ✅ Prevent repeated reruns loop
    if st.session_state.timeout_checked:
        return

    if st.session_state.logged_in:

        now = time.time()
        last = st.session_state.last_activity

        if now - last > SESSION_TIMEOUT:

            st.session_state.logged_in = False
            st.session_state.page = "login"
            st.session_state.timeout_checked = True  # ✅ prevent loop

            st.warning("Session expired. Please login again.")
            st.rerun()

        # update activity
        st.session_state.last_activity = now


check_timeout()


# ===============================
# HOME PAGE
# ===============================
def home_page():

    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:

        st.subheader("Welcome")

        if st.button("🔐 Login", use_container_width=True, type="primary"):
            st.session_state.page = "login"
            st.session_state.timeout_checked = False
            st.rerun()

        if st.button("📝 Register", use_container_width=True, type="primary"):
            st.session_state.page = "register"
            st.session_state.timeout_checked = False
            st.rerun()


# ===============================
# ROUTING
# ===============================
if st.session_state.logged_in:

    st.session_state.timeout_checked = False  # reset flag

    # ROLE BASED REDIRECT
    if st.session_state.role == "Admin":
        admin_dashboard_page()
    else:
        dashboard_page()

else:

    if st.session_state.page == "home":
        home_page()

    elif st.session_state.page == "login":
        login_page()

    elif st.session_state.page == "register":
        register_page()