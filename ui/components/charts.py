"""
Chart components using Plotly with dark theme.
"""
from __future__ import annotations

from typing import Dict, List

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

_BG = "#161b22"
_PAPER = "#0d1117"
_GRID = "#21262d"
_TEXT = "#c9d1d9"
_FONT = dict(color=_TEXT, family="Inter, Segoe UI, sans-serif", size=12)

_PALETTE = [
    "#58a6ff", "#3fb950", "#f0883e", "#d2a8ff",
    "#ffa657", "#ff7b72", "#79c0ff", "#56d364",
]


def _base_layout(title: str = "", height: int = 320) -> dict:
    return dict(
        title=dict(text=title, font=dict(color=_TEXT, size=13), x=0.01),
        paper_bgcolor=_BG,
        plot_bgcolor=_BG,
        font=_FONT,
        height=height,
        margin=dict(l=40, r=20, t=36, b=36),
        legend=dict(
            bgcolor="#161b22",
            bordercolor="#30363d",
            borderwidth=1,
            font=dict(size=11, color=_TEXT),
        ),
    )


def render_broker_pie(broker_data: List[dict]):
    """Pie chart: net worth split by broker."""
    if not broker_data:
        return
    labels = [d["broker"] for d in broker_data]
    values = [d["net_worth"] for d in broker_data]

    fig = go.Figure(go.Pie(
        labels=labels,
        values=values,
        marker=dict(colors=_PALETTE, line=dict(color=_BG, width=2)),
        textinfo="label+percent",
        textfont=dict(size=11, color="#e6edf3"),
        hovertemplate="<b>%{label}</b><br>₹%{value:,.0f}<br>%{percent}<extra></extra>",
        hole=0.45,
    ))
    fig.update_layout(**_base_layout("Portfolio by Broker", height=300))
    st.plotly_chart(fig, use_container_width=True)


def render_sector_pie(sector_data: List[dict]):
    """Pie chart: holdings value by sector."""
    if not sector_data:
        return
    labels = [d["sector"] for d in sector_data]
    values = [d["value"] for d in sector_data]

    fig = go.Figure(go.Pie(
        labels=labels,
        values=values,
        marker=dict(colors=_PALETTE, line=dict(color=_BG, width=2)),
        textinfo="label+percent",
        textfont=dict(size=11, color="#e6edf3"),
        hovertemplate="<b>%{label}</b><br>₹%{value:,.0f}<br>%{percent}<extra></extra>",
        hole=0.45,
    ))
    fig.update_layout(**_base_layout("Holdings by Sector", height=300))
    st.plotly_chart(fig, use_container_width=True)


def render_exposure_bar(exposure: Dict[str, float]):
    """Horizontal bar: exposure by instrument type."""
    if not exposure:
        return
    items = [(k, v) for k, v in exposure.items() if v > 0]
    if not items:
        return
    labels, values = zip(*items)

    fig = go.Figure(go.Bar(
        y=list(labels),
        x=list(values),
        orientation="h",
        marker=dict(color=_PALETTE[:len(labels)]),
        text=[f"₹{v:,.0f}" for v in values],
        textposition="outside",
        textfont=dict(size=11, color=_TEXT),
        hovertemplate="<b>%{y}</b><br>₹%{x:,.0f}<extra></extra>",
    ))
    fig.update_xaxes(showgrid=True, gridcolor=_GRID, zeroline=False, tickformat=",")
    fig.update_yaxes(showgrid=False)
    fig.update_layout(**_base_layout("Exposure by Instrument Type", height=280))
    st.plotly_chart(fig, use_container_width=True)


def render_account_bar(account_data: List[dict]):
    """Grouped bar: holdings value and P&L per account."""
    if not account_data:
        return

    names = [d["display_name"] for d in account_data]
    holdings = [d["holdings_value"] for d in account_data]
    pnl = [d["holdings_pnl"] for d in account_data]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Holdings Value",
        x=names, y=holdings,
        marker_color="#58a6ff",
        hovertemplate="<b>%{x}</b><br>₹%{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name="P&L",
        x=names, y=pnl,
        marker_color=[("#3fb950" if v >= 0 else "#f85149") for v in pnl],
        hovertemplate="<b>%{x}</b><br>₹%{y:+,.0f}<extra></extra>",
    ))
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(showgrid=True, gridcolor=_GRID, zeroline=True, zerolinecolor="#30363d")
    fig.update_layout(barmode="group", **_base_layout("Account-wise Breakdown", height=320))
    st.plotly_chart(fig, use_container_width=True)


def render_pnl_waterfall(account_data: List[dict]):
    """Waterfall: P&L contribution per account."""
    if not account_data:
        return

    labels = [d["display_name"] for d in account_data] + ["Total"]
    values = [d["holdings_pnl"] + d.get("positions_pnl", 0) for d in account_data]
    total = sum(values)
    values.append(total)

    measures = ["relative"] * (len(values) - 1) + ["total"]
    colors = ["#3fb950" if v >= 0 else "#f85149" for v in values]

    fig = go.Figure(go.Waterfall(
        name="P&L",
        orientation="v",
        measure=measures,
        x=labels,
        y=values,
        connector=dict(line=dict(color="#30363d")),
        increasing=dict(marker=dict(color="#3fb950")),
        decreasing=dict(marker=dict(color="#f85149")),
        totals=dict(marker=dict(color="#58a6ff")),
        text=[f"₹{v:+,.0f}" for v in values],
        textposition="outside",
        textfont=dict(size=10, color=_TEXT),
    ))
    fig.update_yaxes(showgrid=True, gridcolor=_GRID, zeroline=True, zerolinecolor="#30363d")
    fig.update_xaxes(showgrid=False)
    fig.update_layout(**_base_layout("P&L Contribution by Account", height=320))
    st.plotly_chart(fig, use_container_width=True)


def render_holdings_treemap(holdings_data: List[dict]):
    """Treemap: holdings by current value, coloured by P&L %.

    Plotly treemap requires strictly positive values — zero/negative items are
    dropped. Two-level hierarchy (sector → symbol) is used when meaningful
    sector data is present; falls back to a flat layout when all items share
    the same sector (e.g. all "Other"), avoiding a confusing single-bucket view.
    """
    if not holdings_data:
        return

    valid = [d for d in holdings_data if (d.get("current_value") or 0) > 0]
    if not valid:
        st.info("No holdings with positive value to display in treemap.")
        return

    symbols  = [d["symbol"]             for d in valid]
    values   = [d["current_value"]       for d in valid]
    pnl_pcts = [d.get("pnl_pct", 0)     for d in valid]
    sectors  = [d.get("sector", "Other") for d in valid]

    unique_sectors = set(sectors)
    use_hierarchy  = len(unique_sectors) > 1 or next(iter(unique_sectors)) not in ("Other", "Unknown", "")

    _marker = dict(
        colors=pnl_pcts,
        colorscale=[[0, "#f85149"], [0.5, "#21262d"], [1, "#3fb950"]],
        cmid=0, showscale=True,
        colorbar=dict(
            title=dict(text="P&L %", font=dict(color=_TEXT, size=10)),
            tickfont=dict(color=_TEXT, size=10),
        ),
    )
    _text_tmpl = "<b>%{label}</b><br>%{customdata[0]:+.2f}%"
    _hover     = "<b>%{label}</b><br>Value: ₹%{customdata[1]:,.0f}<br>P&L: %{customdata[0]:+.2f}%<extra></extra>"

    if use_hierarchy:
        # Build explicit node list: sector root nodes + symbol leaf nodes.
        # Use prefixed ids (sec:{name}, sym:{symbol}) to avoid collisions when a
        # symbol name happens to match a sector name.
        ids, labels, parents, vals, colors, custom = [], [], [], [], [], []
        for sec in dict.fromkeys(sectors):           # preserve order, deduplicate
            ids.append(f"sec:{sec}"); labels.append(sec)
            parents.append(""); vals.append(0)
            colors.append(0); custom.append((0, 0))
        for sym, sec, val, pct in zip(symbols, sectors, values, pnl_pcts):
            ids.append(f"sym:{sym}"); labels.append(sym)
            parents.append(f"sec:{sec}"); vals.append(val)
            colors.append(pct); custom.append((pct, val))

        fig = go.Figure(go.Treemap(
            ids=ids, labels=labels, parents=parents, values=vals,
            customdata=custom,
            branchvalues="total",
            marker=dict(
                colors=colors,
                colorscale=[[0, "#f85149"], [0.5, "#21262d"], [1, "#3fb950"]],
                cmid=0, showscale=True,
                colorbar=dict(
                    title=dict(text="P&L %", font=dict(color=_TEXT, size=10)),
                    tickfont=dict(color=_TEXT, size=10),
                ),
            ),
            texttemplate=_text_tmpl, textfont=dict(size=11),
            hovertemplate=_hover,
        ))
    else:
        fig = go.Figure(go.Treemap(
            labels=symbols, parents=[""] * len(symbols),
            values=values, customdata=list(zip(pnl_pcts, values)),
            marker=_marker, texttemplate=_text_tmpl,
            textfont=dict(size=11), hovertemplate=_hover,
        ))

    fig.update_layout(**_base_layout("Holdings Treemap (size=value, color=P&L%)", height=420))
    st.plotly_chart(fig, use_container_width=True)
