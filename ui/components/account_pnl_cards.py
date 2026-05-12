"""
Account-wise P&L cards — vertical metric stack layout.

Each card shows per-account metrics in a vertical list:
  MTM Positions P&L  ← most prominent
  Day P&L
  Margin Available   (= net_available: cash + collateral)
  Used Margin        + progress bar
  Holdings P&L
  Net Worth          (holdings_value + cash + positions_pnl)
"""
from __future__ import annotations

from typing import List

import streamlit as st

from schemas.account import AccountSummary
from ui.theme import C, format_inr, signed_color


def _metric_row(label: str, value: float, size: str = "sm", highlight: bool = False) -> str:
    color = signed_color(value)
    sign  = "+" if value > 0 else ""
    val_s = format_inr(value)
    val_display = f"{sign}{val_s}" if value != 0 else val_s

    font_size = {"lg": "1.15rem", "md": "0.95rem", "sm": "0.82rem"}.get(size, "0.82rem")
    label_size = "0.58rem"
    label_color = "#454a6e"
    bg = "background:rgba(109,40,217,0.06);border-radius:6px;padding:6px 8px;" if highlight else "padding:5px 0;"

    return (
        f"<div style='{bg}margin-bottom:4px;'>"
        f"<div style='font-size:{label_size};color:{label_color};text-transform:uppercase;"
        f"letter-spacing:0.08em;font-weight:600;margin-bottom:2px;'>{label}</div>"
        f"<div style='font-size:{font_size};font-weight:700;color:{color};"
        f"font-family:\"JetBrains Mono\",monospace;line-height:1.2;'>{val_display}</div>"
        f"</div>"
    )


def _neutral_row(label: str, value_html: str, size: str = "sm") -> str:
    font_size = {"lg": "1.15rem", "md": "0.95rem", "sm": "0.82rem"}.get(size, "0.82rem")
    return (
        f"<div style='padding:5px 0;margin-bottom:4px;'>"
        f"<div style='font-size:0.58rem;color:#454a6e;text-transform:uppercase;"
        f"letter-spacing:0.08em;font-weight:600;margin-bottom:2px;'>{label}</div>"
        f"<div style='font-size:{font_size};font-weight:700;color:#8892b0;"
        f"font-family:\"JetBrains Mono\",monospace;line-height:1.2;'>{value_html}</div>"
        f"</div>"
    )


def render_account_pnl_cards(summaries: List[AccountSummary], account_configs: dict):
    if not summaries:
        st.info("No account data.")
        return

    cols = st.columns(len(summaries), gap="small")

    for col, s in zip(cols, summaries):
        cfg = account_configs.get(s.account_id)
        # Show Zerodha client ID if configured, else internal account id
        client_id = ""
        if cfg:
            client_id = (cfg.credentials.get("user_id", "")
                         or cfg.owner or s.account_id.upper())
        client_id = client_id.upper().replace("_", " ") if client_id else s.account_id.upper()

        # Net worth per spec = holdings_value + cash + positions_pnl
        card_net_worth = (
            s.total_holdings_value + s.available_cash + s.positions_pnl
        )

        # Margin bar
        total_capacity = s.used_margin + s.net_available
        margin_pct     = (s.used_margin / total_capacity * 100) if total_capacity > 0 else 0.0
        margin_pct     = min(margin_pct, 100)
        bar_color      = C["negative"] if margin_pct > 75 else (C["warning"] if margin_pct > 50 else C["positive"])

        # Build inner content
        inner = (
            # ── Positions MTM P&L (most prominent) ──
            _metric_row("MTM Positions P&L", s.positions_pnl, size="lg", highlight=True)
            # ── Day P&L ──
            + _metric_row("Day P&L (Holdings)", s.holdings_day_pnl, size="md")
            # ── Divider ──
            + "<div style='border-top:1px solid #1c1f3a;margin:6px 0;'></div>"
            # ── Margin Available ──
            + _neutral_row(
                "Margin Available",
                format_inr(s.net_available),
            )
            # ── Used Margin + bar ──
            + f"<div style='padding:5px 0;margin-bottom:4px;'>"
            + f"<div style='display:flex;justify-content:space-between;"
            + f"font-size:0.58rem;color:#454a6e;text-transform:uppercase;"
            + f"letter-spacing:0.08em;font-weight:600;margin-bottom:3px;'>"
            + f"<span>Used Margin</span><span style='color:{bar_color}'>{margin_pct:.0f}%</span></div>"
            + f"<div style='background:#1c1f3a;border-radius:3px;height:4px;overflow:hidden;'>"
            + f"<div style='background:{bar_color};width:{margin_pct:.1f}%;height:100%;border-radius:3px;'></div></div>"
            + f"<div style='font-size:0.7rem;font-weight:600;color:#8892b0;"
            + f"font-family:\"JetBrains Mono\",monospace;margin-top:3px;'>{format_inr(s.used_margin)}</div>"
            + "</div>"
            # ── Divider ──
            + "<div style='border-top:1px solid #1c1f3a;margin:6px 0;'></div>"
            # ── Holdings P&L ──
            + _metric_row("Holdings P&L", s.holdings_pnl, size="sm")
            # ── Net Worth ──
            + f"<div style='padding:5px 0;margin-top:2px;'>"
            + f"<div style='font-size:0.58rem;color:#454a6e;text-transform:uppercase;"
            + f"letter-spacing:0.08em;font-weight:600;margin-bottom:2px;'>Net Worth</div>"
            + f"<div style='font-size:0.88rem;font-weight:700;color:#a78bfa;"
            + f"font-family:\"JetBrains Mono\",monospace;'>{format_inr(card_net_worth)}</div>"
            + "</div>"
        )

        html = (
            f"<div style='background:{C['card']};border:1px solid {C['border']};"
            f"border-radius:10px;padding:14px 16px;height:100%;"
            f"box-shadow:0 4px 24px rgba(0,0,0,0.4);'>"
            # Card header
            f"<div style='display:flex;justify-content:space-between;align-items:flex-start;"
            f"margin-bottom:10px;'>"
            f"<div style='font-size:0.8rem;font-weight:700;color:{C['text_1']};'>"
            f"{s.display_name}</div>"
            f"<div style='font-size:0.6rem;background:rgba(109,40,217,0.15);"
            f"color:#a78bfa;padding:2px 7px;border-radius:8px;font-weight:600;"
            f"letter-spacing:0.06em;'>{client_id}</div>"
            f"</div>"
            f"{inner}"
            f"</div>"
        )

        with col:
            st.markdown(html, unsafe_allow_html=True)
