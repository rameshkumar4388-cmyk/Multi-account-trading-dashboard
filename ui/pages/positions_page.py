"""
Positions & P&L page — detailed view of all open positions.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from services.aggregation_service import AggregationService
from services.portfolio_service import PortfolioService
from ui.components.exposure_panel import render_fno_summary
from ui.components.positions_table import render_positions_table
from ui.theme import format_inr


def render(
    aggregation: AggregationService,
    portfolio: PortfolioService,
    selected_account: Optional[str] = None,
):
    account_ids = (
        [selected_account]
        if selected_account
        else aggregation._accounts.list_account_ids()
    )

    positions = aggregation.get_combined_positions(account_ids)

    if not positions:
        st.info("No open positions across selected accounts.")
        return

    # ── Quick stats ───────────────────────────────────────────────────
    total_pnl = sum(p.pnl for p in positions)
    day_pnl = sum(p.day_pnl for p in positions)
    long_count = sum(1 for p in positions if p.quantity > 0)
    short_count = sum(1 for p in positions if p.quantity < 0)
    fno_count = sum(1 for p in positions if p.instrument_type in ("FUT", "CE", "PE"))

    c1, c2, c3, c4, c5 = st.columns(5)
    pnl_color = "#3fb950" if total_pnl >= 0 else "#f85149"
    day_color = "#3fb950" if day_pnl >= 0 else "#f85149"
    sign = "+" if total_pnl >= 0 else ""
    day_sign = "+" if day_pnl >= 0 else ""

    with c1:
        st.metric("Total Positions", len(positions))
    with c2:
        st.metric("MTM P&L", f"{sign}₹{total_pnl:,.0f}")
    with c3:
        st.metric("Day P&L", f"{day_sign}₹{day_pnl:,.0f}")
    with c4:
        st.metric("Long / Short", f"{long_count} / {short_count}")
    with c5:
        st.metric("F&O Count", fno_count)

    st.divider()

    # ── Filter by type ─────────────────────────────────────────────────
    type_options = ["All"] + sorted({p.instrument_type for p in positions})
    type_filter = st.radio(
        "Filter by instrument", type_options, horizontal=True, key="pos_type_filter"
    )

    filtered = positions if type_filter == "All" else [
        p for p in positions if p.instrument_type == type_filter
    ]

    # ── All positions table ────────────────────────────────────────────
    render_positions_table(
        filtered,
        show_account_col=len(account_ids) > 1,
        title=f"Open Positions ({type_filter})",
    )

    st.divider()

    # ── F&O detail ─────────────────────────────────────────────────────
    render_fno_summary(positions)

    # ── P&L by underlying chart ────────────────────────────────────────
    underlying_pnl: dict = {}
    for p in positions:
        key = p.underlying or p.symbol
        underlying_pnl[key] = underlying_pnl.get(key, 0) + p.pnl

    if underlying_pnl:
        st.divider()
        sorted_items = sorted(underlying_pnl.items(), key=lambda x: abs(x[1]), reverse=True)[:12]
        labels, values = zip(*sorted_items)
        colors = ["#3fb950" if v >= 0 else "#f85149" for v in values]

        fig = go.Figure(go.Bar(
            x=list(labels),
            y=list(values),
            marker_color=colors,
            text=[f"₹{v:+,.0f}" for v in values],
            textposition="outside",
            textfont=dict(size=10, color="#c9d1d9"),
            hovertemplate="<b>%{x}</b><br>P&L: ₹%{y:+,.0f}<extra></extra>",
        ))
        fig.update_layout(
            title=dict(text="P&L by Underlying", font=dict(color="#c9d1d9", size=13)),
            paper_bgcolor="#161b22",
            plot_bgcolor="#161b22",
            font=dict(color="#c9d1d9"),
            height=300,
            margin=dict(l=40, r=20, t=36, b=60),
            xaxis=dict(showgrid=False, tickangle=-30),
            yaxis=dict(showgrid=True, gridcolor="#21262d", zeroline=True, zerolinecolor="#30363d"),
        )
        st.plotly_chart(fig, use_container_width=True)
