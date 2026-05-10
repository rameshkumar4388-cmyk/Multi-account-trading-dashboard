from __future__ import annotations

from typing import List

import pandas as pd
import streamlit as st

from schemas.position import Position


def _build_df(positions: List[Position]) -> pd.DataFrame:
    rows = []
    for p in positions:
        rows.append({
            "Symbol": p.tradingsymbol or p.symbol,
            "Type": p.instrument_type,
            "Exchange": p.exchange,
            "Product": p.product,
            "Direction": p.direction,
            "Qty": p.quantity,
            "Avg Price": p.avg_price,
            "LTP": p.ltp,
            "Value": p.value,
            "PnL": p.pnl,
            "Day PnL": p.day_pnl,
            "Expiry": p.expiry or "-",
            "Strike": f"{p.strike:,.0f}" if p.strike else "-",
            "Account": p.account_id,
        })
    return pd.DataFrame(rows)


def render_positions_table(
    positions: List[Position],
    show_account_col: bool = True,
    title: str = "Positions",
    compact: bool = False,
):
    if not positions:
        st.info("No open positions.")
        return

    df = _build_df(positions)
    if not show_account_col:
        df = df.drop(columns=["Account"], errors="ignore")

    total_pnl = df["PnL"].sum()
    day_pnl = df["Day PnL"].sum()
    pnl_color = "#3fb950" if total_pnl >= 0 else "#f85149"
    day_color = "#3fb950" if day_pnl >= 0 else "#f85149"
    pnl_sign = "+" if total_pnl >= 0 else ""
    day_sign = "+" if day_pnl >= 0 else ""

    st.markdown(
        f"""
        <div style="display:flex; justify-content:space-between; align-items:center;
                    margin-bottom:8px;">
            <div style="font-size:0.95rem; font-weight:600; color:#c9d1d9;">{title}</div>
            <div style="font-size:0.82rem; font-weight:600;">
                <span style="color:{pnl_color};">MTM P&L: {pnl_sign}&#8377;{total_pnl:,.0f}</span>
                &nbsp;|&nbsp;
                <span style="color:{day_color};">Day P&L: {day_sign}&#8377;{day_pnl:,.0f}</span>
                &nbsp;|&nbsp;
                <span style="color:#8b949e; font-weight:400;">{len(df)} positions</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    def color_row(val):
        if isinstance(val, (int, float)):
            return "color: #3fb950" if val >= 0 else "color: #f85149"
        return ""

    def color_dir(val):
        if val == "LONG":
            return "color: #3fb950"
        if val == "SHORT":
            return "color: #f85149"
        return ""

    fmt = {
        "Avg Price": "{:,.2f}",
        "LTP": "{:,.2f}",
        "Value": "{:,.0f}",
        "PnL": "{:+,.0f}",
        "Day PnL": "{:+,.0f}",
    }

    styled = (
        df.style
        .map(color_row, subset=["PnL", "Day PnL"])
        .map(color_dir, subset=["Direction"])
        .format(fmt)
        .set_properties(**{"background-color": "#161b22", "color": "#e6edf3", "font-size": "13px"})
        .set_table_styles([{"selector": "th", "props": [
            ("background-color", "#21262d"), ("color", "#8b949e"),
            ("font-size", "11px"), ("text-transform", "uppercase"),
        ]}])
    )

    height = 280 if compact else 380
    st.dataframe(styled, use_container_width=True, height=height, hide_index=True)
