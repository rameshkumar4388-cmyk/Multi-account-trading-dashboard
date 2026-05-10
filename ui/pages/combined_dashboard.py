"""
Trading Terminal homepage.

Layout priority (top to bottom):
  1. Live combined MTM banner
  2. Account-wise P&L cards
  3. Underlying price monitor
  4. Open positions table (core component)
  5. Margin / Exposure / Instrument breakdown
"""
from __future__ import annotations

import streamlit as st

from services.aggregation_service import AggregationService
from ui.components.account_pnl_cards import render_account_pnl_cards
from ui.components.price_monitor import render_price_monitor
from ui.theme import format_inr, format_pct


# ── helpers ───────────────────────────────────────────────────────────

def _pnl_html(label: str, value: float, sub: str = "") -> str:
    color = "#3fb950" if value >= 0 else "#f85149"
    sign = "+" if value >= 0 else ""
    sub_html = f"<div style='font-size:0.68rem;color:#8b949e;margin-top:1px;'>{sub}</div>" if sub else ""
    return f"""
    <div style="flex:1; text-align:center; padding:0 8px;">
        <div style="font-size:0.65rem; color:#6e7681; text-transform:uppercase;
                    letter-spacing:0.07em; margin-bottom:4px;">{label}</div>
        <div style="font-size:1.55rem; font-weight:700; color:{color}; line-height:1.1;">
            {sign}{format_inr(value)}
        </div>
        {sub_html}
    </div>"""


def _stat_html(label: str, value: str, color: str = "#e6edf3") -> str:
    return f"""
    <div style="flex:1; text-align:center; padding:0 8px;">
        <div style="font-size:0.65rem; color:#6e7681; text-transform:uppercase;
                    letter-spacing:0.07em; margin-bottom:4px;">{label}</div>
        <div style="font-size:1.55rem; font-weight:700; color:{color}; line-height:1.1;">
            {value}
        </div>
    </div>"""


def _sep() -> str:
    return "<div style='width:1px; background:#30363d; margin:4px 0;'></div>"


# ── main render ───────────────────────────────────────────────────────

def render(aggregation: AggregationService, md_service=None):
    metrics = aggregation.get_combined_metrics()
    summaries = aggregation.get_all_summaries()
    positions = aggregation.get_combined_positions()
    exposure = aggregation.get_exposure_breakdown()
    account_data = aggregation.get_account_breakdown()

    # ── 1. LIVE MTM BANNER ────────────────────────────────────────────
    total_pnl = metrics.get("total_pnl", 0)
    day_pnl = metrics.get("day_pnl", 0)
    pos_pnl = metrics.get("positions_pnl", 0)
    hold_pnl = metrics.get("holdings_pnl", 0)
    net_worth = metrics.get("net_worth", 0)
    cash = metrics.get("available_cash", 0)
    margin = metrics.get("used_margin", 0)
    hold_pnl_pct = metrics.get("holdings_pnl_pct", 0)

    banner_color = "#3fb950" if total_pnl >= 0 else "#f85149"
    banner_border = f"border-top:3px solid {banner_color}"

    st.markdown(
        f"""
        <div style="background:#161b22; {banner_border}; border-radius:0 0 10px 10px;
                    padding:16px 20px; margin-bottom:16px;">
            <div style="display:flex; align-items:center; gap:0;">
                {_pnl_html("Total MTM P&L", total_pnl)}
                {_sep()}
                {_pnl_html("Day P&L", day_pnl)}
                {_sep()}
                {_pnl_html("Positions P&L", pos_pnl)}
                {_sep()}
                {_pnl_html("Holdings P&L", hold_pnl, format_pct(hold_pnl_pct))}
                {_sep()}
                {_stat_html("Net Worth", format_inr(net_worth), "#58a6ff")}
                {_sep()}
                {_stat_html("Cash", format_inr(cash), "#c9d1d9")}
                {_sep()}
                {_stat_html("Margin Used", format_inr(margin), "#f0883e")}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── 2. ACCOUNT P&L CARDS ─────────────────────────────────────────
    render_account_pnl_cards(summaries, aggregation._accounts._account_configs)

    st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)

    # ── 3. UNDERLYING PRICE MONITOR ───────────────────────────────────
    if md_service and positions:
        underlyings_seen: list[str] = []
        for p in positions:
            sym = p.underlying or p.symbol
            if sym and sym not in underlyings_seen:
                underlyings_seen.append(sym)
        # Always include key indices
        for idx in ("NIFTY", "BANKNIFTY"):
            if idx not in underlyings_seen:
                underlyings_seen.insert(0, idx)

        render_price_monitor(underlyings_seen[:12], md_service)
        st.markdown("<div style='margin-top:4px;'></div>", unsafe_allow_html=True)

    st.divider()

    # ── 4. OPEN POSITIONS TABLE ───────────────────────────────────────
    _render_positions_terminal(positions, aggregation)

    st.divider()

    # ── 5. MARGIN / EXPOSURE / INSTRUMENT BREAKDOWN ───────────────────
    col_margin, col_exp, col_inst = st.columns(3, gap="medium")

    with col_margin:
        _render_margin_bars(account_data)

    with col_exp:
        _render_exposure_donut(exposure)

    with col_inst:
        _render_instrument_mix(positions)


# ── sub-sections ──────────────────────────────────────────────────────

def _render_positions_terminal(positions, aggregation):
    """Compact, color-coded positions table — the core homepage component."""
    import pandas as pd

    open_pos = [p for p in positions if p.quantity != 0]
    if not open_pos:
        st.markdown(
            "<div style='background:#161b22; border:1px solid #30363d; border-radius:8px;"
            "padding:24px; text-align:center; color:#6e7681;'>No open positions</div>",
            unsafe_allow_html=True,
        )
        return

    total_mtm = sum(p.pnl for p in open_pos)
    day_total = sum(p.day_pnl for p in open_pos)
    long_c = sum(1 for p in open_pos if p.quantity > 0)
    short_c = sum(1 for p in open_pos if p.quantity < 0)
    mtm_color = "#3fb950" if total_mtm >= 0 else "#f85149"
    day_color = "#3fb950" if day_total >= 0 else "#f85149"
    mtm_sign = "+" if total_mtm >= 0 else ""
    day_sign = "+" if day_total >= 0 else ""

    st.markdown(
        f"""
        <div style="display:flex; justify-content:space-between; align-items:center;
                    margin-bottom:10px;">
            <div style="font-size:0.95rem; font-weight:700; color:#c9d1d9;">
                Open Positions
                <span style="font-size:0.72rem; background:#21262d; color:#8b949e;
                             padding:2px 8px; border-radius:10px; margin-left:8px;
                             font-weight:500;">{len(open_pos)} positions</span>
            </div>
            <div style="font-size:0.82rem; display:flex; gap:16px;">
                <span style="color:{mtm_color}; font-weight:600;">
                    MTM {mtm_sign}{format_inr(total_mtm)}
                </span>
                <span style="color:{day_color}; font-weight:600;">
                    Day {day_sign}{format_inr(day_total)}
                </span>
                <span style="color:#8b949e;">
                    L: <strong style="color:#3fb950;">{long_c}</strong>
                    &nbsp;S: <strong style="color:#f85149;">{short_c}</strong>
                </span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    rows = []
    for p in sorted(open_pos, key=lambda x: abs(x.pnl), reverse=True):
        cfg = aggregation._accounts._account_configs.get(p.account_id)
        acct_label = cfg.display_name if cfg else p.account_id
        rows.append({
            "Symbol": p.tradingsymbol or p.symbol,
            "Underlying": p.underlying or p.symbol,
            "Type": p.instrument_type,
            "Product": p.product,
            "Dir": "L" if p.quantity > 0 else "S",
            "Qty": p.quantity,
            "Avg": p.avg_price,
            "LTP": p.ltp,
            "MTM PnL": p.pnl,
            "Day PnL": p.day_pnl,
            "Expiry": p.expiry or "-",
            "Strike": f"{p.strike:,.0f}" if p.strike else "-",
            "Account": acct_label,
        })

    df = pd.DataFrame(rows)

    def color_pnl(val):
        if isinstance(val, (int, float)):
            return "color: #3fb950" if val >= 0 else "color: #f85149"
        return ""

    def color_dir(val):
        if val == "L":
            return "color: #3fb950; font-weight:700"
        if val == "S":
            return "color: #f85149; font-weight:700"
        return ""

    def color_type(val):
        palette = {"FUT": "#58a6ff", "CE": "#3fb950", "PE": "#f85149", "EQ": "#c9d1d9"}
        c = palette.get(str(val), "#8b949e")
        return f"color: {c}; font-weight:600"

    styled = (
        df.style
        .map(color_pnl, subset=["MTM PnL", "Day PnL"])
        .map(color_dir, subset=["Dir"])
        .map(color_type, subset=["Type"])
        .format({
            "Avg": "{:,.2f}",
            "LTP": "{:,.2f}",
            "MTM PnL": "{:+,.0f}",
            "Day PnL": "{:+,.0f}",
        })
        .set_properties(**{
            "background-color": "#161b22",
            "color": "#e6edf3",
            "font-size": "12.5px",
        })
        .set_table_styles([{"selector": "th", "props": [
            ("background-color", "#21262d"), ("color", "#8b949e"),
            ("font-size", "10.5px"), ("text-transform", "uppercase"),
            ("letter-spacing", "0.05em"), ("padding", "6px 8px"),
        ]}])
    )
    st.dataframe(styled, use_container_width=True, height=min(80 + len(rows) * 36, 420), hide_index=True)


def _render_margin_bars(account_data: list):
    st.markdown(
        "<div style='font-size:0.72rem; color:#6e7681; font-weight:600; text-transform:uppercase;"
        "letter-spacing:0.08em; margin-bottom:10px;'>Margin Usage</div>",
        unsafe_allow_html=True,
    )
    for d in account_data:
        used = d.get("used_margin", 0)
        cash = d.get("available_cash", 0)
        total = used + cash
        pct = (used / total * 100) if total > 0 else 0.0
        bar_c = "#f85149" if pct > 75 else ("#f0883e" if pct > 50 else "#3fb950")
        name = d.get("display_name", d.get("account_id", ""))
        st.markdown(
            f"""
            <div style="margin-bottom:10px;">
                <div style="display:flex; justify-content:space-between; font-size:0.72rem;
                            color:#8b949e; margin-bottom:3px;">
                    <span style="color:#c9d1d9; font-weight:600;">{name}</span>
                    <span>{pct:.0f}% used</span>
                </div>
                <div style="background:#21262d; border-radius:3px; height:6px;">
                    <div style="background:{bar_c}; width:{min(pct,100):.0f}%; height:100%;
                                border-radius:3px;"></div>
                </div>
                <div style="display:flex; justify-content:space-between; font-size:0.68rem;
                            color:#6e7681; margin-top:2px;">
                    <span>Used: {format_inr(used)}</span>
                    <span>Free: {format_inr(cash)}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_exposure_donut(exposure: dict):
    import plotly.graph_objects as go

    items = [(k, v) for k, v in exposure.items() if v > 0]
    if not items:
        return

    labels, values = zip(*items)
    palette = ["#58a6ff", "#3fb950", "#f0883e", "#f85149", "#d2a8ff"]

    fig = go.Figure(go.Pie(
        labels=list(labels),
        values=list(values),
        hole=0.55,
        marker=dict(colors=palette[:len(labels)], line=dict(color="#0d1117", width=2)),
        textinfo="label+percent",
        textfont=dict(size=10, color="#c9d1d9"),
        hovertemplate="<b>%{label}</b><br>%{value:,.0f}<br>%{percent}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="Exposure by Type", font=dict(color="#8b949e", size=11), x=0.0),
        paper_bgcolor="#161b22", plot_bgcolor="#161b22",
        font=dict(color="#c9d1d9"),
        height=260, margin=dict(l=0, r=0, t=28, b=0),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_instrument_mix(positions: list):
    """Compact instrument type breakdown table."""
    from collections import defaultdict

    st.markdown(
        "<div style='font-size:0.72rem; color:#6e7681; font-weight:600; text-transform:uppercase;"
        "letter-spacing:0.08em; margin-bottom:8px;'>Instrument Mix</div>",
        unsafe_allow_html=True,
    )

    buckets: dict = defaultdict(lambda: {"count": 0, "pnl": 0.0, "long": 0, "short": 0})
    for p in positions:
        t = p.instrument_type
        buckets[t]["count"] += 1
        buckets[t]["pnl"] += p.pnl
        if p.quantity > 0:
            buckets[t]["long"] += 1
        else:
            buckets[t]["short"] += 1

    type_colors = {"FUT": "#58a6ff", "CE": "#3fb950", "PE": "#f85149", "EQ": "#c9d1d9"}

    for itype, data in sorted(buckets.items(), key=lambda x: -abs(x[1]["pnl"])):
        pnl = data["pnl"]
        pnl_c = "#3fb950" if pnl >= 0 else "#f85149"
        pnl_sign = "+" if pnl >= 0 else ""
        tc = type_colors.get(itype, "#8b949e")
        st.markdown(
            f"""
            <div style="display:flex; justify-content:space-between; align-items:center;
                        background:#21262d; border-radius:6px; padding:8px 12px; margin-bottom:6px;">
                <div style="display:flex; align-items:center; gap:8px;">
                    <span style="background:{tc}22; color:{tc}; font-size:0.7rem; font-weight:700;
                                 padding:2px 7px; border-radius:4px;">{itype}</span>
                    <span style="color:#8b949e; font-size:0.75rem;">
                        {data['count']} pos &nbsp;
                        <span style="color:#3fb950;">L:{data['long']}</span>
                        <span style="color:#f85149;"> S:{data['short']}</span>
                    </span>
                </div>
                <span style="color:{pnl_c}; font-size:0.78rem; font-weight:600;">
                    {pnl_sign}{format_inr(pnl)}
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )
