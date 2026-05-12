"""
Dark terminal theme — professional prop-desk / portfolio monitor aesthetic.
Deep dark base with purple/blue accent system.
"""

# ── Palette ────────────────────────────────────────────────────────────
C = {
    "bg":          "#09090f",
    "surface":     "#0d0e1a",
    "card":        "#0f1022",
    "card_hover":  "#141530",
    "border":      "#1c1f3a",
    "border_glow": "#2d3170",
    "accent":      "#6d28d9",   # purple
    "accent2":     "#2563eb",   # blue
    "accent_dim":  "rgba(109,40,217,0.12)",
    "positive":    "#10b981",
    "negative":    "#ef4444",
    "warning":     "#f59e0b",
    "text_1":      "#eef0f8",   # primary
    "text_2":      "#8892b0",   # secondary
    "text_3":      "#454a6e",   # muted
}

TERMINAL_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Reset ─────────────────────────────────────────────────────── */
html, body, [class*="css"] {{
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    -webkit-font-smoothing: antialiased;
}}

/* ── App shell ─────────────────────────────────────────────────── */
.stApp {{
    background-color: {C["bg"]};
    color: {C["text_1"]};
}}
.block-container {{
    padding-top: 1rem !important;
    padding-bottom: 2rem !important;
    max-width: 100% !important;
}}

/* ── Sidebar ───────────────────────────────────────────────────── */
[data-testid="stSidebar"] {{
    background: {C["surface"]} !important;
    border-right: 1px solid {C["border"]} !important;
}}
[data-testid="stSidebar"] * {{
    color: {C["text_2"]} !important;
}}

/* ── Dividers ──────────────────────────────────────────────────── */
hr {{
    border: none !important;
    border-top: 1px solid {C["border"]} !important;
    margin: 0.75rem 0 !important;
}}

/* ── DataFrames ─────────────────────────────────────────────────── */
.stDataFrame, .stDataFrame table {{
    background: {C["card"]} !important;
    color: {C["text_1"]} !important;
    border: 1px solid {C["border"]} !important;
    border-radius: 8px;
    font-size: 0.82rem;
}}
.stDataFrame th {{
    background: #0a0b18 !important;
    color: {C["text_3"]} !important;
    font-size: 0.68rem !important;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    font-weight: 600;
    border-bottom: 1px solid {C["border"]} !important;
    padding: 8px 10px !important;
}}
.stDataFrame td {{
    border-bottom: 1px solid {C["border"]} !important;
    padding: 6px 10px !important;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.8rem !important;
}}
.stDataFrame tr:hover td {{
    background: rgba(45,49,112,0.25) !important;
}}

/* ── Tabs ───────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {{
    background: {C["surface"]};
    border-bottom: 1px solid {C["border"]};
    gap: 2px;
}}
.stTabs [data-baseweb="tab"] {{
    color: {C["text_3"]} !important;
    background: transparent !important;
    font-size: 0.82rem;
    font-weight: 500;
    padding: 8px 18px;
    border-radius: 4px 4px 0 0;
    letter-spacing: 0.02em;
}}
.stTabs [aria-selected="true"] {{
    color: #a78bfa !important;
    border-bottom: 2px solid #7c3aed !important;
    background: rgba(109,40,217,0.08) !important;
}}

/* ── Select ─────────────────────────────────────────────────────── */
.stSelectbox > div > div {{
    background: {C["card"]} !important;
    border: 1px solid {C["border"]} !important;
    color: {C["text_1"]} !important;
    border-radius: 6px;
    font-size: 0.83rem;
}}

/* ── Buttons ─────────────────────────────────────────────────────── */
.stButton > button {{
    background: linear-gradient(135deg, #4c1d95, #2563eb);
    color: #fff;
    border: none;
    border-radius: 6px;
    font-weight: 600;
    font-size: 0.82rem;
    padding: 6px 18px;
    letter-spacing: 0.03em;
    transition: opacity 0.15s;
}}
.stButton > button:hover {{
    opacity: 0.85;
}}

/* ── Radio ───────────────────────────────────────────────────────── */
div[data-testid="stRadio"] > div {{
    flex-direction: row;
    gap: 6px;
}}
div[data-testid="stRadio"] label {{
    background: {C["card"]};
    border: 1px solid {C["border"]};
    border-radius: 20px;
    padding: 3px 14px;
    font-size: 0.78rem;
    color: {C["text_2"]};
    cursor: pointer;
    transition: all 0.15s;
}}
div[data-testid="stRadio"] label:has(input:checked) {{
    background: rgba(109,40,217,0.18);
    border-color: #7c3aed;
    color: #a78bfa;
    font-weight: 600;
}}

/* ── Expander ────────────────────────────────────────────────────── */
.streamlit-expanderHeader {{
    background: {C["card"]} !important;
    color: {C["text_2"]} !important;
    border: 1px solid {C["border"]} !important;
    border-radius: 6px !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
}}
.streamlit-expanderHeader:hover {{
    border-color: {C["border_glow"]} !important;
    color: #a78bfa !important;
}}
.streamlit-expanderContent {{
    border: 1px solid {C["border"]} !important;
    border-top: none !important;
    border-radius: 0 0 6px 6px !important;
    background: {C["bg"]} !important;
}}

/* ── Alerts ──────────────────────────────────────────────────────── */
.stAlert {{
    border-radius: 6px;
    border: 1px solid {C["border"]};
    background: {C["card"]};
}}

/* ── Headers ─────────────────────────────────────────────────────── */
h1, h2, h3, h4 {{ color: {C["text_1"]} !important; }}
h3 {{ font-size: 0.9rem !important; font-weight: 600; color: {C["text_2"]} !important; }}

/* ── Plotly backgrounds ──────────────────────────────────────────── */
.js-plotly-plot .plotly .bg {{ fill: {C["card"]} !important; }}
</style>
"""


def apply_theme():
    import streamlit as st
    st.markdown(TERMINAL_CSS, unsafe_allow_html=True)


def color_pnl(value: float) -> str:
    return C["positive"] if value >= 0 else C["negative"]


def format_inr(value: float, compact: bool = True) -> str:
    """Format in Indian number system."""
    neg = value < 0
    v = abs(value)
    if compact:
        if v >= 1_00_00_000:
            s = f"&#8377;{v/1_00_00_000:.2f}Cr"
        elif v >= 1_00_000:
            s = f"&#8377;{v/1_00_000:.2f}L"
        else:
            s = f"&#8377;{v:,.0f}"
    else:
        s = f"&#8377;{v:,.2f}"
    return f"-{s}" if neg else s


def format_inr_plain(value: float) -> str:
    """Plain ₹ string (no HTML entity, for st.metric)."""
    neg = value < 0
    v = abs(value)
    if v >= 1_00_00_000:
        s = f"₹{v/1_00_00_000:.2f}Cr"
    elif v >= 1_00_000:
        s = f"₹{v/1_00_000:.2f}L"
    else:
        s = f"₹{v:,.0f}"
    return f"-{s}" if neg else s


def format_pct(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def signed_color(value: float, pos: str = None, neg: str = None) -> str:
    return (pos or C["positive"]) if value >= 0 else (neg or C["negative"])
