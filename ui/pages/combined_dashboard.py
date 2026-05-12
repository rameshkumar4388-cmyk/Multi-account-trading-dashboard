"""
Trading Terminal — homepage.

Layout (top → bottom):
  1. NIFTY 50 + BANKNIFTY large index cards  (full width, 2 columns)
  2. Combined summary bar                    (5 semantic metrics)
  3. Account-wise cards                      (vertical stack per account)
  4. Active underlyings per account          (chips/tags with LTP)
  5. Open positions table                    (terminal-grade)
"""
from __future__ import annotations

from collections import defaultdict
from typing import List, Optional

import streamlit as st

from services.aggregation_service import AggregationService
from ui.components.account_pnl_cards import render_account_pnl_cards
from ui.theme import C, format_inr, format_pct, signed_color


# ── helpers ───────────────────────────────────────────────────────────

def _pnl_cell(label: str, value: float, sub: str = "") -> str:
    color = signed_color(value)
    sign  = "+" if value > 0 else ""
    sub_h = (
        f"<div style='font-size:0.62rem;color:{C['text_3']};margin-top:2px;'>{sub}</div>"
        if sub else ""
    )
    return (
        f"<div style='flex:1;text-align:center;padding:0 10px;'>"
        f"<div style='font-size:0.58rem;color:{C['text_3']};text-transform:uppercase;"
        f"letter-spacing:0.09em;font-weight:600;margin-bottom:5px;'>{label}</div>"
        f"<div style='font-size:1.35rem;font-weight:700;color:{color};"
        f"font-family:\"JetBrains Mono\",monospace;line-height:1.1;'>"
        f"{sign}{format_inr(value)}</div>{sub_h}</div>"
    )


def _stat_cell(label: str, value: str, color: str = None) -> str:
    color = color or C["text_2"]
    return (
        f"<div style='flex:1;text-align:center;padding:0 10px;'>"
        f"<div style='font-size:0.58rem;color:{C['text_3']};text-transform:uppercase;"
        f"letter-spacing:0.09em;font-weight:600;margin-bottom:5px;'>{label}</div>"
        f"<div style='font-size:1.35rem;font-weight:700;color:{color};"
        f"font-family:\"JetBrains Mono\",monospace;line-height:1.1;'>{value}</div></div>"
    )


def _vdiv() -> str:
    return f"<div style='width:1px;background:{C['border']};margin:6px 0;flex-shrink:0;'></div>"


# ── index cards ───────────────────────────────────────────────────────

def _render_index_cards(md_service):
    """Large NIFTY 50 and BANKNIFTY cards with live LTP."""
    indices = [("NIFTY", "NSE:NIFTY 50"), ("BANKNIFTY", "NSE:NIFTY BANK")]
    cols = st.columns(2, gap="medium")

    for col, (label, _) in zip(cols, indices):
        # Try both key variants the quote feed may use
        ltp = md_service.get_ltp(label) or 0.0
        chg = md_service.get_change(label) or 0.0
        pct = md_service.get_change_pct(label) or 0.0

        color   = C["positive"] if chg >= 0 else C["negative"]
        arrow   = "&#9650;" if chg >= 0 else "&#9660;"
        sign    = "+" if chg >= 0 else ""
        glow    = "rgba(16,185,129,0.08)" if chg >= 0 else "rgba(239,68,68,0.08)"
        border  = C["positive"] if chg >= 0 else C["negative"]

        html = (
            f"<div style='background:{C['card']};border:1px solid {C['border']};"
            f"border-top:2px solid {border};border-radius:10px;padding:18px 22px;"
            f"background-image:radial-gradient(ellipse at top,{glow} 0%,transparent 70%);"
            f"box-shadow:0 4px 32px rgba(0,0,0,0.5);'>"
            f"<div style='font-size:0.68rem;color:{C['text_3']};text-transform:uppercase;"
            f"letter-spacing:0.1em;font-weight:700;margin-bottom:6px;'>{label}</div>"
            f"<div style='font-size:2.2rem;font-weight:700;color:{C['text_1']};"
            f"font-family:\"JetBrains Mono\",monospace;line-height:1;letter-spacing:-0.02em;'>"
            f"{'--' if ltp == 0 else f'{ltp:,.2f}'}</div>"
            f"<div style='font-size:0.88rem;color:{color};font-weight:600;margin-top:6px;"
            f"font-family:\"JetBrains Mono\",monospace;'>"
            f"{arrow} {sign}{chg:,.2f} ({sign}{pct:.2f}%)</div>"
            f"</div>"
        )
        with col:
            st.markdown(html, unsafe_allow_html=True)


# ── combined summary bar ──────────────────────────────────────────────

def _render_summary_bar(metrics: dict):
    """
    5-metric horizontal bar per spec:
      MTM Positions P&L | Day P&L (holdings) | Holdings P&L | Net Worth | Cash Available
    """
    pos_pnl      = metrics.get("positions_pnl", 0)
    holdings_day = metrics.get("holdings_day_pnl", 0)  # holdings-only day movement
    hold_pnl     = metrics.get("holdings_pnl", 0)
    hold_pct     = metrics.get("holdings_pnl_pct", 0)
    # Net worth per spec = holdings_value + cash + positions_pnl
    net_worth    = metrics.get("net_worth", 0) + pos_pnl
    cash_avail   = metrics.get("net_available", 0)     # cash + collateral

    top_border_color = signed_color(pos_pnl + hold_pnl)

    inner = (
        _pnl_cell("MTM Positions P&L", pos_pnl) + _vdiv() +
        _pnl_cell("Day P&L", holdings_day) + _vdiv() +
        _pnl_cell("Holdings P&L", hold_pnl, format_pct(hold_pct)) + _vdiv() +
        _stat_cell("Net Worth", format_inr(net_worth), "#a78bfa") + _vdiv() +
        _stat_cell("Cash Available", format_inr(cash_avail), C["text_2"])
    )

    st.markdown(
        f"<div style='background:{C['card']};border:1px solid {C['border']};"
        f"border-top:2px solid {top_border_color};"
        f"border-radius:10px;padding:14px 20px;margin-bottom:18px;"
        f"box-shadow:0 2px 20px rgba(0,0,0,0.4);'>"
        f"<div style='display:flex;align-items:stretch;gap:0;'>{inner}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


# ── underlying chips ──────────────────────────────────────────────────

def _render_underlying_section(positions, account_configs: dict, md_service):
    """Per-account chips showing active underlyings with live LTP."""
    # Group positions by account_id
    by_account: dict = defaultdict(list)
    for p in positions:
        if p.quantity != 0:
            by_account[p.account_id].append(p)

    all_account_ids = list(account_configs.keys())
    if not all_account_ids:
        return

    st.markdown(
        f"<div style='font-size:0.62rem;color:{C['text_3']};font-weight:700;"
        f"text-transform:uppercase;letter-spacing:0.1em;margin-bottom:10px;'>"
        f"Active Underlyings by Account</div>",
        unsafe_allow_html=True,
    )

    cols = st.columns(len(all_account_ids), gap="small")

    for col, account_id in zip(cols, all_account_ids):
        cfg  = account_configs.get(account_id)
        name = cfg.display_name if cfg else account_id
        client_id = (
            (cfg.credentials.get("user_id", "") if cfg else "") or account_id
        ).upper().replace("_", " ")

        account_positions = by_account.get(account_id, [])
        underlyings = list(dict.fromkeys(
            p.underlying or p.symbol
            for p in account_positions
            if p.underlying or p.symbol
        ))

        if underlyings:
            chips_html = ""
            for sym in underlyings:
                ltp    = md_service.get_ltp(sym) or 0.0
                chg    = md_service.get_change(sym) or 0.0
                color  = C["positive"] if chg >= 0 else C["negative"]
                ltp_s  = f"{ltp:,.0f}" if ltp > 0 else "--"
                chips_html += (
                    f"<div style='display:inline-flex;flex-direction:column;"
                    f"background:rgba(45,49,112,0.2);border:1px solid {C['border_glow']};"
                    f"border-radius:6px;padding:5px 10px;margin:3px 3px 3px 0;"
                    f"min-width:64px;'>"
                    f"<span style='font-size:0.65rem;font-weight:700;color:#a78bfa;"
                    f"letter-spacing:0.04em;'>{sym}</span>"
                    f"<span style='font-size:0.68rem;font-weight:600;color:{color};"
                    f"font-family:\"JetBrains Mono\",monospace;'>{ltp_s}</span>"
                    f"</div>"
                )
        else:
            chips_html = (
                f"<span style='font-size:0.72rem;color:{C['text_3']};font-style:italic;'>NIL</span>"
            )

        card = (
            f"<div style='background:{C['card']};border:1px solid {C['border']};"
            f"border-radius:8px;padding:12px 14px;min-height:80px;'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;"
            f"margin-bottom:8px;'>"
            f"<span style='font-size:0.7rem;font-weight:600;color:{C['text_2']};'>{name}</span>"
            f"<span style='font-size:0.58rem;color:#454a6e;background:#0d0e1a;"
            f"padding:1px 6px;border-radius:6px;font-weight:600;'>{client_id}</span>"
            f"</div>"
            f"<div style='display:flex;flex-wrap:wrap;'>{chips_html}</div>"
            f"</div>"
        )
        with col:
            st.markdown(card, unsafe_allow_html=True)


# ── positions table ───────────────────────────────────────────────────

def _render_positions_table(positions, aggregation: AggregationService):
    import pandas as pd

    open_pos = [p for p in positions if p.quantity != 0]

    if not open_pos:
        st.markdown(
            f"<div style='background:{C['card']};border:1px solid {C['border']};"
            f"border-radius:8px;padding:32px;text-align:center;color:{C['text_3']};'>"
            f"No open positions</div>",
            unsafe_allow_html=True,
        )
        return

    mtm   = sum(p.pnl for p in open_pos)
    day   = sum(p.day_pnl for p in open_pos)
    long_ = sum(1 for p in open_pos if p.quantity > 0)
    short_= sum(1 for p in open_pos if p.quantity < 0)

    mc = signed_color(mtm)
    dc = signed_color(day)
    ms = "+" if mtm > 0 else ""
    ds = "+" if day > 0 else ""

    ct2  = C["text_2"]
    ct3  = C["text_3"]
    cpos = C["positive"]
    cneg = C["negative"]
    ccard= C["card"]
    cbdr = C["border"]
    st.markdown(
        f"<div style='display:flex;justify-content:space-between;align-items:center;"
        f"margin-bottom:10px;'>"
        f"<div style='font-size:0.82rem;font-weight:700;color:{ct2};'>Open Positions"
        f"<span style='font-size:0.65rem;background:{ccard};color:{ct3};"
        f"padding:2px 8px;border-radius:8px;margin-left:8px;border:1px solid {cbdr};'>"
        f"{len(open_pos)}</span></div>"
        f"<div style='font-size:0.78rem;display:flex;gap:18px;'>"
        f"<span style='color:{mc};font-weight:600;'>MTM {ms}{format_inr(mtm)}</span>"
        f"<span style='color:{dc};font-weight:600;'>Day {ds}{format_inr(day)}</span>"
        f"<span style='color:{ct3};'>L:<strong style='color:{cpos};'>{long_}</strong>"
        f" S:<strong style='color:{cneg};'>{short_}</strong></span>"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    rows = []
    for p in sorted(open_pos, key=lambda x: abs(x.pnl), reverse=True):
        cfg = aggregation._accounts._account_configs.get(p.account_id)
        client = (cfg.credentials.get("user_id", "") if cfg else "") or p.account_id
        rows.append({
            "Symbol":     p.tradingsymbol or p.symbol,
            "Underlying": p.underlying or p.symbol,
            "Type":       p.instrument_type,
            "Dir":        "L" if p.quantity > 0 else "S",
            "Qty":        p.quantity,
            "Avg":        p.avg_price,
            "LTP":        p.ltp,
            "MTM PnL":    p.pnl,
            "Day PnL":    p.day_pnl,
            "Expiry":     p.expiry or "—",
            "Strike":     f"{p.strike:,.0f}" if p.strike else "—",
            "Account":    client.upper().replace("_", " "),
        })

    df = pd.DataFrame(rows)

    def _cpnl(v):
        if isinstance(v, (int, float)):
            return f"color: {C['positive']}" if v >= 0 else f"color: {C['negative']}"
        return ""

    def _cdir(v):
        if v == "L": return f"color: {C['positive']}; font-weight:700"
        if v == "S": return f"color: {C['negative']}; font-weight:700"
        return ""

    def _ctype(v):
        pal = {"FUT": "#60a5fa", "CE": "#34d399", "PE": "#f87171", "EQ": C["text_2"]}
        return f"color: {pal.get(str(v), C['text_3'])}; font-weight:600"

    styled = (
        df.style
        .map(_cpnl, subset=["MTM PnL", "Day PnL"])
        .map(_cdir,  subset=["Dir"])
        .map(_ctype, subset=["Type"])
        .format({
            "Avg":     "{:,.2f}",
            "LTP":     "{:,.2f}",
            "MTM PnL": "{:+,.0f}",
            "Day PnL": "{:+,.0f}",
        })
        .set_properties(**{
            "background-color": C["card"],
            "color":            C["text_1"],
            "font-size":        "12px",
            "font-family":      "\"JetBrains Mono\", monospace",
        })
        .set_table_styles([{"selector": "th", "props": [
            ("background-color", "#0a0b18"),
            ("color",            C["text_3"]),
            ("font-size",        "10px"),
            ("text-transform",   "uppercase"),
            ("letter-spacing",   "0.07em"),
            ("padding",          "7px 10px"),
            ("font-weight",      "700"),
        ]}])
    )
    height = min(56 + len(rows) * 36, 440)
    st.dataframe(styled, use_container_width=True, height=height, hide_index=True)


# ── main render ───────────────────────────────────────────────────────

def render(
    aggregation: AggregationService,
    md_service=None,
    portfolio_svc=None,
):
    metrics      = aggregation.get_combined_metrics()
    summaries    = aggregation.get_all_summaries()
    positions    = aggregation.get_combined_positions()
    account_cfgs  = aggregation._accounts._account_configs
    active_ids    = aggregation._accounts.list_account_ids()
    active_cfgs   = {aid: account_cfgs[aid] for aid in active_ids if aid in account_cfgs}

    # ── 1. Index cards ────────────────────────────────────────────────
    if md_service:
        _render_index_cards(md_service)
        st.markdown("<div style='margin-bottom:16px;'></div>", unsafe_allow_html=True)

    # ── 2. Combined summary bar ───────────────────────────────────────
    _render_summary_bar(metrics)

    # ── 3. Account cards ──────────────────────────────────────────────
    render_account_pnl_cards(summaries, account_cfgs)
    st.markdown("<div style='margin-bottom:20px;'></div>", unsafe_allow_html=True)

    # ── 4. Active underlyings ─────────────────────────────────────────
    if md_service:
        _render_underlying_section(positions, active_cfgs, md_service)
        st.markdown("<div style='margin-bottom:20px;'></div>", unsafe_allow_html=True)

    # ── 5. Positions table ────────────────────────────────────────────
    _render_positions_table(positions, aggregation)
