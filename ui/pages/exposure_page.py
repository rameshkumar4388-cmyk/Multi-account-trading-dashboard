"""
Exposure & Risk page — margin usage, instrument exposure, and concentration.
"""
from __future__ import annotations

from typing import Optional

import streamlit as st

from services.aggregation_service import AggregationService
from services.portfolio_service import PortfolioService
from ui.components.charts import render_exposure_bar
from ui.components.exposure_panel import render_fno_summary, render_margin_usage


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

    account_data = aggregation.get_account_breakdown(account_ids)
    exposure = aggregation.get_exposure_breakdown(account_ids)
    positions = aggregation.get_combined_positions(account_ids)
    metrics = aggregation.get_combined_metrics(account_ids)

    # ── Overall risk metrics ───────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    total_assets = metrics.get("total_holdings_value", 0) + metrics.get("available_cash", 0)
    margin_used = metrics.get("used_margin", 0)
    leverage_pct = (margin_used / total_assets * 100) if total_assets else 0.0

    fno_exposure = exposure.get("Futures", 0) + exposure.get("Call Options", 0) + exposure.get("Put Options", 0)
    eq_exposure = exposure.get("Equity Holdings", 0)
    fno_to_eq = (fno_exposure / eq_exposure * 100) if eq_exposure else 0.0

    with c1:
        st.metric("Total Assets", f"₹{total_assets:,.0f}")
    with c2:
        st.metric("Margin Used", f"₹{margin_used:,.0f}")
    with c3:
        st.metric("Leverage %", f"{leverage_pct:.1f}%")
    with c4:
        st.metric("F&O vs Equity", f"{fno_to_eq:.1f}%")

    st.divider()

    # ── Margin bars ────────────────────────────────────────────────────
    render_margin_usage(account_data)

    st.divider()

    # ── Exposure chart ─────────────────────────────────────────────────
    col1, col2 = st.columns([3, 2])
    with col1:
        render_exposure_bar(exposure)
    with col2:
        # Concentration: top 5 holdings by value
        all_holdings = aggregation.get_combined_holdings(account_ids)
        if all_holdings:
            total_hval = sum(h.current_value for h in all_holdings)
            sorted_h = sorted(all_holdings, key=lambda x: -x.current_value)[:5]

            import plotly.graph_objects as go
            labels = [h.symbol for h in sorted_h]
            values = [h.current_value for h in sorted_h]
            others = total_hval - sum(values)
            if others > 0:
                labels.append("Others")
                values.append(others)

            fig = go.Figure(go.Pie(
                labels=labels,
                values=values,
                marker=dict(
                    colors=["#58a6ff", "#3fb950", "#f0883e", "#d2a8ff", "#ffa657", "#6e7681"],
                    line=dict(color="#161b22", width=2),
                ),
                textinfo="label+percent",
                textfont=dict(size=11, color="#e6edf3"),
                hole=0.5,
                hovertemplate="<b>%{label}</b><br>₹%{value:,.0f}<br>%{percent}<extra></extra>",
            ))
            fig.update_layout(
                title=dict(text="Top Holdings Concentration", font=dict(color="#c9d1d9", size=13)),
                paper_bgcolor="#161b22",
                plot_bgcolor="#161b22",
                font=dict(color="#c9d1d9"),
                height=280,
                margin=dict(l=10, r=10, t=36, b=10),
            )
            st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── F&O positions ──────────────────────────────────────────────────
    render_fno_summary(positions)
