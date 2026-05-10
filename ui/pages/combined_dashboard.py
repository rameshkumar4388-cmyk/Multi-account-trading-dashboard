"""
Combined dashboard page — aggregates all accounts into a single unified view.
"""
from __future__ import annotations

import streamlit as st

from services.aggregation_service import AggregationService
from ui.components.charts import (
    render_account_bar,
    render_broker_pie,
    render_holdings_treemap,
    render_pnl_waterfall,
    render_sector_pie,
)
from ui.components.holdings_table import render_aggregated_holdings_table
from ui.components.metric_cards import render_combined_metrics, render_second_row_metrics
from ui.components.positions_table import render_positions_table


def render(aggregation: AggregationService):
    metrics = aggregation.get_combined_metrics()
    broker_data = aggregation.get_broker_breakdown()
    sector_data = aggregation.get_sector_breakdown()
    account_data = aggregation.get_account_breakdown()
    aggregated_holdings = aggregation.get_aggregated_holdings()
    positions = aggregation.get_combined_positions()

    # KPI cards
    render_combined_metrics(metrics)
    st.markdown("<div style='margin-top:4px;'></div>", unsafe_allow_html=True)
    render_second_row_metrics(metrics)

    st.divider()

    # Charts row
    col_left, col_right = st.columns(2, gap="medium")
    with col_left:
        render_broker_pie(broker_data)
    with col_right:
        render_sector_pie(sector_data)

    # Account comparison charts
    col_left2, col_right2 = st.columns(2, gap="medium")
    with col_left2:
        render_account_bar(account_data)
    with col_right2:
        render_pnl_waterfall(account_data)

    st.divider()

    # Tabs: Holdings / Positions / Treemap
    tab_hold, tab_pos, tab_tree = st.tabs([
        "Holdings",
        "Open Positions",
        "Holdings Map",
    ])

    with tab_hold:
        render_aggregated_holdings_table(
            aggregated_holdings,
            title="All Holdings (Aggregated)",
        )

    with tab_pos:
        render_positions_table(
            positions,
            show_account_col=True,
            title="All Open Positions",
        )

    with tab_tree:
        render_holdings_treemap(aggregated_holdings)

    # Account breakdown table
    st.divider()
    st.markdown(
        "<div style='font-size:0.95rem; font-weight:600; color:#c9d1d9; margin-bottom:8px;'>"
        "Account-wise Summary</div>",
        unsafe_allow_html=True,
    )

    import pandas as pd
    if account_data:
        df = pd.DataFrame(account_data).rename(columns={
            "display_name": "Account",
            "broker": "Broker",
            "net_worth": "Net Worth",
            "holdings_value": "Holdings",
            "holdings_pnl": "Holdings PnL",
            "positions_pnl": "Positions PnL",
            "day_pnl": "Day PnL",
            "available_cash": "Cash",
            "used_margin": "Margin Used",
        }).drop(columns=["account_id"], errors="ignore")

        def color_val(val):
            if isinstance(val, (int, float)):
                return "color: #3fb950" if val >= 0 else "color: #f85149"
            return ""

        styled = (
            df.style
            .map(color_val, subset=["Holdings PnL", "Positions PnL", "Day PnL"])
            .format({
                "Net Worth": "{:,.0f}",
                "Holdings": "{:,.0f}",
                "Holdings PnL": "{:+,.0f}",
                "Positions PnL": "{:+,.0f}",
                "Day PnL": "{:+,.0f}",
                "Cash": "{:,.0f}",
                "Margin Used": "{:,.0f}",
            })
            .set_properties(**{"background-color": "#161b22", "color": "#e6edf3", "font-size": "13px"})
            .set_table_styles([{"selector": "th", "props": [
                ("background-color", "#21262d"), ("color", "#8b949e"),
                ("font-size", "11px"), ("text-transform", "uppercase"),
            ]}])
        )
        st.dataframe(styled, use_container_width=True, height=180, hide_index=True)
