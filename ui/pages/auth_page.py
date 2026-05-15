"""
Authentication management page.

Supports Zerodha (OAuth redirect flow) and 5paisa (manual token entry).

Zerodha flow:
  1. Click Open Login → opens kite.zerodha.com in new tab
  2. Zerodha redirects back with ?request_token=...&status=success
  3. Dashboard exchanges request_token → access_token automatically
  4. Token stored in SQLite; live session refreshed without restart

5paisa flow:
  1. Click Open Login → opens 5paisa portal in new tab
  2. User obtains new access_token from 5paisa portal
  3. User pastes access_token into the form on this page
  4. Dashboard calls authenticate() with the new token; session refreshed

Security:
  - api_secret never leaves the server (.env → python process only)
  - access_token is stored server-side in SQLite (never in browser)
  - request_token is single-use and immediately consumed
"""
from __future__ import annotations

import logging
from typing import Optional

import streamlit as st

from ui.account_order import sort_account_ids

logger = logging.getLogger(__name__)

# Survives across Streamlit sessions (tabs) in the same server process.
# Written whenever the reconnect dropdown changes; read by handle_oauth_redirect
# when the OAuth redirect arrives in a fresh tab with no session state.
_PENDING_AUTH: dict = {}

# Brokers that appear in the auth page reconnect flow
_AUTH_BROKERS = {"zerodha", "fivepaisa"}

# 5paisa login URL for daily token retrieval
_FIVEPAISA_PORTAL_URL = "https://login.5paisa.com/login"


def _exchange_token(api_key: str, api_secret: str, request_token: str) -> Optional[str]:
    """Exchange Zerodha request_token for access_token. Returns access_token or None."""
    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=api_key)
        session = kite.generate_session(request_token, api_secret=api_secret)
        return session.get("access_token")
    except Exception as exc:
        logger.error("Token exchange failed: %s", exc)
        return None


def handle_oauth_redirect(account_svc, settings) -> bool:
    """
    Check URL query params for a Zerodha OAuth redirect.
    If request_token is present and valid, exchange and refresh the session.
    Returns True if a token was successfully processed.
    """
    params = st.query_params
    request_token = params.get("request_token", "")
    status        = params.get("status", "")

    if not request_token or status != "success":
        return False

    # Session state is absent when the redirect lands in a new browser tab.
    # _PENDING_AUTH (module-level, process-shared) bridges that gap.
    target_account = (
        st.session_state.get("auth_target_account")
        or _PENDING_AUTH.get("account_id")
    )

    if not target_account:
        # Last resort: canonical order so SP7086 is first
        all_ids = sort_account_ids(
            list(account_svc._account_configs.keys()),
            account_svc._account_configs,
        )
        zerodha_ids = [
            aid for aid in all_ids
            if account_svc._account_configs[aid].broker == "zerodha"
        ]
        target_account = zerodha_ids[0] if zerodha_ids else None

    if not target_account:
        st.error("No Zerodha account configured to receive this token.")
        return False

    cfg = account_svc._account_configs.get(target_account)
    if not cfg:
        return False

    # This redirect is always Zerodha — 5paisa does not redirect back
    if cfg.broker != "zerodha":
        logger.warning(
            "OAuth redirect received but target account '%s' is broker '%s' — ignoring",
            target_account, cfg.broker,
        )
        return False

    api_key    = cfg.credentials.get("api_key", "")
    api_secret = cfg.credentials.get("api_secret", "")

    if not api_secret:
        st.error(
            f"api_secret not configured for account '{target_account}'. "
            "Set KITE_API_SECRET (or ZERODHA_{{TAG}}_API_SECRET) in .env."
        )
        return False

    with st.spinner("Exchanging request token for access token…"):
        access_token = _exchange_token(api_key, api_secret, request_token)

    if not access_token:
        st.error(
            "Token exchange failed. The request_token may have expired "
            "(it's single-use and valid for ~5 minutes). Please try logging in again."
        )
        return False

    ok = account_svc.refresh_session(
        account_id=target_account,
        access_token=access_token,
    )

    if ok:
        st.session_state["last_auth_success"] = target_account
        st.success(
            f"✓ Connected {cfg.display_name}. "
            "Token stored — will persist across app restarts until 6 AM IST tomorrow."
        )
        logger.info("OAuth redirect: refreshed session for '%s'", target_account)
        return True
    else:
        health = account_svc.get_health().get(target_account)
        err = health.error if health else "Unknown error"
        st.error(f"Session refresh failed after token exchange: {err}")
        return False


# ── Per-broker login renderers ─────────────────────────────────────────

def _render_zerodha_login(target_id: str, cfg, portfolio_svc, account_svc):
    """Zerodha OAuth redirect flow."""
    from brokers.zerodha.auth import get_login_url
    api_key   = cfg.credentials.get("api_key", "") if cfg else ""
    login_url = get_login_url(api_key)

    st.markdown("**Step 1 — Log in to Zerodha Kite**")
    st.markdown(
        f"<a href='{login_url}' target='_blank'>"
        f"<button style='background:#238636;color:#fff;border:none;border-radius:6px;"
        f"padding:8px 20px;font-size:0.85rem;font-weight:600;cursor:pointer;"
        f"margin-bottom:8px;'>Open Login ↗</button></a>",
        unsafe_allow_html=True,
    )
    st.caption(
        "After login, Zerodha redirects back to this dashboard with the token in the URL. "
        "The page will detect it automatically — you don't need to copy anything."
    )

    st.markdown("**Step 2 — Automatic detection**")
    st.info(
        "Once you log in on Kite, the redirect will bring you back here. "
        "The dashboard reads `?request_token=...` from the URL and exchanges it automatically. "
        "If the redirect doesn't work, use Step 3 below."
    )

    with st.expander("Step 3 — Manual token entry (fallback)"):
        st.caption(
            "If the automatic redirect doesn't work, paste the full redirect URL "
            "or just the request_token value from the URL bar."
        )
        manual_input = st.text_input(
            "Paste redirect URL or request_token",
            key="manual_token_input",
            placeholder="https://...?request_token=abc123... or just abc123...",
        )
        if st.button("Exchange Token", key="manual_exchange_btn"):
            if not manual_input.strip():
                st.warning("Please paste the redirect URL or request_token first.")
            else:
                raw = manual_input.strip()
                if "request_token=" in raw:
                    token_part = raw.split("request_token=")[-1]
                    request_token = token_part.split("&")[0]
                else:
                    request_token = raw

                api_secret = cfg.credentials.get("api_secret", "") if cfg else ""
                if not api_secret:
                    st.error("api_secret not found in config. Set KITE_API_SECRET in .env.")
                else:
                    with st.spinner("Exchanging token…"):
                        access_token = _exchange_token(api_key, api_secret, request_token)

                    if access_token:
                        ok = account_svc.refresh_session(
                            account_id=target_id,
                            access_token=access_token,
                        )
                        if ok:
                            if portfolio_svc:
                                portfolio_svc.invalidate(target_id)
                            st.success(
                                f"✓ {cfg.display_name} reconnected. "
                                "Token saved — no restart needed."
                            )
                            st.rerun()
                        else:
                            h2 = account_svc.get_health().get(target_id)
                            st.error(f"Session refresh failed: {h2.error if h2 else 'unknown'}")
                    else:
                        st.error(
                            "Token exchange failed. "
                            "The request_token may be expired (single-use, ~5 min TTL). "
                            "Please start over from Step 1."
                        )


def _render_fivepaisa_login(target_id: str, cfg, portfolio_svc, account_svc):
    """
    5paisa manual token entry flow.
    5paisa does not redirect back to the dashboard — the user must obtain
    the access_token from the 5paisa portal and paste it here.
    """
    st.markdown("**Step 1 — Get new access token from 5paisa**")
    st.markdown(
        f"<a href='{_FIVEPAISA_PORTAL_URL}' target='_blank'>"
        f"<button style='background:#238636;color:#fff;border:none;border-radius:6px;"
        f"padding:8px 20px;font-size:0.85rem;font-weight:600;cursor:pointer;"
        f"margin-bottom:8px;'>Open Login ↗</button></a>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Log in to 5paisa and copy your access token from the portal. "
        "Tokens are issued daily and must be refreshed each session."
    )

    st.markdown("**Step 2 — Paste new access token**")
    new_token = st.text_input(
        "5paisa Access Token",
        key="fivepaisa_token_input",
        placeholder="Paste new access_token here…",
        type="password",
    )
    if st.button("Connect", key="fivepaisa_connect_btn"):
        if not new_token.strip():
            st.warning("Please paste your access token first.")
        else:
            with st.spinner(f"Reconnecting {cfg.display_name}…"):
                ok = account_svc.refresh_session(
                    account_id=target_id,
                    access_token=new_token.strip(),
                )
            if ok:
                if portfolio_svc:
                    portfolio_svc.invalidate(target_id)
                st.success(
                    f"✓ {cfg.display_name} reconnected. "
                    "Session is active for this app instance."
                )
                logger.info("5paisa manual token refresh succeeded for '%s'", target_id)
                st.rerun()
            else:
                h2 = account_svc.get_health().get(target_id)
                st.error(
                    f"Authentication failed: {h2.error if h2 else 'check access token and credentials'}"
                )


# ── Main render ────────────────────────────────────────────────────────

def render(account_svc, settings, portfolio_svc=None):
    """Auth management page — shown when user navigates to Auth or on token expiry."""

    health          = account_svc.get_health()
    all_account_ids = list(account_svc._account_configs.keys())

    st.markdown(
        "<div style='font-size:1.1rem;font-weight:700;color:#e6edf3;margin-bottom:4px;'>"
        "Broker Authentication</div>"
        "<div style='font-size:0.8rem;color:#8b949e;margin-bottom:20px;'>"
        "Tokens expire daily. Use this page to reconnect any broker account without restarting the app."
        "</div>",
        unsafe_allow_html=True,
    )

    # ── Per-account status cards ──────────────────────────────────────
    # Show all configured broker accounts with REAL session validity.
    # Bug fix: h.is_active reflects auth success at startup only and does not
    # update when a session later expires.  Using adapter.is_session_valid()
    # gives the true in-process state: False if auth failed or was never
    # attempted, True if the adapter currently holds an active session.
    for account_id in all_account_ids:
        cfg = account_svc._account_configs.get(account_id)
        if not cfg or cfg.broker not in _AUTH_BROKERS:
            continue

        adapter   = account_svc.get_adapter(account_id)
        is_active = adapter.is_session_valid(account_id) if adapter else False

        h         = health.get(account_id)
        auth_time = (
            h.authenticated_at.strftime("%d %b %Y %H:%M") if (h and h.authenticated_at) else "—"
        )
        status_color = "#3fb950" if is_active else "#f85149"
        status_text  = "Connected" if is_active else (
            h.status.replace("_", " ").title() if h else "Not Authenticated"
        )
        error_text = (
            f"<div style='font-size:0.72rem;color:#f85149;margin-top:4px;'>{h.error}</div>"
            if (h and h.error) else ""
        )
        broker_badge = cfg.broker.capitalize()

        st.markdown(
            f"<div style='background:#161b22;border:1px solid #30363d;border-radius:8px;"
            f"padding:14px 16px;margin-bottom:12px;'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;'>"
            f"<div>"
            f"<div style='font-size:0.9rem;font-weight:600;color:#e6edf3;'>{cfg.display_name}"
            f"<span style='font-size:0.65rem;color:#6e7681;margin-left:8px;"
            f"background:#21262d;padding:1px 6px;border-radius:4px;'>{broker_badge}</span>"
            f"</div>"
            f"<div style='font-size:0.7rem;color:#6e7681;margin-top:2px;'>{account_id}</div>"
            f"</div>"
            f"<div style='text-align:right;'>"
            f"<span style='font-size:0.8rem;font-weight:700;color:{status_color};'>"
            f"● {status_text}</span>"
            f"<div style='font-size:0.68rem;color:#6e7681;margin-top:2px;'>Last auth: {auth_time}</div>"
            f"</div></div>{error_text}</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Account selector ──────────────────────────────────────────────
    reconnectable = sort_account_ids(
        [
            aid for aid in all_account_ids
            if account_svc._account_configs.get(aid) and
               account_svc._account_configs[aid].broker in _AUTH_BROKERS
        ],
        account_svc._account_configs,
    )

    if not reconnectable:
        st.info("No broker accounts configured. Add ZERODHA_* or FIVEPAISA_* vars to .env and restart.")
        return

    if len(reconnectable) == 1:
        target_id = reconnectable[0]
    else:
        target_id = st.selectbox(
            "Select account to reconnect",
            reconnectable,
            format_func=lambda x: account_svc._account_configs[x].display_name,
            key="auth_account_select",
        )

    st.session_state["auth_target_account"] = target_id
    _PENDING_AUTH["account_id"] = target_id   # survives cross-tab redirect

    cfg = account_svc._account_configs.get(target_id)
    if not cfg:
        st.error(f"Account config not found for {target_id}.")
        return

    # ── Broker-specific login flow ────────────────────────────────────
    if cfg.broker == "zerodha":
        api_key = cfg.credentials.get("api_key", "")
        if not api_key:
            st.error(f"No api_key configured for {target_id}. Check .env.")
            return
        _render_zerodha_login(target_id, cfg, portfolio_svc, account_svc)

    elif cfg.broker == "fivepaisa":
        _render_fivepaisa_login(target_id, cfg, portfolio_svc, account_svc)
