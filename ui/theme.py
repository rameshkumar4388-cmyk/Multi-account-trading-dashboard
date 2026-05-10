"""
Dark professional theme for the trading dashboard.
Inject via apply_theme() at app startup.
"""

DARK_CSS = """
<style>
/* ── Global reset ────────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
}

/* ── Terminal number style ───────────────────────────────── */
.terminal-num {
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.01em;
}

/* ── Expander (for grouped positions view) ───────────────── */
.streamlit-expanderHeader {
    background-color: #161b22 !important;
    color: #c9d1d9 !important;
    border: 1px solid #30363d !important;
    border-radius: 6px !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
}
.streamlit-expanderHeader:hover {
    border-color: #58a6ff !important;
    color: #58a6ff !important;
}
.streamlit-expanderContent {
    border: 1px solid #21262d !important;
    border-top: none !important;
    border-radius: 0 0 6px 6px !important;
    background: #0d1117 !important;
}

/* ── Radio pills (view toggle) ───────────────────────────── */
div[data-testid="stRadio"] > div {
    flex-direction: row;
    gap: 6px;
}
div[data-testid="stRadio"] label {
    background: #21262d;
    border: 1px solid #30363d;
    border-radius: 20px;
    padding: 3px 14px;
    font-size: 0.78rem;
    color: #8b949e;
    cursor: pointer;
    transition: all 0.15s;
}
div[data-testid="stRadio"] label:has(input:checked) {
    background: #1f4287;
    border-color: #58a6ff;
    color: #58a6ff;
    font-weight: 600;
}

/* ── App background ──────────────────────────────────────── */
.stApp {
    background-color: #0d1117;
    color: #e6edf3;
}

/* ── Sidebar ─────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: #161b22 !important;
    border-right: 1px solid #30363d;
}
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] span {
    color: #c9d1d9 !important;
}

/* ── Metric cards ────────────────────────────────────────── */
[data-testid="stMetric"] {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 14px 18px;
    margin: 4px;
}
[data-testid="stMetricValue"] {
    font-size: 1.6rem !important;
    font-weight: 700;
    color: #e6edf3;
}
[data-testid="stMetricLabel"] {
    color: #8b949e !important;
    font-size: 0.78rem !important;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
[data-testid="stMetricDelta"] svg { display: none; }

/* ── Positive / negative delta colours ──────────────────── */
[data-testid="stMetricDelta"][data-direction="up"] {
    color: #3fb950 !important;
}
[data-testid="stMetricDelta"][data-direction="down"] {
    color: #f85149 !important;
}

/* ── DataFrames / tables ─────────────────────────────────── */
.stDataFrame, .stDataFrame table {
    background-color: #161b22 !important;
    color: #e6edf3 !important;
    border: 1px solid #30363d !important;
    border-radius: 8px;
}
.stDataFrame th {
    background-color: #21262d !important;
    color: #8b949e !important;
    font-size: 0.76rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 1px solid #30363d !important;
}
.stDataFrame td {
    border-bottom: 1px solid #21262d !important;
    font-size: 0.85rem;
}
.stDataFrame tr:hover td {
    background-color: #1f2937 !important;
}

/* ── Tabs ────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    background-color: #161b22;
    border-bottom: 1px solid #30363d;
    gap: 4px;
}
.stTabs [data-baseweb="tab"] {
    color: #8b949e !important;
    background-color: transparent !important;
    border-radius: 6px 6px 0 0;
    font-weight: 500;
    font-size: 0.88rem;
    padding: 8px 16px;
}
.stTabs [aria-selected="true"] {
    color: #58a6ff !important;
    border-bottom: 2px solid #58a6ff !important;
    background-color: #1f2937 !important;
}

/* ── Select boxes ────────────────────────────────────────── */
.stSelectbox > div > div {
    background-color: #21262d !important;
    border: 1px solid #30363d !important;
    color: #e6edf3 !important;
    border-radius: 6px;
}

/* ── Buttons ─────────────────────────────────────────────── */
.stButton > button {
    background-color: #238636;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    font-weight: 600;
    padding: 6px 16px;
    transition: background-color 0.2s;
}
.stButton > button:hover {
    background-color: #2ea043;
}

/* ── Dividers ────────────────────────────────────────────── */
hr { border-color: #30363d !important; }

/* ── Section headers ─────────────────────────────────────── */
h1, h2, h3, h4 { color: #e6edf3 !important; }
h3 { font-size: 1rem; font-weight: 600; color: #8b949e !important; }

/* ── Spinner / info boxes ────────────────────────────────── */
.stAlert {
    border-radius: 8px;
    border: 1px solid #30363d;
}

/* ── Status badge ────────────────────────────────────────── */
.badge-live {
    display: inline-block;
    background: #238636;
    color: #fff;
    font-size: 0.7rem;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 12px;
    letter-spacing: 0.08em;
    vertical-align: middle;
    margin-left: 8px;
}
.badge-mock {
    display: inline-block;
    background: #6e7681;
    color: #fff;
    font-size: 0.7rem;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 12px;
    letter-spacing: 0.08em;
    vertical-align: middle;
    margin-left: 8px;
}

/* ── Plotly chart backgrounds ────────────────────────────── */
.js-plotly-plot .plotly .bg { fill: #161b22 !important; }

/* ── Expander ────────────────────────────────────────────── */
.streamlit-expanderHeader {
    background-color: #161b22 !important;
    color: #c9d1d9 !important;
    border: 1px solid #30363d !important;
    border-radius: 6px;
}
</style>
"""


def apply_theme():
    import streamlit as st
    st.markdown(DARK_CSS, unsafe_allow_html=True)


def color_pnl(value: float) -> str:
    """Return green/red hex colour string based on P&L sign."""
    return "#3fb950" if value >= 0 else "#f85149"


def format_inr(value: float, decimals: int = 2) -> str:
    """Format a number in Indian numbering system with ₹ prefix."""
    if abs(value) >= 1_00_00_000:      # 1 crore
        return f"₹{value / 1_00_00_000:.2f} Cr"
    if abs(value) >= 1_00_000:          # 1 lakh
        return f"₹{value / 1_00_000:.2f} L"
    return f"₹{value:,.{decimals}f}"


def format_pct(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"
