"""Hardcoded-credential login -- prototype only, see components/auth.py."""

import streamlit as st

from components.auth import DEMO_PASSWORD, DEMO_USERNAME

st.set_page_config(page_title="Login", layout="centered")


def login_page() -> None:
    st.title("MSME Financial Health Card")
    st.write("Hackathon Prototype")

    username = st.text_input("Username", key="username_input")
    password = st.text_input("Password", type="password", key="password_input")

    login_btn = st.button("Login", width='stretch', type="primary")

    if login_btn:
        if username == DEMO_USERNAME and password == DEMO_PASSWORD:
            st.session_state["authenticated"] = True
            st.session_state["username"] = username
            st.success("Login successful!")
            st.switch_page("pages/2_Dashboard.py")
        else:
            st.error("Invalid credentials")

    with st.expander("Demo Credentials"):
        st.write(f"**Username:** {DEMO_USERNAME}")
        st.write(f"**Password:** {DEMO_PASSWORD}")


if st.session_state.get("authenticated"):
    st.switch_page("pages/2_Dashboard.py")
else:
    login_page()
