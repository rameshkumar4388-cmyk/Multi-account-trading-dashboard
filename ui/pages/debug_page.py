"""
Runtime debug trace page.

Shows the complete data pipeline from Zerodha API → adapter → portfolio service
→ aggregation → UI-bound values. Use this to identify exactly where
correct API values become incorrect display values.

Access via sidebar: 🔬 Debug Trace
"""
from __future__ import annotations

import copy
import inspect
import sys
import time
from datetime import datetime
from typing import Optional

import streamlit as st


def render(account_svc, portfolio_svc, aggregation_svc, md_svc, settings):

    st.markdown(
        "<div style='font-size:1.1rem;font-weight:700;color:#e6edf3;margin-bottom:4px;'>"
        "Runtime Debug Trace</div>"
        "<div style='font-size:0.78rem;color:#8b949e;margin-bottom:16px;'>"
        "Traces every data hop: Zerodha API → adapter → service → UI values. "
        "Use this to isolate data corruption."
        "</div>",
        unsafe_allow_html=True,
    )

    # ── Cache / Service identity ──────────────────────────────────────
    with st.expander("1. Cache & Module Identity", expanded=True):
        _render_service_identity(account_svc, portfolio_svc, aggregation_svc)

    # ── Per-account adapter trace ─────────────────────────────────────
    account_ids = account_svc.list_account_ids()
    if not account_ids:
        st.error("No active accounts — check authentication status.")
        return

    selected = st.selectbox(
        "Inspect account",
        account_ids,
        format_func=lambda x: account_svc._account_configs.get(x, type("C",(),{"display_name":x})()).display_name,
        key="debug_account_select",
    )

    col_a, col_b = st.columns(2)
    with col_a:
        refresh_raw = st.button("Call adapter.get_holdings() live", key="debug_raw")
    with col_b:
        if st.button("Clear All @st.cache_resource Caches", key="debug_clear_cache", type="primary"):
            st.cache_resource.clear()
            st.success("All caches cleared. Page will re-initialize on next render.")
            st.rerun()

    # ── Layer 1: Raw Zerodha API response ─────────────────────────────
    with st.expander("2. Raw Zerodha API (kite.holdings / kite.positions / kite.margins)", expanded=True):
        _render_raw_api(account_svc, selected, refresh_raw)

    # ── Layer 2: Adapter output (Holding objects) ─────────────────────
    with st.expander("3. Adapter output — Holding objects after normalisation", expanded=True):
        _render_adapter_holdings(account_svc, selected, refresh_raw)

    # ── Layer 3: PortfolioService (with LTP injection) ────────────────
    with st.expander("4. PortfolioService.get_holdings() — after LTP injection", expanded=True):
        _render_portfolio_holdings(portfolio_svc, selected)

    # ── Layer 4: AccountSummary ───────────────────────────────────────
    with st.expander("5. AccountSummary — all computed fields", expanded=True):
        _render_account_summary(portfolio_svc, selected)

    # ── Layer 5: Aggregated metrics ───────────────────────────────────
    with st.expander("6. AggregationService.get_combined_metrics() — final UI values", expanded=True):
        _render_aggregated_metrics(aggregation_svc)

    # ── Market data ───────────────────────────────────────────────────
    with st.expander("7. Market data feed — LTP for key symbols", expanded=False):
        _render_market_data(md_svc, portfolio_svc, selected)


# ── Section renderers ─────────────────────────────────────────────────

def _render_service_identity(account_svc, portfolio_svc, aggregation_svc):
    import pandas as pd

    rows = []
    for name, obj in [
        ("AccountService",    account_svc),
        ("PortfolioService",  portfolio_svc),
        ("AggregationService",aggregation_svc),
    ]:
        cls  = type(obj)
        try:
            path = inspect.getfile(cls)
        except Exception:
            path = "unknown"
        rows.append({
            "Service":   name,
            "Class":     cls.__name__,
            "Object id": id(obj),
            "Module file": path,
        })

    # Adapter
    for aid, adapter in account_svc._adapters.items():
        cls  = type(adapter)
        try:
            path = inspect.getfile(cls)
        except Exception:
            path = "unknown"
        rows.append({
            "Service":   f"Adapter [{aid}]",
            "Class":     cls.__name__,
            "Object id": id(adapter),
            "Module file": path,
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown(
        "<div style='font-size:0.72rem;color:#6e7681;margin-top:6px;'>"
        "<strong>Note:</strong> If 'Object id' is the same across page refreshes, "
        "the service is cached (normal). If 'Module file' points to an unexpected path, "
        "the wrong module version is loaded — clear caches and restart."
        "</div>",
        unsafe_allow_html=True,
    )

    # Schema class identity check
    from schemas.holding import Holding
    from schemas.account import AccountSummary, MarginInfo
    st.code(
        f"schemas.holding.Holding     @ {inspect.getfile(Holding)}\n"
        f"schemas.account.AccountSummary @ {inspect.getfile(AccountSummary)}\n"
        f"schemas.account.MarginInfo   @ {inspect.getfile(MarginInfo)}",
        language="text",
    )


def _render_raw_api(account_svc, account_id: str, force: bool):
    """Call kite.holdings(), kite.positions(), kite.margins() directly and show raw dicts."""
    kite_sessions = account_svc.get_kite_sessions()
    kite = kite_sessions.get(account_id)

    if kite is None:
        adapter = account_svc.get_adapter(account_id)
        if adapter and hasattr(adapter, "_sessions"):
            kite = adapter._sessions.get(account_id)

    if kite is None:
        st.warning(
            f"No live KiteConnect session for '{account_id}'. "
            "This account may be using mock mode or auth failed."
        )
        return

    tab_hold, tab_pos, tab_margin = st.tabs(["holdings()", "positions()", "margins()"])

    with tab_hold:
        try:
            t0 = time.monotonic()
            raw = kite.holdings()
            elapsed = (time.monotonic() - t0) * 1000

            st.caption(f"kite.holdings() returned {len(raw)} rows in {elapsed:.0f} ms")

            if not raw:
                st.info("API returned empty holdings list.")
                return

            # Show first 5 rows with the critical quantity fields highlighted
            import pandas as pd
            rows = []
            for r in raw[:10]:
                qty       = r.get("quantity", "N/A")
                t1_qty    = r.get("t1_quantity", "N/A")
                used_qty  = r.get("used_quantity", "N/A")
                try:
                    total = int(qty or 0) + int(t1_qty or 0) + int(used_qty or 0)
                except Exception:
                    total = "?"
                rows.append({
                    "symbol":         r.get("tradingsymbol"),
                    "quantity":       qty,
                    "t1_quantity":    t1_qty,
                    "used_quantity":  used_qty,
                    "total_calc":     total,
                    "last_price":     r.get("last_price"),
                    "average_price":  r.get("average_price"),
                    "close_price":    r.get("close_price"),
                    "day_change":     r.get("day_change"),
                    "pnl":            r.get("pnl"),
                    "collateral_type":r.get("collateral_type", ""),
                })
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)

            if len(raw) > 10:
                st.caption(f"Showing first 10 of {len(raw)} holdings.")

            # Sanity checks
            zero_qty = [r.get("tradingsymbol") for r in raw
                        if int(r.get("quantity", 0) or 0) == 0
                        and int(r.get("t1_quantity", 0) or 0) == 0
                        and int(r.get("used_quantity", 0) or 0) == 0]
            if zero_qty:
                st.warning(f"Holdings with ALL qty fields = 0 (will be skipped): {zero_qty}")

            t1_only = [r.get("tradingsymbol") for r in raw
                       if int(r.get("quantity", 0) or 0) == 0
                       and int(r.get("t1_quantity", 0) or 0) > 0]
            if t1_only:
                st.info(f"T+1 holdings (only t1_quantity > 0): {t1_only}")

            pledged = [r.get("tradingsymbol") for r in raw
                       if int(r.get("used_quantity", 0) or 0) > 0]
            if pledged:
                st.info(f"Pledged holdings (used_quantity > 0): {pledged}")

        except Exception as exc:
            st.error(f"kite.holdings() failed: {exc}")

    with tab_pos:
        try:
            t0 = time.monotonic()
            raw_pos = kite.positions()
            elapsed = (time.monotonic() - t0) * 1000
            net = raw_pos.get("net", [])
            st.caption(f"kite.positions() returned {len(net)} net positions in {elapsed:.0f} ms")

            if not net:
                st.info("No open positions.")
            else:
                import pandas as pd
                rows = []
                for r in net:
                    rows.append({
                        "symbol":       r.get("tradingsymbol"),
                        "qty":          r.get("quantity"),
                        "pnl":          r.get("pnl"),
                        "m2m":          r.get("m2m"),          # day M2M — correct field name
                        "day_m2m":      r.get("day_m2m", "MISSING"),  # should NOT exist
                        "unrealised":   r.get("unrealised"),
                        "realised":     r.get("realised"),
                        "last_price":   r.get("last_price"),
                        "average_price":r.get("average_price"),
                    })
                df = pd.DataFrame(rows)
                st.dataframe(df, use_container_width=True, hide_index=True)

        except Exception as exc:
            st.error(f"kite.positions() failed: {exc}")

    with tab_margin:
        try:
            t0 = time.monotonic()
            funds = kite.margins()
            elapsed = (time.monotonic() - t0) * 1000
            st.caption(f"kite.margins() returned in {elapsed:.0f} ms")

            eq = funds.get("equity", {})
            avail   = eq.get("available", {})
            utilised = eq.get("utilised", {})

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**available**")
                st.json(avail)
            with col2:
                st.markdown("**utilised**")
                st.json(utilised)

            st.markdown(
                f"**Key values:** "
                f"cash={avail.get('cash')} | "
                f"collateral={avail.get('collateral')} | "
                f"live_balance={avail.get('live_balance')} | "
                f"debits={utilised.get('debits')}"
            )
        except Exception as exc:
            st.error(f"kite.margins() failed: {exc}")


def _render_adapter_holdings(account_svc, account_id: str, force: bool):
    """Call adapter.get_holdings() directly and inspect the resulting Holding objects."""
    adapter = account_svc.get_adapter(account_id)
    if not adapter:
        st.warning(f"No adapter for '{account_id}'")
        return

    try:
        t0 = time.monotonic()
        holdings = adapter.get_holdings(account_id)
        elapsed  = (time.monotonic() - t0) * 1000
    except Exception as exc:
        st.error(f"adapter.get_holdings() raised: {exc}")
        return

    st.caption(
        f"adapter.get_holdings('{account_id}') → {len(holdings)} Holding objects in {elapsed:.0f} ms"
    )

    if not holdings:
        st.warning("Adapter returned 0 holdings. Check the raw API tab to see if the API itself returned data.")
        return

    import pandas as pd
    rows = []
    for h in holdings:
        rows.append({
            "symbol":        h.symbol,
            "quantity":      h.quantity,
            "avg_price":     h.avg_price,
            "ltp":           h.ltp,
            "invested_val":  h.invested_value,
            "current_val":   h.current_value,
            "pnl":           h.pnl,
            "pnl_pct":       h.pnl_pct,
            "day_change":    h.day_change,
            "day_chg_pct":   h.day_change_pct,
        })
    df = pd.DataFrame(rows)

    def _col(val):
        if isinstance(val, (int, float)):
            return "color: #3fb950" if val >= 0 else "color: #f85149"
        return ""

    styled = (
        df.style
        .map(_col, subset=["pnl", "pnl_pct", "day_change"])
        .format({"avg_price": "{:.2f}", "ltp": "{:.2f}", "invested_val": "{:,.0f}",
                 "current_val": "{:,.0f}", "pnl": "{:+,.0f}", "pnl_pct": "{:+.2f}%",
                 "day_change": "{:.2f}", "day_chg_pct": "{:.2f}%"})
        .set_properties(**{"background-color": "#161b22", "color": "#e6edf3", "font-size": "12px"})
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)

    total_invested = sum(h.invested_value for h in holdings)
    total_current  = sum(h.current_value  for h in holdings)
    total_pnl      = sum(h.pnl            for h in holdings)
    st.markdown(
        f"**Adapter totals:** "
        f"invested=**{total_invested:,.0f}** | "
        f"current=**{total_current:,.0f}** | "
        f"pnl=**{total_pnl:+,.0f}**"
    )

    ltp_zero = [h.symbol for h in holdings if h.ltp == 0]
    if ltp_zero:
        st.warning(
            f"Holdings with ltp=0 (showing at cost basis): {ltp_zero}. "
            "This is normal pre-market or if the quote feed hasn't delivered a tick yet."
        )


def _render_portfolio_holdings(portfolio_svc, account_id: str):
    """Show portfolio_service.get_holdings() output and cache state."""
    # Cache state
    cache_entry = portfolio_svc._holdings_cache.get(account_id)
    if cache_entry:
        _, fetched_at = cache_entry
        age = time.monotonic() - fetched_at
        ttl = portfolio_svc._ttl
        st.caption(
            f"Cache: fetched {age:.0f}s ago | TTL={ttl}s | "
            f"{'STALE (next call will refresh)' if age > ttl else 'FRESH'}"
        )
    else:
        st.caption("Cache: no entry — will be fetched on next call")

    try:
        holdings = portfolio_svc.get_holdings(account_id)
    except Exception as exc:
        st.error(f"portfolio_svc.get_holdings() raised: {exc}")
        return

    st.caption(f"portfolio_svc.get_holdings('{account_id}') → {len(holdings)} holdings (after LTP injection)")

    if not holdings:
        st.warning("PortfolioService returned 0 holdings.")
        return

    import pandas as pd
    rows = []
    for h in holdings:
        rows.append({
            "symbol":       h.symbol,
            "quantity":     h.quantity,
            "ltp":          h.ltp,
            "invested_val": h.invested_value,
            "current_val":  h.current_value,
            "pnl":          h.pnl,
            "day_change":   h.day_change,
        })
    df = pd.DataFrame(rows)

    def _col(val):
        if isinstance(val, (int, float)):
            return "color: #3fb950" if val >= 0 else "color: #f85149"
        return ""

    st.dataframe(
        df.style.map(_col, subset=["pnl","day_change"])
        .format({"ltp": "{:.2f}", "invested_val": "{:,.0f}",
                 "current_val": "{:,.0f}", "pnl": "{:+,.0f}", "day_change": "{:.2f}"})
        .set_properties(**{"background-color": "#161b22", "color": "#e6edf3", "font-size": "12px"}),
        use_container_width=True, hide_index=True,
    )

    tc = sum(h.current_value for h in holdings)
    ti = sum(h.invested_value for h in holdings)
    tp = sum(h.pnl for h in holdings)
    st.markdown(f"**Service totals:** invested=**{ti:,.0f}** | current=**{tc:,.0f}** | pnl=**{tp:+,.0f}**")


def _render_account_summary(portfolio_svc, account_id: str):
    """Show every field of the AccountSummary for this account."""
    try:
        s = portfolio_svc.get_account_summary(account_id)
    except Exception as exc:
        st.error(f"get_account_summary() raised: {exc}")
        return

    if not s:
        st.warning("get_account_summary() returned None")
        return

    import pandas as pd

    fields = [
        ("display_name",          s.display_name),
        ("total_holdings_value",  s.total_holdings_value),
        ("total_invested_value",  s.total_invested_value),
        ("holdings_pnl",          s.holdings_pnl),
        ("holdings_pnl_pct",      s.holdings_pnl_pct),
        ("positions_pnl",         s.positions_pnl),
        ("realised_pnl",          s.realised_pnl),
        ("day_pnl",               s.day_pnl),
        ("available_cash",        s.available_cash),
        ("net_available",         s.net_available),
        ("used_margin",           s.used_margin),
        ("total_collateral",      s.total_collateral),
        ("net_worth",             s.net_worth),
        ("total_pnl [property]",  s.total_pnl),
    ]

    df = pd.DataFrame(fields, columns=["Field", "Value"])

    def _color(val):
        if isinstance(val, float) and val != 0:
            return "color: #3fb950" if val > 0 else "color: #f85149"
        return "color: #e6edf3"

    st.dataframe(
        df.style.map(_color, subset=["Value"])
        .set_properties(**{"background-color": "#161b22", "color": "#e6edf3", "font-size": "13px"}),
        use_container_width=True, hide_index=True,
    )

    # Sanity: if holdings_value == 0 but there are holdings → LTP issue
    if s.total_holdings_value == 0 and s.total_invested_value > 0:
        st.error(
            "⚠ total_holdings_value=0 but total_invested_value>0. "
            "This means all LTPs are 0. Either: market is closed and the API returned "
            "last_price=0, or the quote feed hasn't delivered prices yet. "
            "The 'cost-basis fallback' in schemas/holding.py should prevent this — "
            "check if the schema file has been updated (Layer 1 → Module file)."
        )
    if s.net_worth == s.available_cash and s.total_holdings_value > 0:
        st.error(
            "⚠ net_worth == available_cash — holdings are being excluded. "
            "Likely total_holdings_value is 0 (see above)."
        )


def _render_aggregated_metrics(aggregation_svc):
    """Show the final metrics dict that the homepage consumes."""
    try:
        metrics = aggregation_svc.get_combined_metrics()
    except Exception as exc:
        st.error(f"get_combined_metrics() raised: {exc}")
        return

    import pandas as pd

    expected_keys = [
        "net_worth", "total_holdings_value", "total_invested_value",
        "holdings_pnl", "holdings_pnl_pct", "positions_pnl", "total_pnl",
        "day_pnl", "available_cash", "net_available", "used_margin",
        "total_collateral", "account_count",
    ]

    rows = []
    for k in expected_keys:
        present = k in metrics
        rows.append({
            "Key":     k,
            "Value":   metrics.get(k, "MISSING"),
            "Present": "✓" if present else "✗ MISSING",
        })

    df = pd.DataFrame(rows)

    def _pres(val):
        return "color: #3fb950" if val == "✓" else "color: #f85149"

    st.dataframe(
        df.style.map(_pres, subset=["Present"])
        .set_properties(**{"background-color": "#161b22", "color": "#e6edf3", "font-size": "13px"}),
        use_container_width=True, hide_index=True,
    )


def _render_market_data(md_svc, portfolio_svc, account_id: str):
    """Show live LTP values for holdings in this account."""
    try:
        holdings = portfolio_svc.get_holdings(account_id)
    except Exception:
        holdings = []

    symbols = [h.symbol for h in holdings][:15]
    if not symbols:
        st.info("No holdings to check prices for.")
        return

    import pandas as pd
    rows = []
    for sym in symbols:
        ltp     = md_svc.get_ltp(sym)
        change  = md_svc.get_change(sym)
        chg_pct = md_svc.get_change_pct(sym)
        rows.append({
            "symbol":       sym,
            "ltp_from_md":  ltp if ltp is not None else "None (no data)",
            "change":       change,
            "change_pct":   chg_pct,
            "feed_running": md_svc.is_running(),
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    no_price = [r["symbol"] for r in rows if r["ltp_from_md"] in (None, 0, "None (no data)")]
    if no_price:
        st.warning(
            f"MarketDataService returned no price for: {no_price}. "
            "These holdings will show at cost-basis value until the quote feed delivers a price."
        )
