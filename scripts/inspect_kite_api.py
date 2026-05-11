"""
Kite Connect API Schema Inspector
==================================
Pure discovery script — no dashboard schemas, no normalization, no transforms.
Every value is written exactly as the API returns it.

Reference docs:
  https://kite.trade/docs/pykiteconnect/v4/
  https://kite.trade/docs/connect/v3/

Usage:
    cd /path/to/dashboard
    python scripts/inspect_kite_api.py

Outputs written to debug_api/:
    profile.json          — kite.profile() raw response
    holdings.json         — kite.holdings() raw response
    positions.json        — kite.positions() raw response
    margins.json          — kite.margins() raw response
    discovered_fields.txt — every field path, type, sample value
    report_quantities.txt — all quantity-related fields
    report_collateral.txt — all collateral-related fields
    report_margins.txt    — all margin-related fields
    report_pnl.txt        — all P&L-related fields

Authentication priority (tries each in order, skips on failure):
    1. DB stored_tokens                          (freshest — written by auth page)
    2. Tagged env vars ZERODHA_<TAG>_*           (multi-account .env)
    3. Flat env vars ZERODHA_* (no tag)
    4. Flat env vars KITE_*                      (tried last — most likely stale)
"""
from __future__ import annotations

import json
import os
import sys
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from pprint import pformat
from typing import Any

# ── Paths ─────────────────────────────────────────────────────────────
ROOT   = Path(__file__).parent.parent
OUT    = ROOT / "debug_api"
OUT.mkdir(exist_ok=True)

# ── .env loading (standalone — no dashboard config layer) ─────────────
def _load_dotenv(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v

_load_dotenv(ROOT / ".env")
_load_dotenv(ROOT / ".env.local")

# ── Credential discovery ───────────────────────────────────────────────
PLACEHOLDER = {"", "your_api_key_here", "your_access_token_here", "xxx"}

def _is_real(v: str) -> bool:
    return bool(v) and v.strip() not in PLACEHOLDER

def _discover_credentials() -> list[dict]:
    """
    Return list of {api_key, access_token, label} dicts ordered by
    likelihood of being fresh.  DB tokens are tried first because they
    are written by the auth page after every successful daily login.
    Flat .env vars (KITE_*) come last — they are the most likely to be
    stale after the daily 06:00 IST expiry.
    """
    creds = []

    # ── 1. DB stored_tokens (freshest — written by the auth page) ────
    db_path = ROOT / os.getenv("DB_PATH", "data/dashboard.db")
    if db_path.exists():
        try:
            con = sqlite3.connect(str(db_path))
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT * FROM stored_tokens ORDER BY generated_at DESC"
            ).fetchall()
            con.close()
            for row in rows:
                k   = (row["api_key"] or "").strip()
                t   = (row["access_token"] or "").strip()
                gen = row["generated_at"]
                if _is_real(k) and _is_real(t):
                    creds.append({
                        "api_key":      k,
                        "access_token": t,
                        "label":        f"DB:{row['account_id']} (generated {gen})",
                        "source":       "db",
                    })
        except Exception as e:
            print(f"  [warn] could not read stored_tokens from DB: {e}")

    # ── 2. Tagged ZERODHA_<TAG>_* (multi-account .env) ───────────────
    for key in sorted(os.environ):
        if key.startswith("ZERODHA_") and key.endswith("_API_KEY"):
            tag = key[len("ZERODHA_"):-len("_API_KEY")]
            if not tag:
                continue
            k = os.getenv(f"ZERODHA_{tag}_API_KEY", "").strip()
            t = os.getenv(f"ZERODHA_{tag}_ACCESS_TOKEN", "").strip()
            if _is_real(k) and _is_real(t):
                creds.append({
                    "api_key":      k,
                    "access_token": t,
                    "label":        f"env:ZERODHA_{tag}_*",
                    "source":       "env_tagged",
                })

    # ── 3. Flat ZERODHA_* (no tag) ────────────────────────────────────
    k = os.getenv("ZERODHA_API_KEY", "").strip()
    t = os.getenv("ZERODHA_ACCESS_TOKEN", "").strip()
    if _is_real(k) and _is_real(t):
        creds.append({
            "api_key":      k,
            "access_token": t,
            "label":        "env:ZERODHA_*",
            "source":       "env_flat",
        })

    # ── 4. Flat KITE_* (tried last — most likely stale) ───────────────
    k = os.getenv("KITE_API_KEY", "").strip()
    t = os.getenv("KITE_ACCESS_TOKEN", "").strip()
    if _is_real(k) and _is_real(t):
        creds.append({
            "api_key":      k,
            "access_token": t,
            "label":        "env:KITE_*",
            "source":       "env_kite",
        })

    return creds


# ── Auth ──────────────────────────────────────────────────────────────
def _try_auth(cred: dict) -> tuple:
    """
    Attempt to authenticate with one credential set.

    Returns (kite_instance, profile_dict) on success.
    Returns (None, error_message_str) on failure.
    Never raises — all exceptions are caught and returned as strings.
    """
    try:
        from kiteconnect import KiteConnect
    except ImportError:
        return None, "kiteconnect not installed — run: pip install kiteconnect"

    try:
        kite = KiteConnect(api_key=cred["api_key"])
        kite.set_access_token(cred["access_token"])
        profile = kite.profile()   # single lightweight validation call
        return kite, profile
    except Exception as exc:
        return None, str(exc)


# ── Field discovery ───────────────────────────────────────────────────
def _walk(obj: Any, prefix: str = "") -> list[tuple[str, str, str]]:
    """
    Recursively walk a JSON structure and return
    (field_path, python_type, sample_value) for every leaf.
    """
    results = []

    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                results.extend(_walk(v, path))
            else:
                results.append((path, type(v).__name__, _sample(v)))

    elif isinstance(obj, list):
        if obj:
            # Walk the first element as representative
            results.extend(_walk(obj[0], f"{prefix}[0]"))
        else:
            results.append((f"{prefix}[]", "list", "(empty)"))

    else:
        results.append((prefix, type(obj).__name__, _sample(obj)))

    return results


def _sample(v: Any, max_len: int = 60) -> str:
    s = repr(v)
    if len(s) > max_len:
        s = s[:max_len] + "…"
    return s


# ── Category detection ────────────────────────────────────────────────
_CATEGORIES = {
    "quantity": [
        "quantity", "qty", "t1_quantity", "t1_qty", "used_quantity", "used_qty",
        "authorised_quantity", "collateral_quantity", "opening_quantity",
        "realised_quantity", "discounted_quantity",
        "buy_quantity", "sell_quantity", "day_buy_quantity", "day_sell_quantity",
        "overnight_quantity",
    ],
    "collateral": [
        "collateral", "pledge", "pledged", "collateral_quantity",
        "collateral_type", "stock_collateral", "liquid_collateral",
        "authorised_quantity", "used_quantity",
    ],
    "margin": [
        "margin", "span", "exposure", "debits", "net", "live_balance",
        "opening_balance", "intraday_payin", "adhoc_margin", "cash",
        "collateral", "option_premium", "utilised", "available",
        "turnover", "payout", "holding_sales", "delivery", "m2m",
    ],
    "pnl": [
        "pnl", "m2m", "realised", "unrealised", "day_m2m",
        "profit", "loss", "buy_m2m", "sell_m2m",
    ],
}

def _categorise(path: str) -> list[str]:
    p_low = path.lower()
    matched = []
    for cat, keywords in _CATEGORIES.items():
        if any(kw in p_low for kw in keywords):
            matched.append(cat)
    return matched


# ── Writers ───────────────────────────────────────────────────────────
def _write_json(data: Any, filename: str) -> Path:
    path = OUT / filename

    # datetime objects from kiteconnect aren't JSON-serialisable — convert them
    def _default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        raise TypeError(f"Not serialisable: {type(o)}")

    path.write_text(json.dumps(data, indent=2, default=_default), encoding="utf-8")
    print(f"  saved → {path}")
    return path


def _write_text(lines: list[str], filename: str) -> Path:
    path = OUT / filename
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  saved → {path}")
    return path


# ── Pretty section printer ────────────────────────────────────────────
SEP = "─" * 72

def _section(title: str):
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


def _preview(data: Any, max_lines: int = 30):
    text = pformat(data, width=100, depth=4)
    lines = text.splitlines()
    for line in lines[:max_lines]:
        print("  " + line)
    if len(lines) > max_lines:
        print(f"  ... ({len(lines) - max_lines} more lines — see JSON file)")


# ── Main ──────────────────────────────────────────────────────────────
def main():
    print(f"\nKite Connect API Schema Inspector")
    print(f"Output directory: {OUT}")
    print(f"Timestamp: {datetime.now().isoformat()}")

    # ── Discover and try credentials in priority order ────────────────
    _section("Credential Discovery & Authentication")
    creds = _discover_credentials()

    if not creds:
        print("  ERROR: no credentials found in DB or .env")
        print("  Ensure at least one of the following is set:")
        print("    data/dashboard.db → stored_tokens table")
        print("    .env: ZERODHA_ACC1_API_KEY + ZERODHA_ACC1_ACCESS_TOKEN")
        print("    .env: KITE_API_KEY + KITE_ACCESS_TOKEN")
        sys.exit(1)

    print(f"  Found {len(creds)} candidate credential set(s):\n")

    kite       = None
    profile_raw = None
    used_cred  = None

    for i, cred in enumerate(creds, 1):
        api_key_preview = cred["api_key"][:6] + "…" if len(cred["api_key"]) > 6 else cred["api_key"]
        token_preview   = cred["access_token"][:6] + "…" if len(cred["access_token"]) > 6 else cred["access_token"]

        print(f"  [{i}/{len(creds)}] {cred['label']}")
        print(f"         api_key      : {api_key_preview}")
        print(f"         access_token : {token_preview}")
        print(f"         → attempting kite.profile() …", end=" ", flush=True)

        result, detail = _try_auth(cred)

        if result is not None:
            # Success
            kite        = result
            profile_raw = detail
            used_cred   = cred
            print("SUCCESS")
            print(f"         ✓ authenticated as {profile_raw.get('user_name', '?')} "
                  f"({profile_raw.get('user_id', '?')})")
            break
        else:
            # Failure — log and continue to next candidate
            print("FAILED")
            print(f"         ✗ {detail}")
            if i < len(creds):
                print(f"         → trying next credential source…\n")

    if kite is None:
        print(f"\n  All {len(creds)} credential source(s) exhausted — none authenticated.")
        print("  To fix: run the dashboard auth page to generate a fresh token,")
        print("  or update KITE_ACCESS_TOKEN / ZERODHA_*_ACCESS_TOKEN in .env")
        sys.exit(1)

    print(f"\n  Selected source : {used_cred['label']}")
    print(f"  User name       : {profile_raw.get('user_name', '?')}")
    print(f"  User ID         : {profile_raw.get('user_id', '?')}")
    print(f"  Email           : {profile_raw.get('email', '?')}")
    print(f"  Exchanges       : {profile_raw.get('exchanges', [])}")
    print(f"  Products        : {profile_raw.get('products', [])}")

    # ── profile() ─────────────────────────────────────────────────────
    _section("kite.profile()")
    _preview(profile_raw)
    _write_json(profile_raw, "profile.json")

    # ── holdings() ────────────────────────────────────────────────────
    _section("kite.holdings()")
    try:
        holdings_raw = kite.holdings()
        print(f"  {len(holdings_raw)} holdings returned")
        if holdings_raw:
            print("\n  First holding (all fields):")
            _preview(holdings_raw[0])
            print(f"\n  ALL fields present in first holding:")
            for k, v in holdings_raw[0].items():
                print(f"    {k:<35} = {_sample(v, 80)}")
        _write_json(holdings_raw, "holdings.json")
    except Exception as e:
        print(f"  FAILED: {e}")
        holdings_raw = []

    # ── positions() ───────────────────────────────────────────────────
    _section("kite.positions()")
    try:
        positions_raw = kite.positions()
        net = positions_raw.get("net", [])
        day = positions_raw.get("day", [])
        print(f"  net positions : {len(net)}")
        print(f"  day positions : {len(day)}")
        if net:
            print("\n  First net position (all fields):")
            _preview(net[0])
            print(f"\n  ALL fields in first net position:")
            for k, v in net[0].items():
                print(f"    {k:<35} = {_sample(v, 80)}")
        _write_json(positions_raw, "positions.json")
    except Exception as e:
        print(f"  FAILED: {e}")
        positions_raw = {}

    # ── margins() ─────────────────────────────────────────────────────
    _section("kite.margins()")
    try:
        margins_raw = kite.margins()
        print("  Top-level keys:", list(margins_raw.keys()))
        for segment, seg_data in margins_raw.items():
            print(f"\n  [{segment}]")
            _preview(seg_data)
            for section_name, section_data in seg_data.items():
                if isinstance(section_data, dict):
                    print(f"\n  [{segment}][{section_name}] — all fields:")
                    for k, v in section_data.items():
                        print(f"    {k:<35} = {_sample(v, 80)}")
        _write_json(margins_raw, "margins.json")
    except Exception as e:
        print(f"  FAILED: {e}")
        margins_raw = {}

    # ── Field discovery ───────────────────────────────────────────────
    _section("Dynamic Field Discovery")

    all_fields: list[tuple[str, str, str, list[str]]] = []  # path, type, sample, categories

    # Walk all four datasets
    datasets = [
        ("profile",   profile_raw),
        ("holdings",  holdings_raw),
        ("positions", positions_raw),
        ("margins",   margins_raw),
    ]
    for ds_name, data in datasets:
        for path, typ, sample in _walk(data, ds_name):
            cats = _categorise(path)
            all_fields.append((path, typ, sample, cats))

    print(f"  {len(all_fields)} total fields discovered")

    # Write discovered_fields.txt
    lines = [
        "Kite Connect API — Discovered Fields",
        f"Generated: {datetime.now().isoformat()}",
        "=" * 72,
        f"{'FIELD PATH':<55} {'TYPE':<12} SAMPLE VALUE",
        "-" * 72,
    ]
    for path, typ, sample, _ in sorted(all_fields):
        lines.append(f"{path:<55} {typ:<12} {sample}")
    _write_text(lines, "discovered_fields.txt")

    # ── Category reports ──────────────────────────────────────────────
    _section("Generating Category Reports")

    for cat in ("quantity", "collateral", "margin", "pnl"):
        matched = [(path, typ, sample) for path, typ, sample, cats in all_fields if cat in cats]
        rlines = [
            f"Kite Connect API — {cat.upper()} Fields",
            f"Generated: {datetime.now().isoformat()}",
            f"Fields matched: {len(matched)}",
            "=" * 72,
            f"{'FIELD PATH':<55} {'TYPE':<12} SAMPLE VALUE",
            "-" * 72,
        ]
        for path, typ, sample in matched:
            rlines.append(f"{path:<55} {typ:<12} {sample}")

        # For quantity/collateral, add semantic notes
        if cat == "quantity":
            rlines += [
                "",
                "=" * 72,
                "SEMANTIC NOTES (from Kite Connect docs v3):",
                "-" * 72,
                "  holdings[].quantity             — free settled qty (EXCLUDES T1, auth-pending, pledged)",
                "  holdings[].t1_quantity           — T+1 unsettled (bought today/yesterday, settling tomorrow)",
                "  holdings[].authorised_quantity   — pledge initiated, CDSL OTP NOT YET DONE",
                "                                     shares are frozen in this state, not in quantity or used_quantity",
                "  holdings[].used_quantity         — pledge fully authorised, margin is live",
                "  holdings[].opening_quantity      — qty at start of day",
                "  holdings[].realised_quantity     — settled qty (overlaps with quantity)",
                "",
                "  CORRECT TOTAL OWNED = quantity + t1_quantity + authorised_quantity + used_quantity",
                "",
                "  WARNING: omitting authorised_quantity causes holdings in mid-pledge-auth state",
                "  to show total_qty=0 and get silently dropped from portfolio valuation.",
            ]
        elif cat == "collateral":
            rlines += [
                "",
                "=" * 72,
                "SEMANTIC NOTES (from Kite Connect docs v3):",
                "-" * 72,
                "  holdings[].collateral_type   — 'margin' if pledged for margin, '' if not",
                "  holdings[].used_quantity     — shares currently pledged",
                "  margins.equity.available.collateral",
                "      — Monetary value of pledged holdings approved as margin (after haircut)",
                "      — This is NOT the market value of pledged holdings",
                "      — Pledged holdings still appear in holdings[] at their full market value",
                "  margins.equity.utilised.stock_collateral",
                "      — Collateral already consumed/blocked against open positions",
                "  margins.equity.utilised.liquid_collateral",
                "      — Liquid fund collateral consumed",
            ]
        elif cat == "margin":
            rlines += [
                "",
                "=" * 72,
                "SEMANTIC NOTES (from Kite Connect docs v3):",
                "-" * 72,
                "  margins.equity.available.cash        — Pure cash balance (bank transfer + P&L credits)",
                "  margins.equity.available.collateral  — Collateral value (pledged stocks, after haircut)",
                "  margins.equity.available.intraday_payin — Intraday credit (not permanent)",
                "  margins.equity.available.live_balance — TOTAL available = cash + collateral - debits",
                "  margins.equity.available.opening_balance — Balance at start of day",
                "  margins.equity.utilised.debits       — TOTAL margin blocked (SPAN+exposure+premium+etc)",
                "  margins.equity.utilised.span         — SPAN margin for F&O positions",
                "  margins.equity.utilised.exposure     — Exposure margin for F&O positions",
                "  margins.equity.utilised.option_premium — Premium blocked for bought options",
                "  margins.equity.utilised.m2m_realised — Realised M2M debits",
                "  margins.equity.utilised.m2m_unrealised — Unrealised M2M (floating loss)",
                "  margins.equity.net                   — Shorthand: live_balance - debits",
            ]
        elif cat == "pnl":
            rlines += [
                "",
                "=" * 72,
                "SEMANTIC NOTES (from Kite Connect docs v3):",
                "-" * 72,
                "  holdings[].pnl               — Unrealized P&L = (last_price - avg_price) * qty",
                "  positions[net][].pnl         — Net position unrealized P&L",
                "  positions[net][].m2m         — Day mark-to-market P&L vs. yesterday close",
                "  positions[net][].realised     — Realized P&L from squared-off intraday legs",
                "  positions[net][].unrealised   — Same as pnl for net positions",
                "  IMPORTANT: 'day_m2m' does NOT exist — the correct field is 'm2m'",
            ]

        fname = f"report_{cat}.txt"
        _write_text(rlines, fname)
        print(f"  {cat}: {len(matched)} fields → {fname}")

    # ── Summary ───────────────────────────────────────────────────────
    _section("Summary")

    summary = [
        f"Total fields discovered : {len(all_fields)}",
        f"Holdings returned       : {len(holdings_raw) if isinstance(holdings_raw, list) else 0}",
        f"Net positions returned  : {len(positions_raw.get('net', [])) if isinstance(positions_raw, dict) else 0}",
        f"Day positions returned  : {len(positions_raw.get('day', [])) if isinstance(positions_raw, dict) else 0}",
        "",
        "Output files:",
        f"  {OUT}/profile.json",
        f"  {OUT}/holdings.json",
        f"  {OUT}/positions.json",
        f"  {OUT}/margins.json",
        f"  {OUT}/discovered_fields.txt",
        f"  {OUT}/report_quantity.txt",
        f"  {OUT}/report_collateral.txt",
        f"  {OUT}/report_margin.txt",
        f"  {OUT}/report_pnl.txt",
    ]

    for line in summary:
        print(f"  {line}" if line else "")

    # Holdings quantity breakdown (if any holdings)
    if isinstance(holdings_raw, list) and holdings_raw:
        print("\n  Holdings quantity breakdown (first 10):")
        print(f"  {'symbol':<20} {'qty':>6} {'t1_qty':>8} {'used_qty':>9} {'total':>7} {'lp':>10} {'collateral_type'}")
        print(f"  {'-'*80}")
        for r in holdings_raw[:10]:
            sym   = str(r.get("tradingsymbol", "?"))[:20]
            qty   = r.get("quantity", "?")
            t1    = r.get("t1_quantity", "?")
            used  = r.get("used_quantity", "?")
            lp    = r.get("last_price", "?")
            ct    = r.get("collateral_type", "")
            try:
                total = int(qty or 0) + int(t1 or 0) + int(used or 0)
            except Exception:
                total = "?"
            print(f"  {sym:<20} {str(qty):>6} {str(t1):>8} {str(used):>9} {str(total):>7} {str(lp):>10}  {ct}")

    # Margin key values
    if isinstance(margins_raw, dict) and "equity" in margins_raw:
        eq  = margins_raw["equity"]
        av  = eq.get("available", {})
        ut  = eq.get("utilised", {})
        print("\n  Equity margin key values:")
        print(f"    available.cash           = {av.get('cash')}")
        print(f"    available.collateral     = {av.get('collateral')}")
        print(f"    available.live_balance   = {av.get('live_balance')}")
        print(f"    available.opening_balance= {av.get('opening_balance')}")
        print(f"    available.intraday_payin = {av.get('intraday_payin')}")
        print(f"    utilised.debits          = {ut.get('debits')}")
        print(f"    utilised.span            = {ut.get('span')}")
        print(f"    utilised.exposure        = {ut.get('exposure')}")
        print(f"    utilised.option_premium  = {ut.get('option_premium')}")
        print(f"    utilised.m2m_realised    = {ut.get('m2m_realised')}")
        print(f"    utilised.m2m_unrealised  = {ut.get('m2m_unrealised')}")
        print(f"    utilised.stock_collateral= {ut.get('stock_collateral')}")
        print(f"    utilised.liquid_collateral={ut.get('liquid_collateral')}")
        print(f"    net                      = {eq.get('net')}")

    print(f"\n  Done. All outputs in: {OUT}/")


if __name__ == "__main__":
    main()
