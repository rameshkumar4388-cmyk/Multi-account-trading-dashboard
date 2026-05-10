from __future__ import annotations

from typing import List, Optional

import pandas as pd
import streamlit as st

from schemas.holding import Holding
from ui.theme import color_pnl


def _build_df(holdings: List[Holding]) -> pd.DataFrame:
    rows = []
    for h in holdings:
        rows.append({
            "Symbol": h.symbol,
            "Exchange": h.exchange,
            "Sector": h.sector,
            "Qty": h.quantity,
            "Avg Price": h.avg_price,
            "LTP": h.ltp,
            "Invested": h.invested_value,
            "Current": h.current_value,
            "PnL": h.pnl,
            "PnL Pct": h.pnl_pct,
            "Day Chg Pct": h.day_change_pct,
            "Account": h.account_id,
        })
    return pd.DataFrame(rows)


def _style_df(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    def color_val(val):
        if isinstance(val, (int, float)):
            return "color: #3fb950" if val >= 0 else "color: #f85149"
        return ""

    return (
        df.style
        .map(color_val, subset=["PnL", "PnL Pct", "Day Chg Pct"])
        .format({
            "Avg Price": "{:,.2f}",
            "LTP": "{:,.2f}",
            "Invested": "{:,.0f}",
            "Current": "{:,.0f}",
            "PnL": "{:+,.0f}",
            "PnL Pct": "{:+.2f}%",
            "Day Chg Pct": "{:+.2f}%",
        })
        .set_properties(**{
            "background-color": "#161b22",
            "color": "#e6edf3",
            "font-size": "13px",
        })
        .set_table_styles([{
            "selector": "th",
            "props": [
                ("background-color", "#21262d"),
                ("color", "#8b949e"),
                ("font-size", "11px"),
                ("text-transform", "uppercase"),
            ],
        }])
    )


def render_holdings_table(
    holdings: List[Holding],
    show_account_col: bool = True,
    title: str = "Holdings",
    compact: bool = False,
):
    if not holdings:
        st.info("No holdings data available.")
        return

    df = _build_df(holdings)
    if not show_account_col:
        df = df.drop(columns=["Account"], errors="ignore")

    total_invested = df["Invested"].sum()
    total_current = df["Current"].sum()
    total_pnl = df["PnL"].sum()
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested else 0.0

    pnl_color = "#3fb950" if total_pnl >= 0 else "#f85149"
    sign = "+" if total_pnl >= 0 else ""

    st.markdown(
        f"""
        <div style="display:flex; justify-content:space-between; align-items:center;
                    margin-bottom:8px;">
            <div style="font-size:0.95rem; font-weight:600; color:#c9d1d9;">{title}</div>
            <div style="font-size:0.82rem; color:{pnl_color}; font-weight:600;">
                Total P&L: {sign}&#8377;{total_pnl:,.0f} ({sign}{total_pnl_pct:.2f}%)
                &nbsp;|&nbsp;
                <span style="color:#8b949e; font-weight:400;">
                    {len(df)} stocks &nbsp;&middot;&nbsp; &#8377;{total_current:,.0f} current value
                </span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    height = 300 if compact else 420
    styled = _style_df(df)
    st.dataframe(styled, use_container_width=True, height=height, hide_index=True)


def render_aggregated_holdings_table(aggregated: List[dict], title: str = "Combined Holdings"):
    if not aggregated:
        st.info("No holdings data.")
        return

    rows = []
    for a in aggregated:
        rows.append({
            "Symbol": a["symbol"],
            "Exchange": a["exchange"],
            "Sector": a["sector"],
            "Total Qty": a["quantity"],
            "Avg Price": a.get("avg_price", 0),
            "LTP": a.get("ltp", 0),
            "Invested": a["invested_value"],
            "Current": a["current_value"],
            "PnL": a["pnl"],
            "PnL Pct": a.get("pnl_pct", 0),
            "Accounts": len(a.get("accounts", [])),
        })

    df = pd.DataFrame(rows)

    total_invested = df["Invested"].sum()
    total_current = df["Current"].sum()
    total_pnl = df["PnL"].sum()
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested else 0.0
    pnl_color = "#3fb950" if total_pnl >= 0 else "#f85149"
    sign = "+" if total_pnl >= 0 else ""

    st.markdown(
        f"""
        <div style="display:flex; justify-content:space-between; align-items:center;
                    margin-bottom:8px;">
            <div style="font-size:0.95rem; font-weight:600; color:#c9d1d9;">{title}</div>
            <div style="font-size:0.82rem; color:{pnl_color}; font-weight:600;">
                Total P&L: {sign}&#8377;{total_pnl:,.0f} ({sign}{total_pnl_pct:.2f}%)
                &nbsp;|&nbsp;
                <span style="color:#8b949e; font-weight:400;">
                    {len(df)} unique symbols &nbsp;&middot;&nbsp; &#8377;{total_current:,.0f} total
                </span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    def color_val(val):
        if isinstance(val, (int, float)):
            return "color: #3fb950" if val >= 0 else "color: #f85149"
        return ""

    styled = (
        df.style
        .map(color_val, subset=["PnL", "PnL Pct"])
        .format({
            "Avg Price": "{:,.2f}",
            "LTP": "{:,.2f}",
            "Invested": "{:,.0f}",
            "Current": "{:,.0f}",
            "PnL": "{:+,.0f}",
            "PnL Pct": "{:+.2f}%",
        })
        .set_properties(**{"background-color": "#161b22", "color": "#e6edf3", "font-size": "13px"})
        .set_table_styles([{"selector": "th", "props": [
            ("background-color", "#21262d"), ("color", "#8b949e"),
            ("font-size", "11px"), ("text-transform", "uppercase"),
        ]}])
    )

    st.dataframe(styled, use_container_width=True, height=420, hide_index=True)
