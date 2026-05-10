from __future__ import annotations

from typing import List, Optional, Tuple

import streamlit as st

from config.settings import AppSettings


def render_sidebar(settings: AppSettings, account_ids: List[str]) -> Tuple[str, Optional[str]]:
    """
    Render the sidebar navigation and filters.

    Returns:
        (view, selected_account_id)
        view: "combined" | "account" | "holdings" | "positions" | "exposure"
    """
    with st.sidebar:
        st.markdown(
            """
            <div style="padding: 12px 0 8px 0; text-align:center;">
                <div style="font-size:1.5rem;">📊</div>
                <div style="font-weight:700; font-size:1rem; color:#e6edf3;">TradeView</div>
                <div style="font-size:0.72rem; color:#6e7681; margin-top:2px;">
                    Read-only Portfolio Monitor
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.divider()

        # Navigation
        st.markdown(
            "<div style='font-size:0.72rem; color:#6e7681; font-weight:600; "
            "text-transform:uppercase; letter-spacing:0.08em; margin-bottom:6px;'>Navigation</div>",
            unsafe_allow_html=True,
        )

        pages = {
            "🏠  Combined Dashboard": "combined",
            "👤  Account View": "account",
            "📁  Holdings": "holdings",
            "📈  Positions & P&L": "positions",
            "⚖️  Exposure & Risk": "exposure",
        }

        if "active_page" not in st.session_state:
            st.session_state.active_page = "combined"

        for label, page_key in pages.items():
            is_active = st.session_state.active_page == page_key
            btn_style = (
                "background:#1f4287; color:#58a6ff; font-weight:600;"
                if is_active
                else "background:transparent; color:#c9d1d9;"
            )
            if st.button(
                label,
                key=f"nav_{page_key}",
                use_container_width=True,
                help=None,
            ):
                st.session_state.active_page = page_key
                st.rerun()

        st.divider()

        # Account filter (shown when not on combined view)
        selected_account: Optional[str] = None
        view = st.session_state.active_page

        if view in ("account", "holdings", "positions", "exposure") and account_ids:
            st.markdown(
                "<div style='font-size:0.72rem; color:#6e7681; font-weight:600; "
                "text-transform:uppercase; letter-spacing:0.08em; margin-bottom:6px;'>Account</div>",
                unsafe_allow_html=True,
            )
            account_options = ["All Accounts"] + account_ids
            sel = st.selectbox(
                "Select Account",
                options=account_options,
                key="account_selector",
                label_visibility="collapsed",
            )
            selected_account = None if sel == "All Accounts" else sel

        st.divider()

        # Mode indicator
        mode_label = "🟢 LIVE MODE" if settings.app_mode == "live" else "🔵 DEMO MODE"
        st.markdown(
            f"<div style='font-size:0.75rem; color:#6e7681; text-align:center;'>{mode_label}</div>",
            unsafe_allow_html=True,
        )

        broker_labels = {
            "zerodha_primary": "Zerodha Primary",
            "zerodha_trading": "Zerodha Trading",
            "groww_invest": "Groww",
        }
        acct_lines = " · ".join(broker_labels.get(a, a) for a in account_ids)
        if acct_lines:
            st.markdown(
                f"<div style='font-size:0.7rem; color:#6e7681; text-align:center; margin-top:4px;'>"
                f"{acct_lines}</div>",
                unsafe_allow_html=True,
            )

        st.markdown(
            "<div style='font-size:0.68rem; color:#30363d; text-align:center; margin-top:24px;'>"
            "Read-only · No order execution"
            "</div>",
            unsafe_allow_html=True,
        )

    return view, selected_account
