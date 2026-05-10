"""
Holdings analysis page — full-screen holdings view with filtering.
"""
from __future__ import annotations

from typing import List, Optional

import pandas as pd
import streamlit as st

from services.aggregation_service import AggregationService
from services.portfolio_service import PortfolioService
from ui.components.charts import render_holdings_treemap, render_sector_pie
from ui.components.holdings_table import (
    render_aggregated_holdings_table,
    render_holdings_table,
)
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

    # ── Filters ───────────────────────────────────────────────────────
    fcol1, fcol2, fcol3 = st.columns([2, 2, 1])
    with fcol1:
        sector_options = ["All Sectors"]
        all_h = aggregation.get_combined_holdings(account_ids)
        sectors = sorted({h.sector for h in all_h if h.sector != "Unknown"})
        sector_options.extend(sectors)
        sector_filter = st.selectbox("Sector", sector_options, key="holdings_sector_filter")

    with fcol2:
        sort_options = ["Current Value ↓", "P&L ↓", "P&L % ↓", "Symbol ↑"]
        sort_by = st.selectbox("Sort by", sort_options, key="holdings_sort")

    with fcol3:
        show_mode = st.radio("View", ["Aggregated", "Per Account"], horizontal=True, key="holdings_view")

    # ── Apply sector filter ───────────────────────────────────────────
    if sector_filter != "All Sectors":
        all_h = [h for h in all_h if h.sector == sector_filter]

    # ── Aggregated view ───────────────────────────────────────────────
    if show_mode == "Aggregated":
        aggregated = aggregation.get_aggregated_holdings(account_ids)
        if sector_filter != "All Sectors":
            aggregated = [a for a in aggregated if a.get("sector") == sector_filter]

        # Sort
        sort_map = {
            "Current Value ↓": ("current_value", True),
            "P&L ↓": ("pnl", True),
            "P&L % ↓": ("pnl_pct", True),
            "Symbol ↑": ("symbol", False),
        }
        key, reverse = sort_map.get(sort_by, ("current_value", True))
        aggregated = sorted(aggregated, key=lambda x: x.get(key, 0), reverse=reverse)

        render_aggregated_holdings_table(aggregated, title="Combined Holdings")

        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            render_sector_pie(aggregation.get_sector_breakdown(account_ids))
        with col2:
            render_holdings_treemap(aggregated)

    else:
        # Per-account view
        for aid in account_ids:
            holdings = portfolio.get_holdings(aid)
            if sector_filter != "All Sectors":
                holdings = [h for h in holdings if h.sector == sector_filter]

            sort_map = {
                "Current Value ↓": lambda h: -h.current_value,
                "P&L ↓": lambda h: -h.pnl,
                "P&L % ↓": lambda h: -h.pnl_pct,
                "Symbol ↑": lambda h: h.symbol,
            }
            holdings = sorted(holdings, key=sort_map.get(sort_by, lambda h: -h.current_value))

            cfg = aggregation._accounts._account_configs.get(aid)
            name = cfg.display_name if cfg else aid
            render_holdings_table(
                holdings,
                show_account_col=False,
                title=f"{name} Holdings",
            )
            st.markdown("<div style='margin-top:8px;'></div>", unsafe_allow_html=True)
