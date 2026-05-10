"""
Live underlying price monitor.

Renders a compact ticker-grid of all stocks/indices that have active
F&O or intraday positions.  Prices are read directly from MarketDataService
so they update on every Streamlit rerun (auto-refresh).
"""
from __future__ import annotations

import textwrap
from typing import List

import streamlit as st


def render_price_monitor(underlyings: List[str], md_service, title: str = "Underlying Prices"):
    if not underlyings:
        return

    st.markdown(
        f"<div style='font-size:0.72rem;color:#6e7681;font-weight:600;"
        f"text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px;'>{title}</div>",
        unsafe_allow_html=True,
    )

    cols = st.columns(len(underlyings), gap="small")
    for col, sym in zip(cols, underlyings):
        ltp = md_service.get_ltp(sym) or 0.0
        change = md_service.get_change(sym) or 0.0
        change_pct = md_service.get_change_pct(sym) or 0.0

        color = "#3fb950" if change >= 0 else "#f85149"
        arrow = "&#9650;" if change >= 0 else "&#9660;"
        sign = "+" if change >= 0 else ""

        html = textwrap.dedent(f"""
<div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:10px 12px;text-align:center;border-top:2px solid {color};">
<div style="font-size:0.7rem;color:#8b949e;font-weight:600;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px;">{sym}</div>
<div style="font-size:1.15rem;font-weight:700;color:#e6edf3;line-height:1.2;">{ltp:,.2f}</div>
<div style="font-size:0.72rem;color:{color};font-weight:600;margin-top:3px;">{arrow} {sign}{change:,.2f} ({sign}{change_pct:.2f}%)</div>
</div>
        """).strip()

        with col:
            st.markdown(html, unsafe_allow_html=True)
