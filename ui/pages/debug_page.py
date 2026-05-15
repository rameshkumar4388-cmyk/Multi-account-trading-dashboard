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

    # ── MF Holdings trace ─────────────────────────────────────────────
    with st.expander("2b. MF Holdings — raw payload + P&L arithmetic trace", expanded=True):
        _render_mf_trace(account_svc, portfolio_svc, selected, refresh_raw)

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

    # ── 5paisa raw API investigation ──────────────────────────────────
    cfg = account_svc._account_configs.get(selected)
    if cfg and cfg.broker == "fivepaisa":
        with st.expander("8. 5paisa raw API investigation (positions_day / holdings)", expanded=True):
            _render_fivepaisa_raw(account_svc, selected)


# ── Section renderers ─────────────────────────────────────────────────

def _render_mf_trace(account_svc, portfolio_svc, account_id: str, force: bool):
    """
    Show exact kite.mf_holdings() payload fields and arithmetic trace so we can
    verify quantity semantics (is 'quantity' total or free-only?) and confirm
    there is no double-counting in the final P&L subtotals.
    """
    import pandas as pd

    kite_sessions = account_svc.get_kite_sessions()
    kite = kite_sessions.get(account_id)
    if kite is None:
        adapter = account_svc.get_adapter(account_id)
        if adapter and hasattr(adapter, "_sessions"):
            kite = adapter._sessions.get(account_id)

    # ── Raw mf_holdings() payload ─────────────────────────────────────
    st.markdown("**Raw `kite.mf_holdings()` payload** (all fields, exact API values)")
    if kite is None:
        st.warning("No live KiteConnect session — cannot call mf_holdings().")
    else:
        try:
            import time as _time
            t0 = _time.monotonic()
            raw_mf = kite.mf_holdings()
            elapsed = (_time.monotonic() - t0) * 1000
            st.caption(f"kite.mf_holdings() returned {len(raw_mf)} rows in {elapsed:.0f} ms")

            if raw_mf:
                # Show every field of every row
                mf_rows = []
                for r in raw_mf:
                    mf_rows.append({k: v for k, v in r.items()})
                df_raw = pd.DataFrame(mf_rows)
                st.dataframe(df_raw, use_container_width=True, hide_index=True)

                # ── Arithmetic trace: what do these numbers mean? ──────
                st.markdown("**Arithmetic trace per MF holding**")
                trace_rows = []
                for r in raw_mf:
                    qty       = float(r.get("quantity", 0) or 0)
                    pledged   = float(r.get("pledged_quantity", 0) or 0)
                    t1        = float(r.get("t1_quantity", 0) or 0)
                    avg       = float(r.get("average_price", 0) or 0)
                    nav       = float(r.get("last_price", 0) or 0)
                    api_pnl   = float(r.get("pnl", 0) or 0)

                    # Hypothesis A: quantity = total (pledged included)
                    total_a   = qty + t1
                    pnl_a     = round(total_a * (nav - avg), 2)

                    # Hypothesis B: quantity = free only, pledged is additive
                    total_b   = qty + pledged + t1
                    pnl_b     = round(total_b * (nav - avg), 2)

                    trace_rows.append({
                        "fund":           r.get("tradingsymbol", r.get("fund", "?")),
                        "qty(API)":       qty,
                        "pledged(API)":   pledged,
                        "t1(API)":        t1,
                        "avg_price":      avg,
                        "last_price(NAV)":nav,
                        "api_pnl":        api_pnl,
                        "HypA qty+t1":    total_a,
                        "HypA pnl":       pnl_a,
                        "HypB qty+plg+t1":total_b,
                        "HypB pnl":       pnl_b,
                        "matches_api_pnl":"A" if abs(pnl_a - api_pnl) < 1 else ("B" if abs(pnl_b - api_pnl) < 1 else "neither"),
                    })
                df_trace = pd.DataFrame(trace_rows)

                def _cp(v):
                    if isinstance(v, float): return "color:#3fb950" if v >= 0 else "color:#f85149"
                    return ""

                st.dataframe(
                    df_trace.style.map(_cp, subset=["api_pnl","HypA pnl","HypB pnl"])
                    .format({"qty(API)": "{:.4f}", "pledged(API)": "{:.4f}",
                             "avg_price": "{:.4f}", "last_price(NAV)": "{:.4f}",
                             "api_pnl": "{:+,.2f}", "HypA pnl": "{:+,.2f}", "HypB pnl": "{:+,.2f}",
                             "HypA qty+t1": "{:.4f}", "HypB qty+plg+t1": "{:.4f}"}),
                    use_container_width=True, hide_index=True,
                )
                st.caption(
                    "HypA: quantity = TOTAL units (pledged included) → use qty+t1 only. "
                    "HypB: quantity = free-only → use qty+pledged+t1. "
                    "'matches_api_pnl' shows which hypothesis matches the API's own pnl field."
                )
            else:
                st.info("mf_holdings() returned empty — no MF holdings for this account.")

        except Exception as exc:
            st.error(f"mf_holdings() failed: {exc}")

    # ── P&L subtotal breakdown (from portfolio_service cache) ─────────
    st.markdown("---")
    st.markdown("**Portfolio P&L arithmetic trace** (equity subtotal · MF subtotal · combined)")
    try:
        holdings = portfolio_svc.get_holdings(account_id)
        eq_h  = [h for h in holdings if h.instrument_type != "MF"]
        mf_h  = [h for h in holdings if h.instrument_type == "MF"]

        eq_inv  = sum(h.invested_value for h in eq_h)
        eq_cur  = sum(h.current_value  for h in eq_h)
        eq_pnl  = sum(h.pnl            for h in eq_h)

        mf_inv  = sum(h.invested_value for h in mf_h)
        mf_cur  = sum(h.current_value  for h in mf_h)
        mf_pnl  = sum(h.pnl            for h in mf_h)

        tot_inv = eq_inv + mf_inv
        tot_cur = eq_cur + mf_cur
        tot_pnl = eq_pnl + mf_pnl

        rows = [
            {"Category": "Equity holdings",   "Count": len(eq_h),  "Invested": eq_inv,  "Current": eq_cur,  "PnL": eq_pnl},
            {"Category": "MF holdings",        "Count": len(mf_h),  "Invested": mf_inv,  "Current": mf_cur,  "PnL": mf_pnl},
            {"Category": "COMBINED",           "Count": len(holdings), "Invested": tot_inv, "Current": tot_cur, "PnL": tot_pnl},
        ]
        df_sub = pd.DataFrame(rows)

        def _cp2(v):
            if isinstance(v, float): return "color:#3fb950" if v >= 0 else "color:#f85149"
            return ""

        st.dataframe(
            df_sub.style.map(_cp2, subset=["PnL"])
            .format({"Invested": "{:,.0f}", "Current": "{:,.0f}", "PnL": "{:+,.0f}"}),
            use_container_width=True, hide_index=True,
        )

        # Per-MF detail
        if mf_h:
            st.markdown("**Per-MF holding detail**")
            mf_detail = []
            for h in mf_h:
                mf_detail.append({
                    "symbol":    h.symbol,
                    "qty":       h.quantity,
                    "avg_price": h.avg_price,
                    "nav(ltp)":  h.ltp,
                    "invested":  h.invested_value,
                    "current":   h.current_value,
                    "pnl":       h.pnl,
                    "formula":   f"{h.quantity:.4f} × ({h.ltp:.4f} − {h.avg_price:.4f}) = {h.pnl:+,.2f}",
                })
            df_mf = pd.DataFrame(mf_detail)
            st.dataframe(df_mf, use_container_width=True, hide_index=True)

    except Exception as exc:
        st.error(f"P&L subtotal trace failed: {exc}")


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


def _render_fivepaisa_raw(account_svc, account_id: str):
    """
    5paisa-specific raw API investigation panel.
    Calls positions_day() (V4/NetPosition) and holdings() directly via the
    live authenticated FivePaisaAdapter client — no TTL cache, no CLI auth.
    Goal: determine whether V4/NetPosition carries broker-native BOD day P&L
    fields (MTOM, PreviousClose, BODPositionPrice) for delivery holdings.
    """
    import json

    adapter = account_svc.get_adapter(account_id)
    if adapter is None:
        st.error(f"No active adapter for '{account_id}'. Check auth status.")
        return

    client = getattr(adapter, "_client", None)
    if client is None:
        st.error(f"Adapter exists but _client is None — adapter not authenticated.")
        return

    st.markdown(
        "<div style='font-size:0.8rem;color:#8b949e;margin-bottom:10px;'>"
        "Direct API calls via the live FivePaisaAdapter client. "
        "Bypasses portfolio_service TTL cache. Press a button to trigger."
        "</div>",
        unsafe_allow_html=True,
    )

    col1, col2, col3, col4 = st.columns(4)
    run_netpos   = col1.button("positions_day() [V4]",            key="fp_netpos_btn")
    run_holdings = col2.button("holdings() raw fields",           key="fp_hold_btn")
    run_hist     = col3.button("historical_data() vs Snapshot",   key="fp_hist_btn")
    run_depth    = col4.button("MarketDepth vs Snapshot ← run this", key="fp_depth_btn", type="primary")

    # ── positions_day() ───────────────────────────────────────────────
    if run_netpos:
        st.markdown("### `positions_day()` — V4/NetPosition raw response")
        try:
            t0  = time.monotonic()
            raw = client.positions_day()
            elapsed = (time.monotonic() - t0) * 1000
            st.caption(f"Returned in {elapsed:.0f} ms  |  type: {type(raw).__name__}")

            import logging
            logger = logging.getLogger(__name__)
            logger.warning("5PAISA NETPOS DIAG [%s] positions_day() type=%s raw=%r",
                           account_id, type(raw).__name__, raw)

            if raw is None:
                st.error("positions_day() returned None — API call failed or returned empty.")
            elif isinstance(raw, dict):
                st.markdown(f"**Top-level keys:** `{list(raw.keys())}`")
                # Find the detail list under common key names
                detail = raw.get("NetPositionDetail",
                         raw.get("Data",
                         raw.get("Positions",
                         raw.get("PositionDetail", []))))
                st.markdown(f"**Detail records:** {len(detail or [])}")
                if detail:
                    st.markdown("**First record keys:**")
                    st.code(list(detail[0].keys()) if isinstance(detail[0], dict) else str(detail[0]))
                    st.markdown("**All records:**")
                    for i, rec in enumerate(detail[:20]):
                        st.json(rec)
                else:
                    st.info("Detail list is empty — no BOD positions found.")
                    st.markdown("**Full response:**")
                    st.json(raw)
            elif isinstance(raw, list):
                st.markdown(f"**Response is a list with {len(raw)} items**")
                for i, rec in enumerate(raw[:20]):
                    st.json(rec)
            else:
                st.markdown(f"**Unexpected type:** `{type(raw)}`")
                st.code(str(raw)[:2000])

        except Exception as exc:
            st.error(f"`positions_day()` raised: {exc}")
            import logging
            logging.getLogger(__name__).warning(
                "5PAISA NETPOS DIAG [%s] positions_day() EXCEPTION: %s", account_id, exc
            )

    # ── holdings() raw fields ─────────────────────────────────────────
    if run_holdings:
        st.markdown("### `holdings()` — V3/Holding all raw fields")
        try:
            t0   = time.monotonic()
            raw  = client.holdings()
            elapsed = (time.monotonic() - t0) * 1000
            st.caption(f"Returned {len(raw or [])} rows in {elapsed:.0f} ms")

            if not raw:
                st.info("holdings() returned empty list.")
            else:
                st.markdown(f"**Keys in first row:** `{list(raw[0].keys()) if isinstance(raw[0], dict) else '?'}`")
                for rec in (raw or []):
                    sym = rec.get("Symbol", "?") if isinstance(rec, dict) else "?"
                    st.markdown(f"**{sym}**")
                    st.json(rec)

        except Exception as exc:
            st.error(f"`holdings()` raised: {exc}")

    # ── V3 MarketDepth vs MarketSnapshot LTP comparison ──────────────
    import logging as _logging_depth
    import pandas as _pd_depth
    _logger_depth = _logging_depth.getLogger(__name__)

    # Persist results across reruns so the table stays visible after the
    # button triggers a Streamlit rerun.
    if "fp_depth_result" not in st.session_state:
        st.session_state.fp_depth_result = None

    if run_depth:
        with st.spinner("Fetching MarketDepth and MarketSnapshot for all holdings…"):
            _rows_depth = []
            _raw_depth_all = {}
            _error_depth = None

            try:
                raw_hold = client.holdings()
            except Exception as exc:
                _error_depth = f"holdings() failed: {exc}"
                raw_hold = []

            if raw_hold:
                scrip_info = {}
                for r in raw_hold:
                    sym  = (r.get("Symbol") or "").strip()
                    exch = (r.get("Exch") or "N").strip()
                    sc   = str(r.get("NseCode") if exch == "N" else r.get("BseCode") or "").strip()
                    if sym and sc:
                        scrip_info[sym] = (exch, sc)

                snap_ltp    = {}
                snap_pclose = {}
                try:
                    snap_req    = [{"Exchange": exch, "ExchangeType": "C", "ScripCode": sc}
                                   for _, (exch, sc) in scrip_info.items()]
                    snap_raw    = client.fetch_market_snapshot(snap_req)
                    snap_detail = snap_raw.get("Data", []) if isinstance(snap_raw, dict) else []
                    sc_to_sym   = {sc: sym for sym, (_, sc) in scrip_info.items()}
                    for item in snap_detail:
                        if not isinstance(item, dict):
                            continue
                        sc_key = str(item.get("ScripCode") or item.get("Token") or "")
                        sym = sc_to_sym.get(sc_key)
                        if sym:
                            snap_ltp[sym]    = item.get("LastTradedPrice")
                            snap_pclose[sym] = item.get("PClose")
                except Exception as exc:
                    _error_depth = f"MarketSnapshot failed: {exc}"

                # ── MarketDepth: try all three variants + multiple formats ──
                # Previous probe returned Status=0/Success with empty quote
                # fields — suggests request was accepted but instrument not
                # matched.  Possible causes:
                #   (a) ScripCode type: string vs int
                #   (b) Field names: Exch/ExchType vs Exchange/ExchangeType
                #   (c) NseCode != MarketDepth ScripCode identifier
                # We try every permutation and log request + raw response.

                depth_ltp      = {}
                _raw_depth_all = {}   # {sym: {variant: response}}

                for sym, (exch, sc) in scrip_info.items():
                    _raw_depth_all[sym] = {}

                    # Variant A — V3/MarketDepth, string ScripCode, Exch/ExchType
                    try:
                        req_a = [{"Exch": exch, "ExchType": "C", "ScripCode": sc}]
                        _raw_depth_all[sym]["V3_str"] = {"req": req_a, "resp": client.fetch_market_depth(req_a)}
                    except Exception as exc:
                        _raw_depth_all[sym]["V3_str"] = {"req": req_a, "error": str(exc)}

                    # Variant B — V3/MarketDepth, int ScripCode, Exch/ExchType
                    try:
                        req_b = [{"Exch": exch, "ExchType": "C", "ScripCode": int(sc)}]
                        _raw_depth_all[sym]["V3_int"] = {"req": req_b, "resp": client.fetch_market_depth(req_b)}
                    except Exception as exc:
                        _raw_depth_all[sym]["V3_int"] = {"req": req_b, "error": str(exc)}

                    # Variant C — V1/MarketDepth by symbol, using Symbol name
                    try:
                        req_c = [{"Exch": exch, "ExchType": "C", "Symbol": sym}]
                        _raw_depth_all[sym]["V1_sym"] = {"req": req_c, "resp": client.fetch_market_depth_by_symbol(req_c)}
                    except Exception as exc:
                        _raw_depth_all[sym]["V1_sym"] = {"req": req_c, "error": str(exc)}

                    # Variant D — V3/MarketDepth, Exchange/ExchangeType like Snapshot
                    try:
                        req_d = [{"Exchange": exch, "ExchangeType": "C", "ScripCode": int(sc)}]
                        _raw_depth_all[sym]["V3_snapfmt"] = {"req": req_d, "resp": client.fetch_market_depth(req_d)}
                    except Exception as exc:
                        _raw_depth_all[sym]["V3_snapfmt"] = {"req": req_d, "error": str(exc)}

                    # Extract best LTP from any variant that returned a non-zero value
                    _found_ltp = None
                    for _variant, _vdata in _raw_depth_all[sym].items():
                        _resp = _vdata.get("resp") if isinstance(_vdata, dict) else None
                        if not isinstance(_resp, dict):
                            continue
                        _data = _resp.get("Data", _resp.get("MarketDepthData", []))
                        _items = _data if isinstance(_data, list) else ([_data] if isinstance(_data, dict) else [])
                        for _item in _items:
                            if not isinstance(_item, dict):
                                continue
                            for _key in ("LTP", "LastTradedPrice", "LastRate", "Ltp", "ltp", "last_price"):
                                _v = _item.get(_key)
                                if _v and float(_v) > 0:
                                    _found_ltp = float(_v)
                                    break
                            if _found_ltp:
                                break
                        if _found_ltp:
                            break
                    depth_ltp[sym] = _found_ltp

                for r in raw_hold:
                    sym = (r.get("Symbol") or "").strip()
                    if not sym:
                        continue
                    hold_price = float(r.get("CurrentPrice") or 0)
                    s_ltp  = snap_ltp.get(sym)
                    d_ltp  = depth_ltp.get(sym)
                    s_pc   = snap_pclose.get(sym)
                    s_f    = float(s_ltp) if s_ltp is not None and not isinstance(s_ltp, str) else None
                    d_f    = float(d_ltp) if d_ltp is not None and not isinstance(d_ltp, str) else None

                    s_hold = round(s_f - hold_price, 4) if s_f is not None else None
                    d_hold = round(d_f - hold_price, 4) if d_f is not None else None
                    s_d    = round(s_f - d_f,        4) if (s_f is not None and d_f is not None) else None

                    _rows_depth.append({
                        "Symbol":           sym,
                        "holdings_Price":   hold_price,
                        "Snapshot_LTP":     s_ltp,
                        "Depth_LTP":        d_ltp,
                        "Snapshot_PClose":  s_pc,
                        "Snap-Hold delta":  s_hold,
                        "Depth-Hold delta": d_hold,
                        "Snap-Depth delta": s_d,
                    })

                    _logger_depth.warning(
                        "5PAISA DEPTH DIAG [%s] symbol=%s holdings=%.4f "
                        "snap_ltp=%s depth_ltp=%s pclose=%s "
                        "snap_hold_delta=%s depth_hold_delta=%s snap_depth_delta=%s",
                        account_id, sym, hold_price,
                        s_ltp, d_ltp, s_pc, s_hold, d_hold, s_d,
                    )

        st.session_state.fp_depth_result = {
            "rows":     _rows_depth,
            "raw_all":  _raw_depth_all,
            "error":    _error_depth,
        }

    # Render persisted result (survives reruns)
    _res = st.session_state.fp_depth_result
    if _res is not None:
        st.markdown("### V3/MarketDepth LTP vs MarketSnapshot LTP vs retail app")
        st.caption(
            "Snap-Hold delta ≈ 0: Snapshot matches holdings price.  "
            "Depth-Hold delta ≈ 0: MarketDepth matches holdings price (and likely the app).  "
            "Snap-Depth delta ≈ 0: both REST sources use the same pipeline → WebSocket needed."
        )
        if _res.get("error"):
            st.warning(_res["error"])
        if _res["rows"]:
            st.dataframe(_pd_depth.DataFrame(_res["rows"]),
                         use_container_width=True, hide_index=True)
        st.markdown("---")
        st.markdown("**Raw V3/MarketDepth responses** (field inspection)")
        for sym, raw_resp in (_res.get("raw_all") or {}).items():
            with st.expander(f"{sym} — raw MarketDepth response", expanded=True):
                st.json(raw_resp)
        if st.button("Clear result", key="fp_depth_clear"):
            st.session_state.fp_depth_result = None
            st.rerun()

    # ── historical_data() vs MarketSnapshot comparison ────────────────
    if run_hist:
        st.markdown("### `historical_data()` adjusted close vs MarketSnapshot `PClose`")
        st.caption(
            "Hypothesis: MarketSnapshot PClose = unadjusted settlement price. "
            "historical_data() 1d Close = adjusted close (ex-div, bonus etc). "
            "If they differ on days with corporate actions, adjusted close matches the app."
        )
        import logging
        import pandas as pd
        from datetime import date, timedelta

        _logger = logging.getLogger(__name__)

        try:
            raw_hold = client.holdings()
        except Exception as exc:
            st.error(f"holdings() failed: {exc}")
            raw_hold = []

        if not raw_hold:
            st.warning("No holdings returned.")
        else:
            # Date range: last 5 calendar days to catch the most recent trading day
            today_dt = date.today()
            from_dt  = (today_dt - timedelta(days=5)).strftime("%Y-%m-%d")
            to_dt    = (today_dt - timedelta(days=1)).strftime("%Y-%m-%d")

            # Build scrip_info: symbol → (exch, nse_code_str)
            scrip_info = {}
            for r in raw_hold:
                sym  = (r.get("Symbol") or "").strip()
                exch = (r.get("Exch") or "N").strip()
                sc   = str(r.get("NseCode") if exch == "N" else r.get("BseCode") or "").strip()
                if sym and sc:
                    scrip_info[sym] = (exch, sc)

            # Fetch MarketSnapshot for all holdings in one call
            snapshot_pclose = {}
            snapshot_netchange = {}
            try:
                snap_req = [{"Exchange": exch, "ExchangeType": "C", "ScripCode": sc}
                            for _, (exch, sc) in scrip_info.items()]
                snap_raw = client.fetch_market_snapshot(snap_req)
                snap_detail = snap_raw.get("Data", []) if isinstance(snap_raw, dict) else []
                sc_to_sym = {sc: sym for sym, (_, sc) in scrip_info.items()}
                for item in snap_detail:
                    if not isinstance(item, dict):
                        continue
                    sc_key = str(item.get("ScripCode") or item.get("Token") or "")
                    sym = sc_to_sym.get(sc_key)
                    if sym:
                        snapshot_pclose[sym]    = item.get("PClose")
                        snapshot_netchange[sym] = item.get("NetChange")
            except Exception as exc:
                st.warning(f"MarketSnapshot fetch failed: {exc}")

            # Per-holding: call historical_data() and build comparison rows
            rows = []
            for r in raw_hold:
                sym  = (r.get("Symbol") or "").strip()
                if not sym:
                    continue
                qty          = float(r.get("Quantity") or r.get("Qty") or 0)
                current_price = float(r.get("CurrentPrice") or 0)
                exch, sc     = scrip_info.get(sym, ("N", ""))

                hist_close = None
                hist_error = None
                if sc:
                    try:
                        df_hist = client.historical_data(
                            Exch=exch,
                            ExchangeSegment="C",
                            ScripCode=int(sc),
                            time="1d",
                            From=from_dt,
                            To=to_dt,
                        )
                        if df_hist is not None and not df_hist.empty:
                            # Last row = most recent trading day close
                            hist_close = float(df_hist.iloc[-1]["Close"])
                        else:
                            hist_error = "empty/None"
                    except Exception as exc:
                        hist_error = str(exc)[:60]

                pclose     = snapshot_pclose.get(sym)
                netchange  = snapshot_netchange.get(sym)

                # Derived day changes
                adj_day_change   = round(current_price - hist_close, 4) if hist_close else None
                unadj_day_change = float(netchange) if netchange is not None else None

                adj_day_pnl   = round(adj_day_change * qty, 2) if adj_day_change is not None else None
                unadj_day_pnl = round(unadj_day_change * qty, 2) if unadj_day_change is not None else None

                hist_vs_pclose = round(hist_close - float(pclose), 4) if (hist_close and pclose) else None

                row = {
                    "Symbol":              sym,
                    "Qty":                 qty,
                    "CurrentPrice":        current_price,
                    "Snapshot_PClose":     pclose,
                    "Snapshot_NetChange":  netchange,
                    "Hist_Close (adj)":    hist_close if hist_close else hist_error,
                    "Hist-PClose delta":   hist_vs_pclose,
                    "Unadj_DayPnL":        unadj_day_pnl,
                    "Adj_DayPnL":          adj_day_pnl,
                }
                rows.append(row)

                _logger.warning(
                    "5PAISA HIST DIAG [%s] symbol=%s qty=%.0f current=%.4f "
                    "snap_PClose=%s snap_NetChange=%s hist_close=%s "
                    "hist_pclose_delta=%s unadj_day_pnl=%s adj_day_pnl=%s",
                    account_id, sym, qty, current_price,
                    pclose, netchange, hist_close if hist_close else hist_error,
                    hist_vs_pclose, unadj_day_pnl, adj_day_pnl,
                )

            if rows:
                df_out = pd.DataFrame(rows)
                st.dataframe(df_out, use_container_width=True, hide_index=True)

                total_adj   = sum(r["Adj_DayPnL"]   for r in rows if r["Adj_DayPnL"]   is not None)
                total_unadj = sum(r["Unadj_DayPnL"] for r in rows if r["Unadj_DayPnL"] is not None)
                st.markdown(
                    f"**Total unadjusted day P&L** (MarketSnapshot NetChange × Qty) = **₹{total_unadj:,.2f}**  \n"
                    f"**Total adjusted day P&L** (historical_data Close × Qty) = **₹{total_adj:,.2f}**"
                )
                _logger.warning(
                    "5PAISA HIST DIAG [%s] TOTAL unadj=%.2f adj=%.2f",
                    account_id, total_unadj, total_adj,
                )
