from __future__ import annotations

from typing import List

import pandas as pd
import streamlit as st

from schemas.position import Position
from ui.theme import format_inr


def render_margin_usage(account_data: List[dict]):
    if not account_data:
        return

    st.markdown(
        "<div style='font-size:0.95rem; font-weight:600; color:#c9d1d9; margin-bottom:10px;'>"
        "Margin Usage by Account</div>",
        unsafe_allow_html=True,
    )

    for d in account_data:
        used      = d.get("used_margin", 0)
        net_avail = d.get("net_available", d.get("available_cash", 0))
        total     = used + net_avail          # net_available already includes collateral
        pct       = (used / total * 100) if total > 0 else 0.0
        bar_color = "#f85149" if pct > 75 else ("#f0883e" if pct > 50 else "#3fb950")

        st.markdown(
            f"""
            <div style="margin-bottom:12px;">
                <div style="display:flex; justify-content:space-between;
                            font-size:0.8rem; color:#8b949e; margin-bottom:4px;">
                    <span><strong style="color:#c9d1d9;">{d['display_name']}</strong></span>
                    <span>Used: {format_inr(used)} / Available: {format_inr(net_avail)} ({pct:.1f}%)</span>
                </div>
                <div style="background:#21262d; border-radius:4px; height:8px; overflow:hidden;">
                    <div style="background:{bar_color}; width:{pct:.1f}%; height:100%;
                                border-radius:4px; transition:width 0.3s;"></div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_fno_summary(positions: List[Position]):
    fno = [p for p in positions if p.instrument_type in ("FUT", "CE", "PE")]
    if not fno:
        st.info("No open F&O positions.")
        return

    rows = []
    for p in fno:
        rows.append({
            "Symbol": p.tradingsymbol or p.symbol,
            "Type": p.instrument_type,
            "Underlying": p.underlying,
            "Direction": p.direction,
            "Qty": p.quantity,
            "LTP": p.ltp,
            "Avg": p.avg_price,
            "MTM PnL": p.pnl,
            "Expiry": p.expiry or "-",
            "Strike": f"{p.strike:,.0f}" if p.strike else "-",
            "Lot Size": p.lot_size,
            "Account": p.account_id,
        })

    df = pd.DataFrame(rows)

    total_pnl = sum(p.pnl for p in fno)
    pnl_color = "#3fb950" if total_pnl >= 0 else "#f85149"
    sign = "+" if total_pnl >= 0 else ""

    st.markdown(
        f"""
        <div style="display:flex; justify-content:space-between; align-items:center;
                    margin-bottom:8px;">
            <div style="font-size:0.95rem; font-weight:600; color:#c9d1d9;">F&amp;O Positions</div>
            <div style="color:{pnl_color}; font-weight:600; font-size:0.82rem;">
                MTM P&amp;L: {sign}&#8377;{total_pnl:,.0f} &middot; {len(fno)} positions
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    def color_val(val):
        if isinstance(val, (int, float)):
            return "color: #3fb950" if val >= 0 else "color: #f85149"
        return ""

    def color_dir(val):
        return "color: #3fb950" if val == "LONG" else "color: #f85149"

    styled = (
        df.style
        .map(color_val, subset=["MTM PnL"])
        .map(color_dir, subset=["Direction"])
        .format({"LTP": "{:,.2f}", "Avg": "{:,.2f}", "MTM PnL": "{:+,.0f}"})
        .set_properties(**{"background-color": "#161b22", "color": "#e6edf3", "font-size": "13px"})
        .set_table_styles([{"selector": "th", "props": [
            ("background-color", "#21262d"), ("color", "#8b949e"),
            ("font-size", "11px"), ("text-transform", "uppercase"),
        ]}])
    )
    st.dataframe(styled, use_container_width=True, height=300, hide_index=True)
