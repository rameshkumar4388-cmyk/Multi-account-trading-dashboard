"""
Portfolio Dashboard — main entry point.

Run with:  streamlit run main.py

Architecture:
  Streamlit reruns this script on every interaction/autorefresh.
  Services are cached with @st.cache_resource so they persist across reruns
  (single instance per server process, shared by all sessions).
  The MockFeed background thread runs continuously inside MarketDataManager.
"""
from __future__ import annotations

import sys
import os

# Ensure repo root is on sys.path so all imports resolve correctly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

# ── Page config must be first Streamlit call ──────────────────────────
st.set_page_config(
    page_title="Portfolio Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": None,
        "Report a bug": None,
        "About": "Portfolio Dashboard — read-only multi-account trading monitor.",
    },
)

# ── Deferred imports (after sys.path setup) ───────────────────────────
from config.settings import load_settings
from services.account_service import AccountService
from services.aggregation_service import AggregationService
from services.market_data_service import MarketDataService
from services.portfolio_service import PortfolioService
from ui.theme import apply_theme
from ui.components.header import render_header
from ui.components.sidebar import render_sidebar


# ── Singleton services (survive Streamlit reruns) ─────────────────────

@st.cache_resource
def _get_settings():
    return load_settings()


@st.cache_resource
def _get_account_service(_settings):
    svc = AccountService(_settings)
    svc.initialize()
    return svc


@st.cache_resource
def _get_market_data_service(_settings, _account_svc):
    svc = MarketDataService(_settings)
    symbols = _account_svc.get_all_symbols()
    svc.initialize(symbols)
    return svc


@st.cache_resource
def _get_portfolio_service(_account_svc, _md_svc):
    return PortfolioService(_account_svc, _md_svc)


@st.cache_resource
def _get_aggregation_service(_account_svc, _portfolio_svc):
    return AggregationService(_account_svc, _portfolio_svc)


# ── Bootstrap ─────────────────────────────────────────────────────────

def main():
    apply_theme()

    settings = _get_settings()
    account_svc = _get_account_service(settings)
    md_svc = _get_market_data_service(settings, account_svc)
    portfolio_svc = _get_portfolio_service(account_svc, md_svc)
    aggregation_svc = _get_aggregation_service(account_svc, portfolio_svc)

    account_ids     = account_svc.list_account_ids()
    account_health  = account_svc.get_health()

    # ── Sidebar navigation ────────────────────────────────────────────
    view, selected_account = render_sidebar(settings, account_ids, account_health)

    # ── Combined metrics for header ───────────────────────────────────
    try:
        metrics = aggregation_svc.get_combined_metrics()
        net_worth = metrics.get("net_worth", 0.0)
        day_pnl = metrics.get("day_pnl", 0.0)
    except Exception:
        net_worth = 0.0
        day_pnl = 0.0

    render_header(settings.app_mode, net_worth, day_pnl)

    # ── Page routing ──────────────────────────────────────────────────
    if view == "terminal":
        from ui.pages.combined_dashboard import render
        render(aggregation_svc, md_svc)

    elif view == "account":
        from ui.pages.account_dashboard import render
        render(aggregation_svc, portfolio_svc, selected_account)

    elif view == "holdings":
        from ui.pages.holdings_page import render
        render(aggregation_svc, portfolio_svc, selected_account)

    elif view == "positions":
        from ui.pages.positions_page import render
        render(aggregation_svc, portfolio_svc, selected_account)

    elif view == "exposure":
        from ui.pages.exposure_page import render
        render(aggregation_svc, portfolio_svc, selected_account)

    # ── Auto-refresh ──────────────────────────────────────────────────
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(
            interval=settings.ui_refresh_interval * 1000,
            limit=None,
            key="dashboard_autorefresh",
        )
    except ImportError:
        # Fallback: manual refresh button in sidebar
        with st.sidebar:
            st.divider()
            if st.button("🔄 Refresh", use_container_width=True):
                st.rerun()
            st.caption(
                "Install streamlit-autorefresh for auto-refresh:\n"
                "`pip install streamlit-autorefresh`"
            )


if __name__ == "__main__":
    main()
