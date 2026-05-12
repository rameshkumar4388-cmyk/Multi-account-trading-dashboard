from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from schemas.account import AccountInfo, AccountSummary, MarginInfo
from schemas.holding import Holding
from schemas.position import Position


class BrokerAdapter(ABC):
    """
    Abstract base for all broker integrations.

    Every broker must implement this interface. The dashboard layer
    never calls broker APIs directly — it always goes through a
    BrokerAdapter subclass.

    All returned data must conform to the internal normalized schemas.
    """

    @property
    @abstractmethod
    def broker_name(self) -> str:
        """Canonical broker identifier: 'zerodha', 'groww', 'fivepaisa', 'mock'."""

    @abstractmethod
    def authenticate(self, account_id: str, credentials: dict) -> bool:
        """
        Authenticate and prepare session for the given account.
        Returns True on success, False on failure.
        """

    @abstractmethod
    def is_session_valid(self, account_id: str) -> bool:
        """Return True if the current session token is still valid."""

    @abstractmethod
    def get_account_info(self, account_id: str) -> Optional[AccountInfo]:
        """Fetch and return normalized account profile information."""

    @abstractmethod
    def get_holdings(self, account_id: str) -> List[Holding]:
        """Return list of normalized Holding objects for long-term investments."""

    @abstractmethod
    def get_positions(self, account_id: str) -> List[Position]:
        """Return list of normalized Position objects for intraday/overnight trades."""

    @abstractmethod
    def get_margin(self, account_id: str) -> Optional[MarginInfo]:
        """Return normalized margin and fund information."""

    @abstractmethod
    def get_account_summary(self, account_id: str) -> Optional[AccountSummary]:
        """Return a pre-computed account summary."""

    def get_kite_session(self, account_id: str):
        """
        Return the underlying KiteConnect session for this account, or None.
        Only ZerodhaAdapter returns a real object; all other adapters return None.
        Used by the market data layer to attach a live price feed.
        """
        return None

    def get_subscribed_symbols(self, account_id: str) -> List[str]:
        """
        Return symbols to subscribe to for live market data.
        Default: derive from current holdings + positions.
        Override for broker-specific instrument tokens.
        """
        symbols: List[str] = []
        for h in self.get_holdings(account_id):
            if h.instrument_type != "MF":   # MF NAVs are EOD-only — no live feed
                symbols.append(h.symbol)
        for p in self.get_positions(account_id):
            symbols.append(p.symbol)        # F&O contract (e.g. RELIANCE26MAY1300PE)
            if p.underlying and p.underlying != p.symbol:
                symbols.append(p.underlying)  # underlying equity/index for the LTP chip display
        return list(dict.fromkeys(symbols))   # deduplicate, preserve order
