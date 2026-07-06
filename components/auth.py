"""Hardcoded-credential auth guard, shared across every page except Login itself.

Prototype-only: a single shared username/password baked into source is fine
for a hackathon demo, not for anything real -- see pages/1_Login.py.
"""

from __future__ import annotations

import streamlit as st

DEMO_USERNAME = "admin"
DEMO_PASSWORD = "demo123"


def require_login() -> None:
    """Bounce to the login page if the session isn't authenticated."""
    if not st.session_state.get("authenticated"):
        st.switch_page("pages/1_Login.py")


def render_header(title: str) -> None:
    """Shared page header: title, welcome caption, and a working Logout button.

    Every authenticated page should show this -- a Logout button that only
    exists on some pages would strand a user unable to sign out from the rest.
    """
    col1, col2 = st.columns([8, 2])
    with col1:
        st.title(title)
        st.caption(f"Welcome, {st.session_state.get('username', 'user')}")
    with col2:
        if st.button("Logout"):
            st.session_state["authenticated"] = False
            st.switch_page("pages/1_Login.py")
