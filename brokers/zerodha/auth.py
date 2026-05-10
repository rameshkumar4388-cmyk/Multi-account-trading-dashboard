"""
Zerodha KiteConnect authentication helpers.

Usage:
  1. Generate login URL via get_login_url()
  2. User logs in, gets request_token from redirect
  3. Exchange request_token → access_token via exchange_token()
  4. Store access_token in env or config (valid until next day's 6 AM IST)
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def get_login_url(api_key: str) -> str:
    return f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"


def exchange_token(api_key: str, api_secret: str, request_token: str) -> Optional[str]:
    """Exchange a request_token for an access_token. Returns access_token or None."""
    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=api_key)
        session = kite.generate_session(request_token, api_secret=api_secret)
        return session.get("access_token")
    except ImportError:
        logger.error("kiteconnect not installed. Install with: pip install kiteconnect")
        return None
    except Exception as exc:
        logger.error("Token exchange failed: %s", exc)
        return None
