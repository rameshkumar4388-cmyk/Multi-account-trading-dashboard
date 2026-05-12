from __future__ import annotations

import streamlit as st

from ui.components.market_clock import render_session_badge


def render_header(app_mode: str, net_worth: float = 0, day_pnl: float = 0):
    """
    Minimal top bar: app name + live/demo badge + session status + IST time.
    Portfolio metrics are shown in the terminal page body, not here.
    """
    mode_html = (
        "<span style='background:linear-gradient(135deg,#065f46,#047857);"
        "color:#6ee7b7;font-size:0.62rem;font-weight:700;padding:2px 8px;"
        "border-radius:10px;letter-spacing:0.08em;'>● LIVE</span>"
        if app_mode == "live" else
        "<span style='background:#1c1f3a;color:#454a6e;font-size:0.62rem;"
        "font-weight:700;padding:2px 8px;border-radius:10px;"
        "letter-spacing:0.08em;'>◎ DEMO</span>"
    )

    session = render_session_badge()

    st.markdown(
        f"<div style='display:flex;align-items:center;justify-content:space-between;"
        f"padding:6px 0 10px 0;border-bottom:1px solid #1c1f3a;margin-bottom:14px;'>"
        f"<div style='display:flex;align-items:center;gap:10px;'>"
        f"<span style='font-size:0.95rem;font-weight:700;color:#eef0f8;"
        f"letter-spacing:0.02em;'>Portfolio Terminal</span>"
        f"{mode_html}</div>"
        f"<div>{session}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
