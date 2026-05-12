"""
Canonical account display order for all UI rendering.

Centralised here so ordering logic is changed in exactly one place.

Usage:
    from ui.account_order import sort_account_ids, sort_summaries

    ids      = sort_account_ids(raw_ids,   account_configs)
    summaries = sort_summaries(raw_summaries, account_configs)
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

# Accounts in the exact order they must appear in every UI surface.
# Accounts not listed here appear after these, sorted alphabetically.
_CANONICAL_USER_IDS: List[str] = [
    "SP7086",
    "VU5420",
    "CL0502",
    "FXU722",
    "DA1898",
]


def _resolve_user_id(account_id: str, account_configs: Dict[str, Any]) -> str:
    """
    Return the Zerodha client ID (e.g. 'SP7086') for a given account_id.

    Resolution order:
      1. cfg.credentials['user_id']  — populated from API profile after auth
      2. cfg.display_name pattern    — 'Zerodha (SP7086)' → 'SP7086'
      3. account_id tag              — 'zerodha_sp7086' → 'SP7086'
    """
    cfg = (account_configs or {}).get(account_id)
    if cfg is not None:
        # 1 — credentials (most reliable after auth)
        if hasattr(cfg, "credentials") and isinstance(cfg.credentials, dict):
            uid = cfg.credentials.get("user_id", "")
            if uid:
                return uid.upper()
        # 2 — display name like "Zerodha (SP7086)"
        if hasattr(cfg, "display_name") and cfg.display_name:
            m = re.search(r"\(([A-Z0-9]+)\)", cfg.display_name)
            if m:
                return m.group(1).upper()
    # 3 — tag extracted from account_id ("zerodha_sp7086" → "SP7086")
    if "_" in account_id:
        return account_id.rsplit("_", 1)[-1].upper()
    return account_id.upper()


def _rank(account_id: str, account_configs: Dict[str, Any]):
    """Return a sort key: canonical accounts first, then alphabetical."""
    uid = _resolve_user_id(account_id, account_configs)
    if uid in _CANONICAL_USER_IDS:
        return (0, _CANONICAL_USER_IDS.index(uid), uid)
    return (1, 0, uid or account_id)


def sort_account_ids(
    account_ids: List[str],
    account_configs: Dict[str, Any],
) -> List[str]:
    """
    Return account_ids sorted by canonical display order.

    Canonical order: SP7086, VU5420, CL0502, FXU722, DA1898.
    Unknown accounts follow in alphabetical order.
    """
    return sorted(account_ids, key=lambda aid: _rank(aid, account_configs))


def sort_summaries(summaries: List[Any], account_configs: Dict[str, Any]) -> List[Any]:
    """Sort a list of AccountSummary objects by canonical display order."""
    ordered_ids = sort_account_ids(
        [s.account_id for s in summaries], account_configs
    )
    id_to_summary = {s.account_id: s for s in summaries}
    return [id_to_summary[aid] for aid in ordered_ids if aid in id_to_summary]
