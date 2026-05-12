"""
Holdings — dedicated long-term portfolio analytics page.

All holdings-focused visuals and analytics live here.
The trading terminal homepage does NOT show holdings data.
"""
from __future__ import annotations

from typing import List, Optional

import plotly.graph_objects as go
import streamlit as st

from services.aggregation_service import AggregationService
from services.portfolio_service import PortfolioService
from ui.account_order import sort_account_ids
from ui.components.charts import render_holdings_treemap, render_sector_pie
from ui.components.holdings_table import (
    render_aggregated_holdings_table,
    render_holdings_table,
)
from ui.theme import format_inr, format_pct


def render(
    aggregation: AggregationService,
    portfolio: PortfolioService,
    selected_account: Optional[str] = None,
):
    cfgs = aggregation._accounts._account_configs
    account_ids = (
        [selected_account] if selected_account
        else sort_account_ids(aggregation._accounts.list_account_ids(), cfgs)
    )

    all_holdings = aggregation.get_combined_holdings(account_ids)

    if not all_holdings:
        st.info("No holdings data available.")
        return

    # ── SUMMARY STRIP ─────────────────────────────────────────────────
    total_invested = sum(h.invested_value for h in all_holdings)
    total_current = sum(h.current_value for h in all_holdings)
    total_pnl = sum(h.pnl for h in all_holdings)
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested else 0.0
    day_pnl = sum(h.day_change * h.quantity for h in all_holdings)

    pnl_c = "#3fb950" if total_pnl >= 0 else "#f85149"
    day_c = "#3fb950" if day_pnl >= 0 else "#f85149"
    pnl_sign = "+" if total_pnl >= 0 else ""
    day_sign = "+" if day_pnl >= 0 else ""

    st.markdown(
        f"""
        <div style="background:#161b22; border:1px solid #30363d; border-radius:8px;
                    padding:14px 20px; margin-bottom:16px; display:flex; gap:24px;
                    align-items:center; flex-wrap:wrap;">
            <div>
                <div style="font-size:0.62rem; color:#6e7681; text-transform:uppercase;
                            letter-spacing:0.06em;">Portfolio Value</div>
                <div style="font-size:1.2rem; font-weight:700; color:#58a6ff;">
                    {format_inr(total_current)}
                </div>
            </div>
            <div style="width:1px; background:#30363d; height:32px;"></div>
            <div>
                <div style="font-size:0.62rem; color:#6e7681; text-transform:uppercase;
                            letter-spacing:0.06em;">Total Invested</div>
                <div style="font-size:1.2rem; font-weight:700; color:#c9d1d9;">
                    {format_inr(total_invested)}
                </div>
            </div>
            <div style="width:1px; background:#30363d; height:32px;"></div>
            <div>
                <div style="font-size:0.62rem; color:#6e7681; text-transform:uppercase;
                            letter-spacing:0.06em;">Overall P&amp;L</div>
                <div style="font-size:1.2rem; font-weight:700; color:{pnl_c};">
                    {pnl_sign}{format_inr(total_pnl)}
                    <span style="font-size:0.75rem; margin-left:4px;">
                        ({pnl_sign}{total_pnl_pct:.2f}%)
                    </span>
                </div>
            </div>
            <div style="width:1px; background:#30363d; height:32px;"></div>
            <div>
                <div style="font-size:0.62rem; color:#6e7681; text-transform:uppercase;
                            letter-spacing:0.06em;">Day P&amp;L</div>
                <div style="font-size:1.2rem; font-weight:700; color:{day_c};">
                    {day_sign}{format_inr(day_pnl)}
                </div>
            </div>
            <div style="width:1px; background:#30363d; height:32px;"></div>
            <div>
                <div style="font-size:0.62rem; color:#6e7681; text-transform:uppercase;
                            letter-spacing:0.06em;">Stocks Held</div>
                <div style="font-size:1.2rem; font-weight:700; color:#e6edf3;">
                    {len({h.symbol for h in all_holdings})}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── FILTER CONTROLS ────────────────────────────────────────────────
    fc1, fc2, fc3 = st.columns([2, 2, 1], gap="small")

    with fc1:
        sectors = sorted({h.sector for h in all_holdings if h.sector and h.sector != "Unknown"})
        sector_filter = st.selectbox("Sector", ["All Sectors"] + sectors, key="hold_sector")

    with fc2:
        sort_options = ["Current Value", "P&L (Abs)", "P&L %", "Symbol"]
        sort_by = st.selectbox("Sort by", sort_options, key="hold_sort")

    with fc3:
        view_mode = st.radio("View", ["Aggregated", "Per Account"], horizontal=True, key="hold_view")

    # Apply filters
    if sector_filter != "All Sectors":
        all_holdings = [h for h in all_holdings if h.sector == sector_filter]

    sort_key_map = {
        "Current Value": lambda h: -h.current_value,
        "P&L (Abs)": lambda h: -abs(h.pnl),
        "P&L %": lambda h: -h.pnl_pct,
        "Symbol": lambda h: h.symbol,
    }
    all_holdings = sorted(all_holdings, key=sort_key_map.get(sort_by, lambda h: -h.current_value))

    st.divider()

    # ── CHARTS ROW ─────────────────────────────────────────────────────
    col_l, col_r = st.columns(2, gap="medium")
    with col_l:
        sector_data = aggregation.get_sector_breakdown(account_ids)
        if sector_filter != "All Sectors":
            sector_data = [s for s in sector_data if s["sector"] == sector_filter]
        render_sector_pie(sector_data)

    with col_r:
        _render_top_winners_losers(all_holdings)

    st.divider()

    # ── MAIN TABLE ─────────────────────────────────────────────────────
    if view_mode == "Aggregated":
        aggregated = aggregation.get_aggregated_holdings(account_ids)
        if sector_filter != "All Sectors":
            aggregated = [a for a in aggregated if a.get("sector") == sector_filter]
        sort_agg_map = {
            "Current Value": ("current_value", True),
            "P&L (Abs)": ("pnl", True),
            "P&L %": ("pnl_pct", True),
            "Symbol": ("symbol", False),
        }
        sk, rev = sort_agg_map.get(sort_by, ("current_value", True))
        aggregated = sorted(aggregated, key=lambda x: x.get(sk, 0), reverse=rev)
        render_aggregated_holdings_table(aggregated, title="Portfolio Holdings (Aggregated)")

        st.divider()
        render_holdings_treemap(aggregated)

    else:
        for aid in account_ids:
            holdings = portfolio.get_holdings(aid)
            if sector_filter != "All Sectors":
                holdings = [h for h in holdings if h.sector == sector_filter]
            holdings = sorted(holdings, key=sort_key_map.get(sort_by, lambda h: -h.current_value))
            cfg = aggregation._accounts._account_configs.get(aid)
            name = cfg.display_name if cfg else aid
            render_holdings_table(holdings, show_account_col=False, title=f"{name}")
            st.markdown("<div style='margin-top:12px;'></div>", unsafe_allow_html=True)

    # ── ACCOUNT-WISE HOLDINGS COMPARISON ──────────────────────────────
    if not selected_account:
        st.divider()
        _render_account_comparison(aggregation, account_ids)


def _render_top_winners_losers(holdings):
    """Horizontal bar chart of top gainers and losers."""
    if not holdings:
        return

    sorted_by_pnl = sorted(holdings, key=lambda h: h.pnl, reverse=True)
    top5 = sorted_by_pnl[:5]
    bot5 = sorted_by_pnl[-5:][::-1]
    combined = top5 + bot5

    labels = [h.symbol for h in combined]
    values = [h.pnl for h in combined]
    colors = ["#3fb950" if v >= 0 else "#f85149" for v in values]

    fig = go.Figure(go.Bar(
        y=labels, x=values, orientation="h",
        marker_color=colors,
        text=[f"{'+' if v >= 0 else ''}{format_inr(v)}" for v in values],
        textposition="outside",
        textfont=dict(size=9, color="#c9d1d9"),
        hovertemplate="<b>%{y}</b><br>P&L: %{x:+,.0f}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="Top Gainers & Losers", font=dict(color="#8b949e", size=11)),
        paper_bgcolor="#161b22", plot_bgcolor="#161b22",
        font=dict(color="#c9d1d9"),
        height=300, margin=dict(l=10, r=60, t=28, b=10),
        xaxis=dict(showgrid=True, gridcolor="#21262d", zeroline=True, zerolinecolor="#30363d"),
        yaxis=dict(showgrid=False, autorange="reversed"),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_account_comparison(aggregation: AggregationService, account_ids: List[str]):
    """Side-by-side invested vs current value per account."""
    summaries = aggregation.get_all_summaries(account_ids)
    if not summaries:
        return

    st.markdown(
        "<div style='font-size:0.72rem; color:#6e7681; font-weight:600; text-transform:uppercase;"
        "letter-spacing:0.08em; margin-bottom:10px;'>Account Holdings Comparison</div>",
        unsafe_allow_html=True,
    )

    names = [s.display_name for s in summaries]
    invested = [s.total_invested_value for s in summaries]
    current = [s.total_holdings_value for s in summaries]
    pnl = [s.holdings_pnl for s in summaries]

    fig = go.Figure()
    fig.add_trace(go.Bar(name="Invested", x=names, y=invested, marker_color="#58a6ff",
                         hovertemplate="<b>%{x}</b><br>Invested: %{y:,.0f}<extra></extra>"))
    fig.add_trace(go.Bar(name="Current", x=names, y=current,
                         marker_color=["#3fb950" if c >= i else "#f85149" for c, i in zip(current, invested)],
                         hovertemplate="<b>%{x}</b><br>Current: %{y:,.0f}<extra></extra>"))

    fig.update_layout(
        barmode="group",
        paper_bgcolor="#161b22", plot_bgcolor="#161b22",
        font=dict(color="#c9d1d9"),
        height=280, margin=dict(l=40, r=20, t=16, b=40),
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="#21262d"),
        legend=dict(bgcolor="#21262d", bordercolor="#30363d", borderwidth=1),
    )
    st.plotly_chart(fig, use_container_width=True)
