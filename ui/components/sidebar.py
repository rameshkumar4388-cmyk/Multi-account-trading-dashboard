from __future__ import annotations

from typing import List, Optional, Tuple

import streamlit as st

from config.settings import AppSettings


_PAGES = {
    "terminal":  ("🖥",  "Trading Terminal"),
    "positions": ("📈",  "Positions & P&L"),
    "exposure":  ("⚖️",  "Exposure & Risk"),
    "account":   ("👤",  "Account View"),
    "holdings":  ("📁",  "Holdings"),
}


def render_sidebar(settings: AppSettings, account_ids: List[str]) -> Tuple[str, Optional[str]]:
    """
    Render the sidebar navigation.

    Returns:
        (view_key, selected_account_id)
        view_key: one of "terminal" | "positions" | "exposure" | "account" | "holdings"
    """
    with st.sidebar:
        # Logo / brand
        st.markdown(
            """
            <div style="padding:12px 0 4px 0; text-align:center;">
                <div style="font-size:1.6rem; line-height:1;">📊</div>
                <div style="font-weight:700; font-size:1rem; color:#e6edf3; margin-top:4px;">
                    TradeView
                </div>
                <div style="font-size:0.68rem; color:#6e7681; margin-top:2px;">
                    Multi-account Terminal
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.divider()

        # ── Navigation ────────────────────────────────────────────────
        st.markdown(
            "<div style='font-size:0.68rem; color:#6e7681; font-weight:600; "
            "text-transform:uppercase; letter-spacing:0.1em; margin-bottom:6px;'>"
            "Navigation</div>",
            unsafe_allow_html=True,
        )

        if "active_page" not in st.session_state:
            st.session_state.active_page = "terminal"

        for key, (icon, label) in _PAGES.items():
            is_active = st.session_state.active_page == key
            btn_style = (
                "background-color:#1f4287 !important; color:#58a6ff !important;"
            ) if is_active else ""

            if st.button(
                f"{icon}  {label}",
                key=f"nav_{key}",
                use_container_width=True,
            ):
                st.session_state.active_page = key
                st.rerun()

        st.divider()

        # ── Account / Broker filter ───────────────────────────────────
        view = st.session_state.active_page
        selected_account: Optional[str] = None

        if account_ids:
            cfg_map = {a.account_id: a for a in settings.accounts}

            if view in ("positions", "exposure", "holdings", "account"):
                st.markdown(
                    "<div style='font-size:0.68rem; color:#6e7681; font-weight:600; "
                    "text-transform:uppercase; letter-spacing:0.1em; margin-bottom:6px;'>"
                    "Filter by Account</div>",
                    unsafe_allow_html=True,
                )
                display_names = {
                    aid: (cfg_map[aid].display_name if aid in cfg_map else aid)
                    for aid in account_ids
                }
                options = ["All Accounts"] + account_ids
                labels = ["All Accounts"] + [display_names[a] for a in account_ids]

                sel_label = st.selectbox(
                    "Account",
                    labels,
                    key="account_selector",
                    label_visibility="collapsed",
                )
                if sel_label != "All Accounts":
                    idx = labels.index(sel_label)
                    selected_account = options[idx]

            # ── Accounts quick-info ───────────────────────────────────
            st.markdown(
                "<div style='font-size:0.68rem; color:#6e7681; font-weight:600; "
                "text-transform:uppercase; letter-spacing:0.1em; margin-bottom:6px;'>"
                "Active Accounts</div>",
                unsafe_allow_html=True,
            )
            for aid in account_ids:
                cfg = cfg_map.get(aid)
                broker = cfg.metadata.get("original_broker", "").capitalize() if cfg else ""
                name = cfg.display_name if cfg else aid
                st.markdown(
                    f"""
                    <div style="display:flex; justify-content:space-between; align-items:center;
                                padding:5px 8px; border-radius:5px; margin-bottom:3px;
                                background:#21262d;">
                        <span style="font-size:0.73rem; color:#c9d1d9;">{name}</span>
                        <span style="font-size:0.62rem; color:#6e7681; background:#30363d;
                                     padding:1px 6px; border-radius:8px;">{broker}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        st.divider()

        # ── Mode indicator ────────────────────────────────────────────
        if settings.app_mode == "live":
            st.markdown(
                "<div style='text-align:center;'>"
                "<span style='background:#238636; color:#fff; font-size:0.7rem; font-weight:700;"
                "padding:3px 10px; border-radius:10px; letter-spacing:0.08em;'>● LIVE</span>"
                "</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div style='text-align:center;'>"
                "<span style='background:#6e7681; color:#fff; font-size:0.7rem; font-weight:700;"
                "padding:3px 10px; border-radius:10px; letter-spacing:0.08em;'>◎ DEMO MODE</span>"
                "</div>",
                unsafe_allow_html=True,
            )

        st.markdown(
            "<div style='font-size:0.62rem; color:#30363d; text-align:center; margin-top:12px;'>"
            "Read-only &nbsp;&middot;&nbsp; No order execution"
            "</div>",
            unsafe_allow_html=True,
        )

    return view, selected_account
