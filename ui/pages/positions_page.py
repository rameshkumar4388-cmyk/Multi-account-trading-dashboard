"""
Positions & P&L — professional derivatives monitoring terminal.

Features:
- Filter bar: account, underlying, instrument type, expiry
- Live summary strip
- Positions grouped by underlying with per-group P&L
- Full flat table for sorting/scanning
- P&L by underlying bar chart
"""
from __future__ import annotations

from collections import defaultdict
from typing import List, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from schemas.position import Position
from services.aggregation_service import AggregationService
from services.portfolio_service import PortfolioService
from ui.theme import format_inr


# ── helpers ───────────────────────────────────────────────────────────

def _type_badge(itype: str) -> str:
    colors = {"FUT": "#58a6ff", "CE": "#3fb950", "PE": "#f85149", "EQ": "#c9d1d9"}
    c = colors.get(itype, "#8b949e")
    return (
        f"<span style='background:{c}22; color:{c}; font-size:0.65rem; font-weight:700;"
        f"padding:1px 6px; border-radius:4px; letter-spacing:0.04em;'>{itype}</span>"
    )


def _dir_badge(qty: int) -> str:
    if qty > 0:
        return "<span style='color:#3fb950; font-weight:700; font-size:0.8rem;'>▲ LONG</span>"
    return "<span style='color:#f85149; font-weight:700; font-size:0.8rem;'>▼ SHORT</span>"


def _pnl_span(val: float) -> str:
    c = "#3fb950" if val >= 0 else "#f85149"
    sign = "+" if val >= 0 else ""
    return f"<span style='color:{c}; font-weight:600;'>{sign}{format_inr(val)}</span>"


# ── filter bar ────────────────────────────────────────────────────────

def _apply_filters(
    positions: List[Position],
    accounts: list,
    account_filter: Optional[str],
    underlying_filter: str,
    type_filter: str,
    expiry_filter: str,
) -> List[Position]:
    out = positions
    if account_filter and account_filter != "All":
        out = [p for p in out if p.account_id == account_filter]
    if underlying_filter != "All":
        out = [p for p in out if (p.underlying or p.symbol) == underlying_filter]
    if type_filter != "All":
        out = [p for p in out if p.instrument_type == type_filter]
    if expiry_filter != "All":
        out = [p for p in out if p.expiry == expiry_filter]
    return out


# ── grouped view ──────────────────────────────────────────────────────

def _render_grouped(positions: List[Position], aggregation: AggregationService):
    """Positions grouped by underlying — primary terminal view."""
    groups: dict = defaultdict(list)
    for p in positions:
        groups[p.underlying or p.symbol].append(p)

    for underlying, pos_list in sorted(groups.items(), key=lambda x: -abs(sum(p.pnl for p in x[1]))):
        group_pnl = sum(p.pnl for p in pos_list)
        group_day = sum(p.day_pnl for p in pos_list)
        pnl_c = "#3fb950" if group_pnl >= 0 else "#f85149"
        day_c = "#3fb950" if group_day >= 0 else "#f85149"
        pnl_sign = "+" if group_pnl >= 0 else ""
        day_sign = "+" if group_day >= 0 else ""
        long_c = sum(1 for p in pos_list if p.quantity > 0)
        short_c = sum(1 for p in pos_list if p.quantity < 0)

        with st.expander(
            f"{underlying}  ·  {len(pos_list)} position(s)  ·  "
            f"MTM {pnl_sign}₹{group_pnl:,.0f}  ·  "
            f"Day {day_sign}₹{group_day:,.0f}  ·  "
            f"L:{long_c}  S:{short_c}",
            expanded=True,
        ):
            rows = []
            for p in sorted(pos_list, key=lambda x: x.instrument_type):
                cfg = aggregation._accounts._account_configs.get(p.account_id)
                acct = cfg.display_name if cfg else p.account_id
                rows.append({
                    "Symbol": p.tradingsymbol or p.symbol,
                    "Type": p.instrument_type,
                    "Dir": "LONG" if p.quantity > 0 else "SHORT",
                    "Qty": p.quantity,
                    "Avg": p.avg_price,
                    "LTP": p.ltp,
                    "MTM PnL": p.pnl,
                    "Day PnL": p.day_pnl,
                    "Product": p.product,
                    "Strike": f"{p.strike:,.0f}" if p.strike else "-",
                    "Expiry": p.expiry or "-",
                    "Lot Size": p.lot_size,
                    "Account": acct,
                })

            df = pd.DataFrame(rows)

            def c_pnl(v):
                return ("color: #3fb950" if isinstance(v, (int, float)) and v >= 0 else "color: #f85149") if isinstance(v, (int, float)) else ""

            def c_dir(v):
                return "color: #3fb950; font-weight:700" if v == "LONG" else "color: #f85149; font-weight:700"

            def c_type(v):
                pal = {"FUT": "#58a6ff", "CE": "#3fb950", "PE": "#f85149", "EQ": "#c9d1d9"}
                return f"color: {pal.get(str(v), '#8b949e')}; font-weight:600"

            styled = (
                df.style
                .map(c_pnl, subset=["MTM PnL", "Day PnL"])
                .map(c_dir, subset=["Dir"])
                .map(c_type, subset=["Type"])
                .format({"Avg": "{:,.2f}", "LTP": "{:,.2f}", "MTM PnL": "{:+,.0f}", "Day PnL": "{:+,.0f}"})
                .set_properties(**{"background-color": "#161b22", "color": "#e6edf3", "font-size": "12.5px"})
                .set_table_styles([{"selector": "th", "props": [
                    ("background-color", "#21262d"), ("color", "#8b949e"),
                    ("font-size", "10.5px"), ("text-transform", "uppercase"), ("padding", "5px 8px"),
                ]}])
            )
            height = 52 + len(rows) * 36
            st.dataframe(styled, use_container_width=True, height=min(height, 320), hide_index=True)


# ── main render ───────────────────────────────────────────────────────

def render(
    aggregation: AggregationService,
    portfolio: PortfolioService,
    selected_account: Optional[str] = None,
):
    account_ids = (
        [selected_account] if selected_account
        else aggregation._accounts.list_account_ids()
    )
    all_positions = aggregation.get_combined_positions(account_ids)

    if not all_positions:
        st.info("No open positions.")
        return

    # ── FILTER BAR ────────────────────────────────────────────────────
    fc1, fc2, fc3, fc4 = st.columns(4, gap="small")

    all_account_ids = aggregation._accounts.list_account_ids()
    acct_labels = {
        aid: (aggregation._accounts._account_configs[aid].display_name
              if aid in aggregation._accounts._account_configs else aid)
        for aid in all_account_ids
    }

    with fc1:
        acct_opts = ["All"] + all_account_ids
        acct_disp = ["All"] + [acct_labels[a] for a in all_account_ids]
        sel_acct_disp = st.selectbox("Account", acct_disp, key="pos_acct_filter")
        if sel_acct_disp == "All":
            acct_filter = "All"
        else:
            idx = acct_disp.index(sel_acct_disp)
            acct_filter = acct_opts[idx]

    underlyings = sorted({p.underlying or p.symbol for p in all_positions if p.underlying})
    with fc2:
        underlying_filter = st.selectbox("Underlying", ["All"] + underlyings, key="pos_ul_filter")

    types = sorted({p.instrument_type for p in all_positions})
    with fc3:
        type_filter = st.selectbox("Instrument Type", ["All"] + types, key="pos_type_filter")

    expiries = sorted({p.expiry for p in all_positions if p.expiry})
    with fc4:
        expiry_filter = st.selectbox("Expiry", ["All"] + expiries, key="pos_expiry_filter")

    filtered = _apply_filters(
        all_positions, all_account_ids,
        acct_filter, underlying_filter, type_filter, expiry_filter,
    )

    # ── LIVE SUMMARY STRIP ────────────────────────────────────────────
    total_pnl = sum(p.pnl for p in filtered)
    day_pnl = sum(p.day_pnl for p in filtered)
    long_c = sum(1 for p in filtered if p.quantity > 0)
    short_c = sum(1 for p in filtered if p.quantity < 0)
    fno_c = sum(1 for p in filtered if p.instrument_type in ("FUT", "CE", "PE"))

    mtm_c = "#3fb950" if total_pnl >= 0 else "#f85149"
    day_c = "#3fb950" if day_pnl >= 0 else "#f85149"
    mtm_sign = "+" if total_pnl >= 0 else ""
    day_sign = "+" if day_pnl >= 0 else ""

    st.markdown(
        f"""
        <div style="background:#161b22; border:1px solid #30363d; border-radius:8px;
                    padding:12px 18px; margin:10px 0; display:flex; gap:24px; align-items:center;
                    flex-wrap:wrap;">
            <div>
                <span style="font-size:0.65rem; color:#6e7681; text-transform:uppercase;
                             letter-spacing:0.06em;">Positions</span>
                <div style="font-size:1.1rem; font-weight:700; color:#e6edf3;">{len(filtered)}</div>
            </div>
            <div style="width:1px; background:#30363d; height:32px;"></div>
            <div>
                <span style="font-size:0.65rem; color:#6e7681; text-transform:uppercase;
                             letter-spacing:0.06em;">MTM P&amp;L</span>
                <div style="font-size:1.1rem; font-weight:700; color:{mtm_c};">
                    {mtm_sign}{format_inr(total_pnl)}
                </div>
            </div>
            <div style="width:1px; background:#30363d; height:32px;"></div>
            <div>
                <span style="font-size:0.65rem; color:#6e7681; text-transform:uppercase;
                             letter-spacing:0.06em;">Day P&amp;L</span>
                <div style="font-size:1.1rem; font-weight:700; color:{day_c};">
                    {day_sign}{format_inr(day_pnl)}
                </div>
            </div>
            <div style="width:1px; background:#30363d; height:32px;"></div>
            <div>
                <span style="font-size:0.65rem; color:#6e7681; text-transform:uppercase;
                             letter-spacing:0.06em;">Long / Short</span>
                <div style="font-size:1.1rem; font-weight:700;">
                    <span style="color:#3fb950;">{long_c}</span>
                    <span style="color:#6e7681;"> / </span>
                    <span style="color:#f85149;">{short_c}</span>
                </div>
            </div>
            <div style="width:1px; background:#30363d; height:32px;"></div>
            <div>
                <span style="font-size:0.65rem; color:#6e7681; text-transform:uppercase;
                             letter-spacing:0.06em;">F&amp;O Positions</span>
                <div style="font-size:1.1rem; font-weight:700; color:#58a6ff;">{fno_c}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.divider()

    # ── VIEW TOGGLE ───────────────────────────────────────────────────
    view_mode = st.radio(
        "View",
        ["Grouped by Underlying", "Flat Table"],
        horizontal=True,
        key="pos_view_mode",
        label_visibility="collapsed",
    )

    if view_mode == "Grouped by Underlying":
        _render_grouped(filtered, aggregation)
    else:
        _render_flat_table(filtered, aggregation)

    # ── P&L BY UNDERLYING ─────────────────────────────────────────────
    st.divider()
    _render_pnl_chart(filtered)


def _render_flat_table(positions: List[Position], aggregation: AggregationService):
    if not positions:
        st.info("No positions match filters.")
        return

    rows = []
    for p in sorted(positions, key=lambda x: abs(x.pnl), reverse=True):
        cfg = aggregation._accounts._account_configs.get(p.account_id)
        acct = cfg.display_name if cfg else p.account_id
        rows.append({
            "Symbol": p.tradingsymbol or p.symbol,
            "Underlying": p.underlying or p.symbol,
            "Type": p.instrument_type,
            "Dir": "LONG" if p.quantity > 0 else "SHORT",
            "Qty": p.quantity,
            "Avg": p.avg_price,
            "LTP": p.ltp,
            "MTM PnL": p.pnl,
            "Day PnL": p.day_pnl,
            "Product": p.product,
            "Strike": f"{p.strike:,.0f}" if p.strike else "-",
            "Expiry": p.expiry or "-",
            "Account": acct,
        })

    df = pd.DataFrame(rows)

    def c_pnl(v):
        if isinstance(v, (int, float)):
            return "color: #3fb950" if v >= 0 else "color: #f85149"
        return ""

    def c_dir(v):
        return "color: #3fb950; font-weight:700" if v == "LONG" else "color: #f85149; font-weight:700"

    def c_type(v):
        pal = {"FUT": "#58a6ff", "CE": "#3fb950", "PE": "#f85149", "EQ": "#c9d1d9"}
        return f"color: {pal.get(str(v), '#8b949e')}; font-weight:600"

    styled = (
        df.style
        .map(c_pnl, subset=["MTM PnL", "Day PnL"])
        .map(c_dir, subset=["Dir"])
        .map(c_type, subset=["Type"])
        .format({"Avg": "{:,.2f}", "LTP": "{:,.2f}", "MTM PnL": "{:+,.0f}", "Day PnL": "{:+,.0f}"})
        .set_properties(**{"background-color": "#161b22", "color": "#e6edf3", "font-size": "12.5px"})
        .set_table_styles([{"selector": "th", "props": [
            ("background-color", "#21262d"), ("color", "#8b949e"),
            ("font-size", "10.5px"), ("text-transform", "uppercase"), ("padding", "6px 8px"),
        ]}])
    )
    height = min(60 + len(rows) * 36, 520)
    st.dataframe(styled, use_container_width=True, height=height, hide_index=True)


def _render_pnl_chart(positions: List[Position]):
    if not positions:
        return

    ul_pnl: dict = defaultdict(float)
    for p in positions:
        ul_pnl[p.underlying or p.symbol] += p.pnl

    if not ul_pnl:
        return

    items = sorted(ul_pnl.items(), key=lambda x: abs(x[1]), reverse=True)[:10]
    labels, values = zip(*items)
    colors = ["#3fb950" if v >= 0 else "#f85149" for v in values]

    fig = go.Figure(go.Bar(
        x=list(labels),
        y=list(values),
        marker_color=colors,
        text=[f"{'+' if v >= 0 else ''}{format_inr(v)}" for v in values],
        textposition="outside",
        textfont=dict(size=10, color="#c9d1d9"),
        hovertemplate="<b>%{x}</b><br>P&L: %{y:+,.0f}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="P&L by Underlying", font=dict(color="#8b949e", size=11)),
        paper_bgcolor="#161b22", plot_bgcolor="#161b22",
        font=dict(color="#c9d1d9"),
        height=280, margin=dict(l=40, r=20, t=36, b=60),
        xaxis=dict(showgrid=False, tickangle=-30),
        yaxis=dict(showgrid=True, gridcolor="#21262d", zeroline=True, zerolinecolor="#30363d"),
    )
    st.plotly_chart(fig, use_container_width=True)
