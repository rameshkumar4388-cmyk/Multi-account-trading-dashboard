from __future__ import annotations

from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

import streamlit as st

from config.settings import AppSettings

if TYPE_CHECKING:
    from services.account_service import AccountHealth


_PAGES = {
    "terminal":  ("🖥",  "Trading Terminal"),
    "positions": ("📈",  "Positions & P&L"),
    "exposure":  ("⚖️",  "Exposure & Risk"),
    "account":   ("👤",  "Account View"),
    "holdings":  ("📁",  "Holdings"),
}


def render_sidebar(
    settings: AppSettings,
    account_ids: List[str],
    account_health: Optional[Dict[str, "AccountHealth"]] = None,
) -> Tuple[str, Optional[str]]:
    """
    Render the sidebar navigation and account status panel.

    Args:
        settings:        App settings (mode, accounts list)
        account_ids:     IDs of accounts that authenticated successfully
        account_health:  Per-account health from AccountService.get_health()
                         If provided, failed accounts are shown with error indicators.

    Returns:
        (view_key, selected_account_id)
    """
    health = account_health or {}
    all_configured = list(health.keys()) if health else account_ids

    with st.sidebar:
        # ── Brand ─────────────────────────────────────────────────────
        st.markdown(
            "<div style='padding:12px 0 4px 0;text-align:center;'>"
            "<div style='font-size:1.6rem;line-height:1;'>📊</div>"
            "<div style='font-weight:700;font-size:1rem;color:#e6edf3;margin-top:4px;'>TradeView</div>"
            "<div style='font-size:0.68rem;color:#6e7681;margin-top:2px;'>Multi-account Terminal</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        st.divider()

        # ── Navigation ────────────────────────────────────────────────
        st.markdown(
            "<div style='font-size:0.68rem;color:#6e7681;font-weight:600;"
            "text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px;'>Navigation</div>",
            unsafe_allow_html=True,
        )

        if "active_page" not in st.session_state:
            st.session_state.active_page = "terminal"

        for key, (icon, label) in _PAGES.items():
            if st.button(f"{icon}  {label}", key=f"nav_{key}", use_container_width=True):
                st.session_state.active_page = key
                st.rerun()

        st.divider()

        # ── Account filter (context-sensitive) ────────────────────────
        view = st.session_state.active_page
        selected_account: Optional[str] = None

        cfg_map = {a.account_id: a for a in settings.accounts}

        if account_ids and view in ("positions", "exposure", "holdings", "account"):
            st.markdown(
                "<div style='font-size:0.68rem;color:#6e7681;font-weight:600;"
                "text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px;'>"
                "Filter by Account</div>",
                unsafe_allow_html=True,
            )
            display_names = {
                aid: (cfg_map[aid].display_name if aid in cfg_map else aid)
                for aid in account_ids
            }
            options = ["All Accounts"] + account_ids
            labels  = ["All Accounts"] + [display_names[a] for a in account_ids]

            sel = st.selectbox(
                "Account", labels,
                key="account_selector",
                label_visibility="collapsed",
            )
            if sel != "All Accounts":
                selected_account = options[labels.index(sel)]

        # ── Account health panel ──────────────────────────────────────
        st.markdown(
            "<div style='font-size:0.68rem;color:#6e7681;font-weight:600;"
            "text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px;'>"
            "Accounts</div>",
            unsafe_allow_html=True,
        )

        if all_configured:
            for aid in all_configured:
                h = health.get(aid)
                cfg = cfg_map.get(aid)
                name   = (h.display_name if h else None) or (cfg.display_name if cfg else aid)
                broker = ""
                if cfg:
                    broker = cfg.metadata.get("original_broker", cfg.broker).capitalize()
                elif h:
                    broker = h.broker.capitalize()

                if h and h.is_active:
                    dot   = "<span style='color:#3fb950;'>●</span>"
                    label_color = "#c9d1d9"
                    error_html  = ""
                elif h and h.status == "auth_failed":
                    dot   = "<span style='color:#f85149;'>●</span>"
                    label_color = "#8b949e"
                    short_err   = (h.error or "Auth failed")[:48]
                    error_html  = (
                        f"<div style='font-size:0.6rem;color:#f85149;margin-top:2px;"
                        f"line-height:1.3;'>{short_err}</div>"
                    )
                elif h and h.status == "error":
                    dot   = "<span style='color:#f0883e;'>●</span>"
                    label_color = "#8b949e"
                    short_err   = (h.error or "Unexpected error")[:48]
                    error_html  = (
                        f"<div style='font-size:0.6rem;color:#f0883e;margin-top:2px;"
                        f"line-height:1.3;'>{short_err}</div>"
                    )
                else:
                    # aid is active (no health object means it was not tracked, treat as active)
                    dot   = "<span style='color:#3fb950;'>●</span>"
                    label_color = "#c9d1d9"
                    error_html  = ""

                broker_badge = (
                    f"<span style='font-size:0.6rem;color:#6e7681;background:#30363d;"
                    f"padding:1px 5px;border-radius:8px;'>{broker}</span>"
                    if broker else ""
                )

                st.markdown(
                    f"<div style='background:#21262d;border-radius:5px;padding:6px 8px;"
                    f"margin-bottom:4px;'>"
                    f"<div style='display:flex;justify-content:space-between;align-items:center;'>"
                    f"<span style='font-size:0.73rem;color:{label_color};'>{dot} {name}</span>"
                    f"{broker_badge}</div>"
                    f"{error_html}</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                "<div style='font-size:0.72rem;color:#6e7681;padding:6px;'>No accounts configured.</div>",
                unsafe_allow_html=True,
            )

        # ── Failed-account help (live mode only) ──────────────────────
        failed = [aid for aid, h in health.items() if not h.is_active]
        if failed and settings.app_mode == "live":
            with st.expander(f"⚠ {len(failed)} account(s) failed", expanded=False):
                st.markdown(
                    "<div style='font-size:0.72rem;color:#8b949e;line-height:1.5;'>"
                    "Common fixes:<br>"
                    "1. Generate a new access token at <strong>kite.zerodha.com</strong><br>"
                    "2. Update <code>ZERODHA_&lt;TAG&gt;_ACCESS_TOKEN</code> in <code>.env</code><br>"
                    "3. Restart the dashboard"
                    "</div>",
                    unsafe_allow_html=True,
                )

        st.divider()

        # ── Mode badge ────────────────────────────────────────────────
        if settings.app_mode == "live":
            st.markdown(
                "<div style='text-align:center;'>"
                "<span style='background:#238636;color:#fff;font-size:0.7rem;font-weight:700;"
                "padding:3px 10px;border-radius:10px;letter-spacing:0.08em;'>● LIVE</span>"
                "</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div style='text-align:center;'>"
                "<span style='background:#6e7681;color:#fff;font-size:0.7rem;font-weight:700;"
                "padding:3px 10px;border-radius:10px;letter-spacing:0.08em;'>◎ DEMO MODE</span>"
                "</div>",
                unsafe_allow_html=True,
            )

        st.markdown(
            "<div style='font-size:0.62rem;color:#30363d;text-align:center;margin-top:12px;'>"
            "Read-only &nbsp;&middot;&nbsp; No order execution</div>",
            unsafe_allow_html=True,
        )

    return view, selected_account
