"""
Per-account dashboard — drills into a single account or shows all accounts side by side.
"""
from __future__ import annotations

from typing import Optional

import streamlit as st

from services.aggregation_service import AggregationService
from services.portfolio_service import PortfolioService
from ui.account_order import sort_account_ids
from ui.components.charts import render_broker_pie, render_sector_pie
from ui.components.holdings_table import render_holdings_table
from ui.components.metric_cards import render_account_metrics
from ui.components.positions_table import render_positions_table


def render(
    aggregation: AggregationService,
    portfolio: PortfolioService,
    selected_account: Optional[str] = None,
):
    account_ids = sort_account_ids(
        aggregation._accounts.list_account_ids(),
        aggregation._accounts._account_configs,
    )

    if not selected_account:
        # Show all accounts as expandable sections
        st.markdown(
            "<div style='font-size:0.95rem; color:#8b949e; margin-bottom:12px;'>"
            "Showing all accounts — select a specific account in the sidebar for a focused view."
            "</div>",
            unsafe_allow_html=True,
        )
        for aid in account_ids:
            _render_single_account(portfolio, aggregation, aid, expanded=(len(account_ids) == 1))
    else:
        if selected_account not in account_ids:
            st.error(f"Account '{selected_account}' not found.")
            return
        _render_single_account(portfolio, aggregation, selected_account, expanded=True)


def _render_single_account(
    portfolio: PortfolioService,
    aggregation: AggregationService,
    account_id: str,
    expanded: bool = True,
):
    summary = portfolio.get_account_summary(account_id)
    if not summary:
        st.warning(f"No data available for account: {account_id}")
        return

    cfg = aggregation._accounts._account_configs.get(account_id)
    broker = cfg.metadata.get("original_broker", summary.broker) if cfg else summary.broker

    with st.expander(
        f"📂 {summary.display_name}  ·  {broker.capitalize()}  ·  {summary.owner}",
        expanded=expanded,
    ):
        render_account_metrics(summary)
        st.markdown("<div style='margin-top:8px;'></div>", unsafe_allow_html=True)

        holdings = portfolio.get_holdings(account_id)
        positions = portfolio.get_positions(account_id)

        tab_hold, tab_pos, tab_charts = st.tabs([
            "📁 Holdings", "📈 Positions", "📊 Charts"
        ])

        with tab_hold:
            render_holdings_table(
                holdings,
                show_account_col=False,
                title=f"{summary.display_name} Holdings",
            )

        with tab_pos:
            render_positions_table(
                positions,
                show_account_col=False,
                title=f"{summary.display_name} Positions",
            )

        with tab_charts:
            col1, col2 = st.columns(2)
            with col1:
                sector_data = aggregation.get_sector_breakdown([account_id])
                render_sector_pie(sector_data)
            with col2:
                # Holdings vs invested comparison
                if holdings:
                    import plotly.graph_objects as go
                    syms = [h.symbol for h in holdings[:10]]
                    invested = [h.invested_value for h in holdings[:10]]
                    current = [h.current_value for h in holdings[:10]]

                    fig = go.Figure()
                    fig.add_trace(go.Bar(
                        name="Invested", x=syms, y=invested,
                        marker_color="#58a6ff",
                    ))
                    fig.add_trace(go.Bar(
                        name="Current", x=syms, y=current,
                        marker_color=["#3fb950" if c >= i else "#f85149"
                                      for c, i in zip(current, invested)],
                    ))
                    fig.update_layout(
                        title=dict(text="Invested vs Current (Top 10)", font=dict(color="#c9d1d9", size=13)),
                        paper_bgcolor="#161b22",
                        plot_bgcolor="#161b22",
                        font=dict(color="#c9d1d9"),
                        height=300,
                        margin=dict(l=40, r=20, t=36, b=60),
                        barmode="group",
                        xaxis=dict(tickangle=-30),
                    )
                    st.plotly_chart(fig, use_container_width=True)
