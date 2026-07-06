"""Entry point: redirects to Login or Dashboard based on session state."""

import streamlit as st

st.set_page_config(page_title="MSME Financial Health Card", layout="wide")

if st.session_state.get("authenticated"):
    st.switch_page("pages/2_Dashboard.py")
else:
    st.switch_page("pages/1_Login.py")
