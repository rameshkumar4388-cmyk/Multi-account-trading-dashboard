"""
NSE market session detector and IST clock.

Timezone: Asia/Kolkata (UTC+5:30) — always fixed offset, no DST.
Trading hours: pre-open 09:00, open 09:15, close 15:30, post-close 15:40.
Holidays: official NSE equity segment holiday list.

Update _NSE_HOLIDAYS annually from: https://www.nseindia.com/resources/exchange-communication-holidays
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone, timedelta
from typing import Optional, Tuple

_IST = timezone(timedelta(hours=5, minutes=30))


# ── NSE Equity Holidays 2025–2026 ────────────────────────────────────
# Source: NSE circular list. Update each October for the coming year.
_NSE_HOLIDAYS: set[date] = {
    # 2025
    date(2025, 2, 26),   # Mahashivratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-Ul-Fitr (Ramzan Id)
    date(2025, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti / Visu
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 27),   # Ganesh Chaturthi
    date(2025, 10, 2),   # Gandhi Jayanti
    date(2025, 10, 2),   # Dussehra
    date(2025, 10, 24),  # Diwali — Laxmi Puja (Muhurat trading day)
    date(2025, 10, 25),  # Diwali — Balipratipada
    date(2025, 11, 5),   # Prakash Gurpurab (Gurunanak Jayanti)
    date(2025, 11, 5),   # Gurunanak Jayanti
    date(2025, 12, 25),  # Christmas
    # 2026  (confirm with NSE circular when published)
    date(2026, 1, 26),   # Republic Day
    date(2026, 2, 26),   # Mahashivratri (approx)
    date(2026, 3, 3),    # Holi (approx)
    date(2026, 3, 20),   # Id-Ul-Fitr (approx, lunar calendar)
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 8, 15),   # Independence Day
    date(2026, 10, 2),   # Gandhi Jayanti
    date(2026, 10, 14),  # Diwali — Laxmi Puja (approx)
    date(2026, 11, 5),   # Gurunanak Jayanti (approx)
    date(2026, 12, 25),  # Christmas
}

# Special Muhurat trading sessions: {date: (start_ist, end_ist)}
_MUHURAT_SESSIONS: dict[date, Tuple[time, time]] = {
    date(2025, 10, 20): (time(18, 15), time(19, 15)),  # Diwali 2025 Muhurat
    date(2026, 10, 13): (time(18, 15), time(19, 15)),  # Diwali 2026 Muhurat (approx)
}

# Market session windows (IST times, 24-hour)
_PRE_OPEN_START = time(9, 0)
_MARKET_OPEN    = time(9, 15)
_MARKET_CLOSE   = time(15, 30)
_POST_CLOSE_END = time(15, 40)


def _ist_now() -> datetime:
    return datetime.now(_IST)


def get_session_info() -> dict:
    """
    Return full session metadata for the current IST moment.

    Keys:
      status: "open" | "pre_open" | "post_close" | "closed" | "holiday" | "weekend" | "muhurat"
      label:  human-readable status string
      color:  hex colour for the badge
      ist_now: current datetime in IST
      is_trading_day: bool
    """
    now  = _ist_now()
    today = now.date()
    t    = now.time()

    # Weekend
    if today.weekday() >= 5:
        return _session("weekend", now)

    # Muhurat session (special evening session on Diwali)
    if today in _MUHURAT_SESSIONS:
        start, end = _MUHURAT_SESSIONS[today]
        if start <= t <= end:
            return _session("muhurat", now)
        # Outside muhurat hours on a holiday — still closed
        if today in _NSE_HOLIDAYS:
            return _session("holiday", now)

    # NSE holiday
    if today in _NSE_HOLIDAYS:
        return _session("holiday", now)

    # Regular trading day — check time windows
    if _PRE_OPEN_START <= t < _MARKET_OPEN:
        return _session("pre_open", now)
    if _MARKET_OPEN <= t <= _MARKET_CLOSE:
        return _session("open", now)
    if _MARKET_CLOSE < t <= _POST_CLOSE_END:
        return _session("post_close", now)

    return _session("closed", now)


_STATUS_META = {
    "open":       ("Market Open",    "#10b981", True),
    "pre_open":   ("Pre-Open",       "#f59e0b", True),
    "post_close": ("Post-Close",     "#6d28d9", True),
    "closed":     ("Market Closed",  "#454a6e", False),
    "weekend":    ("Weekend",        "#454a6e", False),
    "holiday":    ("NSE Holiday",    "#2563eb", False),
    "muhurat":    ("Muhurat Open",   "#f59e0b", True),
}

def _session(status: str, now: datetime) -> dict:
    label, color, active = _STATUS_META.get(status, ("Unknown", "#454a6e", False))
    return {
        "status":          status,
        "label":           label,
        "color":           color,
        "is_active":       active,
        "ist_now":         now,
        "ist_time_str":    now.strftime("%H:%M:%S"),
        "ist_date_str":    now.strftime("%a, %d %b %Y"),
    }


def render_session_badge() -> str:
    """Return an inline HTML badge showing market session + IST time."""
    info = get_session_info()
    dot = "●" if info["is_active"] else "○"
    return (
        f"<span style='display:inline-flex;align-items:center;gap:6px;"
        f"font-size:0.72rem;color:{info['color']};font-weight:600;"
        f"letter-spacing:0.05em;'>"
        f"{dot} {info['label']}</span>"
        f"<span style='font-size:0.68rem;color:#454a6e;margin-left:8px;'>"
        f"IST {info['ist_time_str']}</span>"
    )
