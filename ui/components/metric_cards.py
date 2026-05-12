from __future__ import annotations

import streamlit as st

from ui.theme import format_inr_plain as format_inr, format_pct


def _metric(label: str, value: float, delta: float = None, prefix: str = "₹", is_pct: bool = False):
    if is_pct:
        val_str = format_pct(value)
        delta_str = format_pct(delta) if delta is not None else None
    else:
        val_str = format_inr(value)
        delta_str = format_inr(delta) if delta is not None else None

    st.metric(label=label, value=val_str, delta=delta_str)


def render_combined_metrics(metrics: dict):
    """Top-level KPI row for the combined dashboard."""
    cols = st.columns(5, gap="small")

    with cols[0]:
        st.metric(
            label="Net Worth",
            value=format_inr(metrics.get("net_worth", 0)),
            delta=None,
        )
    with cols[1]:
        day_pnl = metrics.get("day_pnl", 0)
        st.metric(
            label="Day P&L",
            value=format_inr(day_pnl),
            delta=format_pct(metrics.get("day_pnl_pct", 0)) if "day_pnl_pct" in metrics else None,
        )
    with cols[2]:
        holdings_pnl = metrics.get("holdings_pnl", 0)
        st.metric(
            label="Holdings P&L",
            value=format_inr(holdings_pnl),
            delta=format_pct(metrics.get("holdings_pnl_pct", 0)),
        )
    with cols[3]:
        pos_pnl = metrics.get("positions_pnl", 0)
        st.metric(
            label="Positions P&L",
            value=format_inr(pos_pnl),
        )
    with cols[4]:
        st.metric(
            label="Cash Available",
            value=format_inr(metrics.get("available_cash", 0)),
        )


def render_second_row_metrics(metrics: dict):
    cols = st.columns(4, gap="small")

    with cols[0]:
        st.metric(
            label="Holdings Value",
            value=format_inr(metrics.get("total_holdings_value", 0)),
        )
    with cols[1]:
        st.metric(
            label="Total Invested",
            value=format_inr(metrics.get("total_invested_value", 0)),
        )
    with cols[2]:
        st.metric(
            label="Margin Used",
            value=format_inr(metrics.get("used_margin", 0)),
        )
    with cols[3]:
        st.metric(
            label="Total P&L",
            value=format_inr(metrics.get("total_pnl", 0)),
            delta=format_pct(metrics.get("holdings_pnl_pct", 0)),
        )


def render_account_metrics(summary):
    """KPI cards for a single account summary."""
    cols = st.columns(5, gap="small")

    with cols[0]:
        st.metric("Net Worth", format_inr(summary.net_worth))
    with cols[1]:
        st.metric(
            "Day P&L",
            format_inr(summary.day_pnl),
        )
    with cols[2]:
        st.metric(
            "Holdings P&L",
            format_inr(summary.holdings_pnl),
            delta=format_pct(summary.holdings_pnl_pct),
        )
    with cols[3]:
        st.metric("Positions P&L", format_inr(summary.positions_pnl))
    with cols[4]:
        st.metric("Cash Available", format_inr(summary.available_cash))
