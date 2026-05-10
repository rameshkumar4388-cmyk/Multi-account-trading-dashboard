"""
Aggregation service — combines data across all accounts.

Provides combined views (net worth, total holdings, total P&L) while
also supporting per-broker and per-account breakdowns.

This layer never calls broker adapters directly. It only consumes
PortfolioService, keeping the dependency graph clean.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from schemas.account import AccountSummary, MarginInfo
from schemas.holding import Holding
from schemas.position import Position

logger = logging.getLogger(__name__)


class AggregationService:
    def __init__(self, account_service, portfolio_service):
        self._accounts = account_service
        self._portfolio = portfolio_service

    def _active_ids(self, account_ids: Optional[List[str]] = None) -> List[str]:
        all_ids = self._accounts.list_account_ids()
        if account_ids is None:
            return all_ids
        return [aid for aid in account_ids if aid in all_ids]

    # ------------------------------------------------------------------
    # Holdings
    # ------------------------------------------------------------------

    def get_combined_holdings(self, account_ids: Optional[List[str]] = None) -> List[Holding]:
        result: List[Holding] = []
        for aid in self._active_ids(account_ids):
            result.extend(self._portfolio.get_holdings(aid))
        return result

    def get_aggregated_holdings(self, account_ids: Optional[List[str]] = None) -> List[dict]:
        """
        Merge holdings of the same symbol across accounts into a single row.
        Returns dicts for easy DataFrame construction.
        """
        merged: Dict[str, dict] = {}
        for h in self.get_combined_holdings(account_ids):
            key = h.symbol
            if key not in merged:
                merged[key] = {
                    "symbol": h.symbol,
                    "exchange": h.exchange,
                    "sector": h.sector,
                    "quantity": 0,
                    "invested_value": 0.0,
                    "current_value": 0.0,
                    "pnl": 0.0,
                    "accounts": [],
                    "ltp": h.ltp,
                    "avg_price": 0.0,
                }
            m = merged[key]
            m["quantity"] += h.quantity
            m["invested_value"] = round(m["invested_value"] + h.invested_value, 2)
            m["current_value"] = round(m["current_value"] + h.current_value, 2)
            m["pnl"] = round(m["pnl"] + h.pnl, 2)
            m["ltp"] = h.ltp
            if h.account_id not in m["accounts"]:
                m["accounts"].append(h.account_id)

        for m in merged.values():
            m["pnl_pct"] = round((m["pnl"] / m["invested_value"]) * 100, 2) if m["invested_value"] else 0.0
            m["avg_price"] = round(m["invested_value"] / m["quantity"], 2) if m["quantity"] else 0.0

        return sorted(merged.values(), key=lambda x: -x["current_value"])

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def get_combined_positions(self, account_ids: Optional[List[str]] = None) -> List[Position]:
        result: List[Position] = []
        for aid in self._active_ids(account_ids):
            result.extend(self._portfolio.get_positions(aid))
        return result

    # ------------------------------------------------------------------
    # Summaries and metrics
    # ------------------------------------------------------------------

    def get_all_summaries(self, account_ids: Optional[List[str]] = None) -> List[AccountSummary]:
        summaries = []
        for aid in self._active_ids(account_ids):
            s = self._portfolio.get_account_summary(aid)
            if s:
                summaries.append(s)
        return summaries

    def get_combined_metrics(self, account_ids: Optional[List[str]] = None) -> dict:
        summaries = self.get_all_summaries(account_ids)
        if not summaries:
            return self._empty_metrics()

        total_holdings_value = sum(s.total_holdings_value for s in summaries)
        total_invested = sum(s.total_invested_value for s in summaries)
        holdings_pnl = sum(s.holdings_pnl for s in summaries)
        positions_pnl = sum(s.positions_pnl for s in summaries)
        day_pnl = sum(s.day_pnl for s in summaries)
        available_cash = sum(s.available_cash for s in summaries)
        used_margin = sum(s.used_margin for s in summaries)
        net_worth = sum(s.net_worth for s in summaries)

        return {
            "total_holdings_value": round(total_holdings_value, 2),
            "total_invested_value": round(total_invested, 2),
            "holdings_pnl": round(holdings_pnl, 2),
            "holdings_pnl_pct": round((holdings_pnl / total_invested) * 100, 2) if total_invested else 0.0,
            "positions_pnl": round(positions_pnl, 2),
            "total_pnl": round(holdings_pnl + positions_pnl, 2),
            "day_pnl": round(day_pnl, 2),
            "available_cash": round(available_cash, 2),
            "used_margin": round(used_margin, 2),
            "net_worth": round(net_worth, 2),
            "account_count": len(summaries),
        }

    def _empty_metrics(self) -> dict:
        return {
            "total_holdings_value": 0.0, "total_invested_value": 0.0,
            "holdings_pnl": 0.0, "holdings_pnl_pct": 0.0,
            "positions_pnl": 0.0, "total_pnl": 0.0, "day_pnl": 0.0,
            "available_cash": 0.0, "used_margin": 0.0,
            "net_worth": 0.0, "account_count": 0,
        }

    # ------------------------------------------------------------------
    # Breakdowns
    # ------------------------------------------------------------------

    def get_broker_breakdown(self, account_ids: Optional[List[str]] = None) -> List[dict]:
        summaries = self.get_all_summaries(account_ids)
        broker_data: Dict[str, dict] = {}
        for s in summaries:
            cfg = self._accounts._account_configs.get(s.account_id)
            broker = cfg.metadata.get("original_broker", s.broker) if cfg else s.broker
            if broker not in broker_data:
                broker_data[broker] = {
                    "broker": broker.capitalize(),
                    "net_worth": 0.0,
                    "holdings_value": 0.0,
                    "pnl": 0.0,
                    "accounts": 0,
                }
            broker_data[broker]["net_worth"] += s.net_worth
            broker_data[broker]["holdings_value"] += s.total_holdings_value
            broker_data[broker]["pnl"] += s.total_pnl
            broker_data[broker]["accounts"] += 1
        return list(broker_data.values())

    def get_sector_breakdown(self, account_ids: Optional[List[str]] = None) -> List[dict]:
        holdings = self.get_combined_holdings(account_ids)
        sector_data: Dict[str, dict] = {}
        for h in holdings:
            sector = h.sector or "Unknown"
            if sector not in sector_data:
                sector_data[sector] = {"sector": sector, "value": 0.0, "pnl": 0.0}
            sector_data[sector]["value"] += h.current_value
            sector_data[sector]["pnl"] += h.pnl
        return sorted(sector_data.values(), key=lambda x: -x["value"])

    def get_exposure_breakdown(self, account_ids: Optional[List[str]] = None) -> dict:
        """Breakdown by instrument type: EQ, FUT, CE, PE."""
        holdings = self.get_combined_holdings(account_ids)
        positions = self.get_combined_positions(account_ids)

        eq_value = sum(h.current_value for h in holdings)
        fut_value = sum(abs(p.value) for p in positions if p.instrument_type == "FUT")
        ce_value = sum(abs(p.value) for p in positions if p.instrument_type == "CE")
        pe_value = sum(abs(p.value) for p in positions if p.instrument_type == "PE")
        eq_pos_value = sum(abs(p.value) for p in positions if p.instrument_type == "EQ")

        return {
            "Equity Holdings": round(eq_value, 2),
            "Equity Intraday": round(eq_pos_value, 2),
            "Futures": round(fut_value, 2),
            "Call Options": round(ce_value, 2),
            "Put Options": round(pe_value, 2),
        }

    def get_account_breakdown(self, account_ids: Optional[List[str]] = None) -> List[dict]:
        summaries = self.get_all_summaries(account_ids)
        result = []
        for s in summaries:
            cfg = self._accounts._account_configs.get(s.account_id)
            broker = cfg.metadata.get("original_broker", s.broker) if cfg else s.broker
            result.append({
                "account_id": s.account_id,
                "display_name": s.display_name,
                "broker": broker.capitalize(),
                "net_worth": s.net_worth,
                "holdings_value": s.total_holdings_value,
                "holdings_pnl": s.holdings_pnl,
                "positions_pnl": s.positions_pnl,
                "day_pnl": s.day_pnl,
                "available_cash": s.available_cash,
                "used_margin": s.used_margin,
            })
        return result
