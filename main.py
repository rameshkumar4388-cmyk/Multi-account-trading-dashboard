"""
Portfolio Dashboard — main entry point.

Run with:  streamlit run main.py

Architecture:
  Streamlit reruns this script on every interaction/autorefresh.
  Services are cached with @st.cache_resource so they persist across reruns
  (single instance per server process, shared by all sessions).

OAuth redirect handling:
  Zerodha redirects to this URL after login:
    http://<host>:8501?request_token=<token>&action=login&status=success
  main() detects this on every render and auto-exchanges the token
  before routing to any page.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

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

from config.settings import load_settings
from services.account_service import AccountService
from services.aggregation_service import AggregationService
from services.market_data_service import MarketDataService
from services.portfolio_service import PortfolioService
from ui.theme import apply_theme
from ui.components.header import render_header
from ui.components.sidebar import render_sidebar


# ── Singleton services ────────────────────────────────────────────────

@st.cache_resource
def _get_settings():
    return load_settings()


@st.cache_resource
def _get_database(_settings):
    from database.db import Database
    return Database(_settings.db_path)


@st.cache_resource
def _get_account_service(_settings, _db):
    svc = AccountService(_settings, db=_db)
    svc.initialize()
    return svc


@st.cache_resource
def _get_market_data_service(_settings, _account_svc):
    return MarketDataService(_settings, _account_svc)


@st.cache_resource
def _get_portfolio_service(_account_svc, _md_svc):
    return PortfolioService(_account_svc, _md_svc)


@st.cache_resource
def _get_aggregation_service(_account_svc, _portfolio_svc):
    return AggregationService(_account_svc, _portfolio_svc)


def _build_quote_symbols(aggregation_svc) -> list:
    """
    Build the minimal quote symbol list for MarketDataService.
    Always includes NIFTY and BANKNIFTY.
    Adds the underlying for each open option position (CE/PE, quantity != 0).
    Holdings are excluded — they carry broker-provided LTP and P&L directly.
    """
    symbols: set = {"NIFTY", "BANKNIFTY"}
    try:
        for p in aggregation_svc.get_combined_positions():
            if p.quantity != 0 and p.instrument_type in ("CE", "PE") and p.underlying:
                symbols.add(p.underlying)
    except Exception:
        pass
    return list(symbols)


# ── Bootstrap ─────────────────────────────────────────────────────────

def main():
    apply_theme()

    settings     = _get_settings()
    db           = _get_database(settings)
    account_svc  = _get_account_service(settings, db)
    md_svc       = _get_market_data_service(settings, account_svc)
    portfolio_svc    = _get_portfolio_service(account_svc, md_svc)
    aggregation_svc  = _get_aggregation_service(account_svc, portfolio_svc)

    # ── OAuth redirect handling (runs before sidebar / page routing) ──
    # When Zerodha redirects back after login, st.query_params contains
    # request_token, action, status. We handle it here on EVERY rerun
    # so the token is captured even if the user lands on a different page.
    if settings.app_mode == "live":
        params = st.query_params
        if params.get("status") == "success" and params.get("request_token"):
            from ui.pages.auth_page import handle_oauth_redirect
            processed = handle_oauth_redirect(account_svc, settings)
            if processed:
                # Invalidate portfolio cache for the refreshed account
                target = st.session_state.get("auth_target_account")
                if target:
                    portfolio_svc.invalidate(target)
                # Clear URL params to avoid re-processing on next render
                st.query_params.clear()
                st.rerun()

    # ── Navigation ────────────────────────────────────────────────────
    account_ids    = account_svc.list_account_ids()
    account_health = account_svc.get_health()

    view, selected_account = render_sidebar(settings, account_ids, account_health)

    # ── Fresh quote snapshot ──────────────────────────────────────────
    # Build symbol set (populates portfolio TTL cache as a side effect),
    # then fetch all prices in ONE batched kite.ltp() call via SP7086.
    # Must happen before get_combined_metrics() so LTP injection sees
    # fresh quotes when portfolio_svc recomputes summaries from cache.
    md_svc.refresh(_build_quote_symbols(aggregation_svc))

    # ── Header ────────────────────────────────────────────────────────
    try:
        metrics   = aggregation_svc.get_combined_metrics()
        net_worth = metrics.get("net_worth", 0.0)
        day_pnl   = metrics.get("day_pnl", 0.0)
    except Exception:
        net_worth = 0.0
        day_pnl   = 0.0

    render_header(settings.app_mode)

    # ── Page routing ──────────────────────────────────────────────────
    if view == "terminal":
        from ui.pages.combined_dashboard import render
        render(aggregation_svc, md_svc, portfolio_svc)

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

    elif view == "auth":
        from ui.pages.auth_page import render
        render(account_svc, settings, portfolio_svc)

    elif view == "debug":
        from ui.pages.debug_page import render
        render(account_svc, portfolio_svc, aggregation_svc, md_svc, settings)

    # ── Auto-refresh ──────────────────────────────────────────────────
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(
            interval=settings.ui_refresh_interval * 1000,
            limit=None,
            key="dashboard_autorefresh",
        )
    except ImportError:
        with st.sidebar:
            st.divider()
            if st.button("🔄 Refresh", use_container_width=True):
                st.rerun()


if __name__ == "__main__":
    main()
