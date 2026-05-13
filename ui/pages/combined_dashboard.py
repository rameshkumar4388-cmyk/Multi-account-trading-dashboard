"""
Trading Terminal — homepage.

Layout (top → bottom):
  1. NIFTY 50 + BANKNIFTY large index cards  (@st.fragment refreshes independently)
  2. Combined summary bar                    (5 semantic metrics)
  3. Account-wise cards                      (vertical stack per account)
  4. Active underlyings per account          (underlying name + LTP chips — NOT contracts)
  5. Open positions table                    (terminal-grade)
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

import streamlit as st

from services.aggregation_service import AggregationService
from ui.account_order import sort_account_ids, sort_summaries
from ui.components.account_pnl_cards import render_account_pnl_cards
from ui.theme import C, format_inr, format_pct, signed_color

# Regex: a valid underlying name has only uppercase letters (and maybe &, -)
# Contract symbols always contain digits (expiry date/strike) — filter those out.
_UNDERLYING_RE = re.compile(r'^[A-Z][A-Z&\-]{1,19}$')

# Detect if @st.fragment with run_every is available (Streamlit ≥ 1.37)
_HAS_FRAGMENT = hasattr(st, 'fragment')


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
        f"<div style='font-size:0.57rem;color:{C['text_3']};text-transform:uppercase;"
        f"letter-spacing:0.09em;font-weight:600;margin-bottom:4px;'>{label}</div>"
        f"<div style='font-size:1.25rem;font-weight:700;color:{color};"
        f"font-family:\"JetBrains Mono\",monospace;line-height:1.1;'>"
        f"{sign}{format_inr(value)}</div>{sub_h}</div>"
    )


def _stat_cell(label: str, value: str, color: str = None) -> str:
    color = color or C["text_2"]
    return (
        f"<div style='flex:1;text-align:center;padding:0 10px;'>"
        f"<div style='font-size:0.57rem;color:{C['text_3']};text-transform:uppercase;"
        f"letter-spacing:0.09em;font-weight:600;margin-bottom:4px;'>{label}</div>"
        f"<div style='font-size:1.25rem;font-weight:700;color:{color};"
        f"font-family:\"JetBrains Mono\",monospace;line-height:1.1;'>{value}</div></div>"
    )


def _vdiv() -> str:
    return f"<div style='width:1px;background:{C['border']};margin:4px 0;flex-shrink:0;'></div>"


# ── index cards ───────────────────────────────────────────────────────

def _index_card_html(label: str, ltp: float, chg: float, pct: float) -> str:
    color  = C["positive"] if chg >= 0 else C["negative"]
    arrow  = "&#9650;" if chg >= 0 else "&#9660;"
    sign   = "+" if chg >= 0 else ""
    glow   = "rgba(16,185,129,0.07)" if chg >= 0 else "rgba(239,68,68,0.07)"
    border = color
    ltp_s  = f"{ltp:,.2f}" if ltp > 0 else "—"
    return (
        f"<div style='background:{C['card']};border:1px solid {C['border']};"
        f"border-top:2px solid {border};border-radius:10px;padding:16px 20px;"
        f"background-image:radial-gradient(ellipse at top left,{glow} 0%,transparent 65%);"
        f"box-shadow:0 4px 24px rgba(0,0,0,0.45);'>"
        f"<div style='font-size:0.62rem;color:{C['text_3']};text-transform:uppercase;"
        f"letter-spacing:0.12em;font-weight:700;margin-bottom:6px;'>{label}</div>"
        f"<div style='font-size:2.1rem;font-weight:700;color:{C['text_1']};"
        f"font-family:\"JetBrains Mono\",monospace;line-height:1;letter-spacing:-0.02em;'>"
        f"{ltp_s}</div>"
        f"<div style='font-size:0.85rem;color:{color};font-weight:600;margin-top:5px;"
        f"font-family:\"JetBrains Mono\",monospace;'>"
        f"{arrow} {sign}{chg:,.2f} &nbsp;({sign}{pct:.2f}%)</div>"
        f"</div>"
    )


def _render_index_cards_impl(md_service, positions=None):
    # Fallback: derive index LTP from positions broker data (same source as positions table)
    _ul = {p.underlying: p.ltp for p in (positions or []) if p.underlying and p.ltp}
    pairs = [("NIFTY", "NIFTY 50"), ("BANKNIFTY", "NIFTY BANK")]
    cols  = st.columns(2, gap="medium")
    for col, (sym, label) in zip(cols, pairs):
        ltp = md_service.get_ltp(sym) or _ul.get(sym, 0.0)
        chg = md_service.get_change(sym) or 0.0
        pct = md_service.get_change_pct(sym) or 0.0
        with col:
            st.markdown(_index_card_html(label, ltp, chg, pct), unsafe_allow_html=True)


# Wrap in @st.fragment if available so index cards refresh without full-page rerender
if _HAS_FRAGMENT:
    try:
        @st.fragment(run_every=3)
        def _render_index_cards(md_service, positions=None):
            _render_index_cards_impl(md_service, positions)
    except Exception:
        def _render_index_cards(md_service, positions=None):
            _render_index_cards_impl(md_service, positions)
else:
    def _render_index_cards(md_service, positions=None):
        _render_index_cards_impl(md_service, positions)


# ── combined summary bar ──────────────────────────────────────────────

def _render_summary_bar(metrics: dict):
    pos_pnl      = metrics.get("positions_pnl", 0)
    holdings_day = metrics.get("holdings_day_pnl", 0)
    hold_pnl     = metrics.get("holdings_pnl", 0)
    hold_pct     = metrics.get("holdings_pnl_pct", 0)
    net_worth    = metrics.get("net_worth", 0)  # already includes positions_pnl
    cash_avail   = metrics.get("available_cash", 0)

    inner = (
        _pnl_cell("MTM Positions P&L", pos_pnl) + _vdiv() +
        _pnl_cell("Day P&L (Holdings)", holdings_day) + _vdiv() +
        _pnl_cell("Holdings P&L", hold_pnl, format_pct(hold_pct)) + _vdiv() +
        _stat_cell("Net Worth", format_inr(net_worth), "#a78bfa") + _vdiv() +
        _stat_cell("Cash", format_inr(cash_avail), C["text_2"])
    )
    bc = signed_color(pos_pnl + hold_pnl)
    st.markdown(
        f"<div style='background:{C['card']};border:1px solid {C['border']};"
        f"border-top:2px solid {bc};border-radius:10px;padding:12px 18px;"
        f"margin-bottom:16px;box-shadow:0 2px 16px rgba(0,0,0,0.4);'>"
        f"<div style='display:flex;align-items:stretch;gap:0;'>{inner}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


# ── underlying chips ──────────────────────────────────────────────────

def _render_underlying_section(positions, active_cfgs: dict, md_service=None):
    if not active_cfgs:
        return

    by_account: dict = defaultdict(list)
    for p in positions:
        if p.quantity != 0:
            by_account[p.account_id].append(p)

    st.markdown(
        f"<div style='font-size:0.58rem;color:{C['text_3']};font-weight:700;"
        f"text-transform:uppercase;letter-spacing:0.1em;margin-bottom:8px;'>"
        f"Active Underlyings</div>",
        unsafe_allow_html=True,
    )

    cols = st.columns(len(active_cfgs), gap="small")

    for col, account_id in zip(cols, active_cfgs):
        cfg   = active_cfgs[account_id]
        name  = cfg.display_name if cfg else account_id
        client_id = (
            (cfg.credentials.get("user_id", "") if hasattr(cfg, 'credentials') else "")
            or account_id
        ).upper().replace("_", " ")

        account_pos = by_account.get(account_id, [])

        # Deduplicate underlying names; filter out full contract symbols (contain digits)
        seen_underlyings: list = []
        for p in account_pos:
            cand = p.underlying or p.symbol
            if cand and _UNDERLYING_RE.match(cand) and cand not in seen_underlyings:
                seen_underlyings.append(cand)

        if seen_underlyings:
            chips_html = ""
            for sym in seen_underlyings:
                ltp   = (md_service.get_ltp(sym) or 0.0) if md_service else 0.0
                chg   = (md_service.get_change(sym) or 0.0) if md_service else 0.0
                color = C["positive"] if chg >= 0 else C["negative"]
                ltp_s = f"{ltp:,.0f}" if ltp > 0 else "—"
                chips_html += (
                    f"<div style='display:inline-flex;flex-direction:column;"
                    f"background:rgba(45,49,112,0.18);border:1px solid {C['border_glow']};"
                    f"border-radius:6px;padding:5px 9px;margin:2px 3px 2px 0;min-width:58px;'>"
                    f"<span style='font-size:0.6rem;font-weight:700;color:#a78bfa;"
                    f"letter-spacing:0.04em;'>{sym}</span>"
                    f"<span style='font-size:0.65rem;font-weight:600;color:{color};"
                    f"font-family:\"JetBrains Mono\",monospace;'>{ltp_s}</span>"
                    f"</div>"
                )
        else:
            chips_html = (
                f"<span style='font-size:0.7rem;color:{C['text_3']};font-style:italic;'>No open positions</span>"
            )

        card = (
            f"<div style='background:{C['card']};border:1px solid {C['border']};"
            f"border-radius:8px;padding:10px 12px;'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;"
            f"margin-bottom:6px;'>"
            f"<span style='font-size:0.68rem;font-weight:600;color:{C['text_2']};'>{name}</span>"
            f"<span style='font-size:0.55rem;color:{C['text_3']};background:#0a0b18;"
            f"padding:1px 5px;border-radius:5px;font-weight:600;'>{client_id}</span>"
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
            f"border-radius:8px;padding:28px;text-align:center;color:{C['text_3']};'>"
            f"No open positions</div>",
            unsafe_allow_html=True,
        )
        return

    mtm   = sum(p.pnl for p in open_pos)
    day   = sum(p.day_pnl for p in open_pos)
    long_ = sum(1 for p in open_pos if p.quantity > 0)
    short_= sum(1 for p in open_pos if p.quantity < 0)

    mc, dc = signed_color(mtm), signed_color(day)
    ms, ds = ("+" if mtm > 0 else ""), ("+" if day > 0 else "")
    ct3    = C["text_3"]
    cpos   = C["positive"]
    cneg   = C["negative"]
    ct2    = C["text_2"]
    ccard  = C["card"]
    cbdr   = C["border"]

    st.markdown(
        f"<div style='display:flex;justify-content:space-between;align-items:center;"
        f"margin-bottom:8px;'>"
        f"<div style='font-size:0.8rem;font-weight:700;color:{ct2};'>Open Positions"
        f"<span style='font-size:0.62rem;background:{ccard};color:{ct3};"
        f"padding:1px 7px;border-radius:7px;margin-left:8px;border:1px solid {cbdr};'>"
        f"{len(open_pos)}</span></div>"
        f"<div style='font-size:0.75rem;display:flex;gap:16px;'>"
        f"<span style='color:{mc};font-weight:600;'>MTM {ms}{format_inr(mtm)}</span>"
        f"<span style='color:{dc};font-weight:600;'>Day {ds}{format_inr(day)}</span>"
        f"<span style='color:{ct3};'>L:<strong style='color:{cpos};'>{long_}</strong>"
        f" S:<strong style='color:{cneg};'>{short_}</strong></span>"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    rows = []
    for p in sorted(open_pos, key=lambda x: abs(x.pnl), reverse=True):
        cfg    = aggregation._accounts._account_configs.get(p.account_id)
        client = (
            (cfg.credentials.get("user_id", "") if hasattr(cfg, 'credentials') else "")
            or p.account_id
        ).upper().replace("_", " ")
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
            "Account":    client,
        })

    df = pd.DataFrame(rows)

    def _cp(v):
        if isinstance(v, (int, float)):
            return f"color: {C['positive']}" if v >= 0 else f"color: {C['negative']}"
        return ""

    def _cd(v):
        if v == "L": return f"color: {C['positive']}; font-weight:700"
        if v == "S": return f"color: {C['negative']}; font-weight:700"
        return ""

    def _ct(v):
        return f"color: {'#60a5fa' if v=='FUT' else '#34d399' if v=='CE' else '#f87171' if v=='PE' else C['text_2']}; font-weight:600"

    styled = (
        df.style
        .map(_cp, subset=["MTM PnL", "Day PnL"])
        .map(_cd, subset=["Dir"])
        .map(_ct, subset=["Type"])
        .format({"Avg": "{:,.2f}", "LTP": "{:,.2f}", "MTM PnL": "{:+,.0f}", "Day PnL": "{:+,.0f}"})
        .set_properties(**{
            "background-color": C["card"],
            "color": C["text_1"],
            "font-size": "11.5px",
            "font-family": '"JetBrains Mono", monospace',
        })
        .set_table_styles([{"selector": "th", "props": [
            ("background-color", "#0a0b18"),
            ("color", C["text_3"]),
            ("font-size", "9.5px"),
            ("text-transform", "uppercase"),
            ("letter-spacing", "0.07em"),
            ("padding", "6px 9px"),
            ("font-weight", "700"),
        ]}])
    )
    st.dataframe(styled, use_container_width=True,
                 height=min(52 + len(rows) * 34, 420), hide_index=True)


# ── main render ───────────────────────────────────────────────────────

def render(
    aggregation: AggregationService,
    md_service=None,
    portfolio_svc=None,
):
    metrics    = aggregation.get_combined_metrics()
    all_cfgs   = aggregation._accounts._account_configs
    summaries  = sort_summaries(aggregation.get_all_summaries(), all_cfgs)
    positions  = aggregation.get_combined_positions()
    active_ids = sort_account_ids(aggregation._accounts.list_account_ids(), all_cfgs)
    active_cfgs = {aid: all_cfgs[aid] for aid in active_ids if aid in all_cfgs}

    # ── 1. Index cards (fragment-refreshed independently when possible) ─
    if md_service:
        _render_index_cards(md_service, positions)
        st.markdown("<div style='margin-bottom:14px;'></div>", unsafe_allow_html=True)

    # ── 2. Combined summary bar ────────────────────────────────────────
    _render_summary_bar(metrics)

    # ── 3. Account cards ───────────────────────────────────────────────
    render_account_pnl_cards(summaries, all_cfgs)
    st.markdown("<div style='margin-bottom:16px;'></div>", unsafe_allow_html=True)

    # ── 4. Active underlyings (per account, underlying name only) ──────
    _render_underlying_section(positions, active_cfgs, md_service)
    st.markdown("<div style='margin-bottom:16px;'></div>", unsafe_allow_html=True)

    # ── 5. Positions table ─────────────────────────────────────────────
    _render_positions_table(positions, aggregation)
