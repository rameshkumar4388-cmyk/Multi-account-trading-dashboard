from __future__ import annotations

from datetime import datetime

import streamlit as st

from ui.theme import format_inr, format_pct


def render_header(app_mode: str, net_worth: float, day_pnl: float):
    badge_html = (
        '<span class="badge-live">● LIVE</span>'
        if app_mode == "live"
        else '<span class="badge-mock">◎ DEMO</span>'
    )
    day_color = "#3fb950" if day_pnl >= 0 else "#f85149"
    day_sign = "+" if day_pnl >= 0 else ""

    st.markdown(
        f"""
        <div style="display:flex; align-items:center; justify-content:space-between;
                    padding:10px 0 4px 0; border-bottom:1px solid #30363d; margin-bottom:16px;">
            <div>
                <span style="font-size:1.4rem; font-weight:700; color:#e6edf3;">
                    Portfolio Dashboard
                </span>
                {badge_html}
            </div>
            <div style="text-align:right;">
                <div style="font-size:0.75rem; color:#8b949e;">
                    {datetime.now().strftime("%d %b %Y  %H:%M:%S")}
                </div>
                <div style="font-size:0.85rem; color:#c9d1d9;">
                    Net Worth: <strong style="color:#e6edf3;">{format_inr(net_worth)}</strong>
                    &nbsp;|&nbsp;
                    Day P&L: <strong style="color:{day_color};">{day_sign}{format_inr(day_pnl)}</strong>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
