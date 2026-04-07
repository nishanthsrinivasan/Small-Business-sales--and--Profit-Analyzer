import streamlit as st
import hashlib
from db_connection import get_connection

def hash_password(p): return hashlib.sha256(p.encode()).hexdigest()

def register_page():
    _, col, _ = st.columns([1, 2, 1])
    with col:
        if st.button("⬅ Back", type="primary"):
            st.session_state.page = "home"; st.rerun()

        st.subheader("📝 Register")

        first    = st.text_input("First Name")
        last     = st.text_input("Last Name")
        username = st.text_input("Username")
        email    = st.text_input("Email")
        phone    = st.text_input("Phone")
        password = st.text_input("Password", type="password")

        st.divider()
        biz_name = st.text_input("Business Name")

        if st.button("Register", type="primary", use_container_width=True):
            if not all([first, username, email, password]):
                st.error("Please fill all required fields."); return

            conn = get_connection(); cur = conn.cursor()
            cur.execute("SELECT user_id FROM users WHERE username=? OR email=?", (username, email))
            if cur.fetchone():
                st.error("Username or email already exists."); conn.close(); return

            cur.execute("""
                INSERT INTO users (first_name, last_name, username, password, email, phone, role)
                VALUES (?, ?, ?, ?, ?, ?, 'User')
            """, (first, last, username, hash_password(password), email, phone))

            if biz_name :
                cur.execute("INSERT INTO businesses (user_id, business_name, industry) VALUES (?, ?, ?)",
                            (cur.lastrowid, biz_name))

            conn.commit(); conn.close()
            st.success("Registration successful! Redirecting...")
            st.session_state.page = "login"; st.rerun()