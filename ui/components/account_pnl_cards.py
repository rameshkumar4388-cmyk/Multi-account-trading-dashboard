"""
Account-wise MTM P&L cards — the most prominent element on the trading terminal homepage.

Each card shows a single account's live P&L state in a compact,
color-coded panel that is immediately readable at a glance.
"""
from __future__ import annotations

from typing import List

import streamlit as st

from schemas.account import AccountSummary
from ui.theme import format_inr


def render_account_pnl_cards(summaries: List[AccountSummary], account_configs: dict):
    """
    Render a horizontal row of account P&L cards.

    Args:
        summaries:        List of AccountSummary objects
        account_configs:  Dict of account_id -> AccountConfig (for display names / broker)
    """
    if not summaries:
        st.info("No account data available.")
        return

    cols = st.columns(len(summaries), gap="small")

    for col, s in zip(cols, summaries):
        cfg = account_configs.get(s.account_id)
        broker = cfg.metadata.get("original_broker", s.broker).capitalize() if cfg else s.broker.capitalize()

        day_up = s.day_pnl >= 0
        mtm_up = s.total_pnl >= 0
        day_color = "#3fb950" if day_up else "#f85149"
        mtm_color = "#3fb950" if mtm_up else "#f85149"
        day_sign = "+" if day_up else ""
        mtm_sign = "+" if mtm_up else ""

        margin_pct = (
            (s.used_margin / (s.used_margin + s.available_cash) * 100)
            if (s.used_margin + s.available_cash) > 0 else 0.0
        )
        margin_bar_color = "#f85149" if margin_pct > 75 else ("#f0883e" if margin_pct > 50 else "#3fb950")
        margin_bar_width = min(margin_pct, 100)

        with col:
            st.markdown(
                f"""
                <div style="background:#161b22; border:1px solid #30363d; border-radius:10px;
                            padding:14px 16px; height:100%;">

                    <!-- Account header -->
                    <div style="display:flex; justify-content:space-between; align-items:flex-start;
                                margin-bottom:10px;">
                        <div>
                            <div style="font-size:0.82rem; font-weight:700; color:#e6edf3;
                                        line-height:1.2;">{s.display_name}</div>
                            <div style="font-size:0.68rem; color:#6e7681; margin-top:2px;">
                                {broker}
                            </div>
                        </div>
                        <div style="font-size:0.62rem; background:#21262d; color:#8b949e;
                                    padding:2px 7px; border-radius:10px; font-weight:600;">
                            {s.account_id.upper().replace("_"," ")}
                        </div>
                    </div>

                    <!-- Day P&L - most prominent -->
                    <div style="margin-bottom:8px;">
                        <div style="font-size:0.62rem; color:#6e7681; text-transform:uppercase;
                                    letter-spacing:0.06em; margin-bottom:2px;">Day P&amp;L</div>
                        <div style="font-size:1.3rem; font-weight:700; color:{day_color}; line-height:1;">
                            {day_sign}{format_inr(s.day_pnl)}
                        </div>
                    </div>

                    <!-- MTM & Cash row -->
                    <div style="display:flex; gap:12px; margin-bottom:10px;">
                        <div style="flex:1;">
                            <div style="font-size:0.6rem; color:#6e7681; text-transform:uppercase;
                                        letter-spacing:0.05em; margin-bottom:1px;">MTM P&amp;L</div>
                            <div style="font-size:0.85rem; font-weight:600; color:{mtm_color};">
                                {mtm_sign}{format_inr(s.total_pnl)}
                            </div>
                        </div>
                        <div style="flex:1;">
                            <div style="font-size:0.6rem; color:#6e7681; text-transform:uppercase;
                                        letter-spacing:0.05em; margin-bottom:1px;">Net Worth</div>
                            <div style="font-size:0.85rem; font-weight:600; color:#c9d1d9;">
                                {format_inr(s.net_worth)}
                            </div>
                        </div>
                    </div>

                    <!-- Margin bar -->
                    <div>
                        <div style="display:flex; justify-content:space-between;
                                    font-size:0.62rem; color:#6e7681; margin-bottom:3px;">
                            <span>Margin Used</span>
                            <span>{format_inr(s.used_margin)} ({margin_pct:.0f}%)</span>
                        </div>
                        <div style="background:#21262d; border-radius:3px; height:4px;">
                            <div style="background:{margin_bar_color}; width:{margin_bar_width:.0f}%;
                                        height:100%; border-radius:3px;"></div>
                        </div>
                        <div style="font-size:0.62rem; color:#6e7681; margin-top:2px;">
                            Cash: {format_inr(s.available_cash)}
                        </div>
                    </div>

                </div>
                """,
                unsafe_allow_html=True,
            )
