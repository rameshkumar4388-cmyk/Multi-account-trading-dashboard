"""
Runtime Synchronisation Verifier
==================================
Answers definitively: is the live process executing the new adapter code?

Run on the VPS:
    cd /path/to/dashboard
    python scripts/verify_runtime.py

Checks performed:
  1. Source file — does adapter.py on disk contain authorised_quantity?
  2. Pyc cache   — is the cached bytecode newer than the source file?
  3. Git state   — branch, HEAD commit, uncommitted changes
  4. Module import — which file does Python actually load?
  5. Live formula  — does the loaded class contain the 4-field formula?
  6. Live API call — fetches first holding and logs all 4 qty fields
  7. Process list  — shows running Streamlit/Python processes + cwd
  8. Multiple copies — scans for other adapter.py files on the system

Exit codes:
  0 — all checks passed, runtime is executing the new code
  1 — at least one check failed or the old code is still running
"""
from __future__ import annotations

import importlib
import inspect
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
PASS = "\033[32m[PASS]\033[0m"
FAIL = "\033[31m[FAIL]\033[0m"
WARN = "\033[33m[WARN]\033[0m"
INFO = "\033[36m[INFO]\033[0m"

failures: list[str] = []
SEP = "─" * 72


def ok(msg):  print(f"  {PASS} {msg}")
def fail(msg): print(f"  {FAIL} {msg}"); failures.append(msg)
def warn(msg): print(f"  {WARN} {msg}")
def info(msg): print(f"  {INFO} {msg}")
def hr(title=""): print(f"\n{SEP}\n  {title}\n{SEP}" if title else SEP)


# ── 1. Source file on disk ────────────────────────────────────────────
hr("1. ADAPTER SOURCE FILE ON DISK")

adapter_src = ROOT / "brokers" / "zerodha" / "adapter.py"
info(f"Expected path : {adapter_src}")

if not adapter_src.exists():
    fail(f"File not found: {adapter_src}")
else:
    ok(f"File exists: {adapter_src}")
    src_text = adapter_src.read_text(encoding="utf-8")

    mtime = datetime.fromtimestamp(adapter_src.stat().st_mtime)
    info(f"Last modified : {mtime}")

    if "authorised_quantity" in src_text:
        ok("Source contains 'authorised_quantity' — fix IS in source file")
        # Find the exact line
        for i, line in enumerate(src_text.splitlines(), 1):
            if "authorised_quantity" in line:
                info(f"  line {i:4d}: {line.strip()}")
    else:
        fail("Source does NOT contain 'authorised_quantity' — source file is the old version")

    if "auth_qty" in src_text:
        ok("Source contains 'auth_qty' variable")
    else:
        fail("Source does NOT contain 'auth_qty' — old code path")

    # Count quantity fields in the formula line
    formula_lines = [l.strip() for l in src_text.splitlines()
                     if "total_qty" in l and ("free_qty" in l or "auth_qty" in l or "t1_qty" in l)]
    if formula_lines:
        info(f"total_qty formula: {formula_lines[0]}")
        if "auth_qty" in formula_lines[0]:
            ok("Formula includes auth_qty (4-field formula)")
        else:
            fail("Formula does NOT include auth_qty (old 3-field formula still in source)")


# ── 2. Pyc cache vs source ────────────────────────────────────────────
hr("2. PYC BYTECODE CACHE")

pyc_dir = ROOT / "brokers" / "zerodha" / "__pycache__"
if not pyc_dir.exists():
    warn("No __pycache__ directory found — will be compiled fresh on next import")
else:
    pyc_files = sorted(pyc_dir.glob("adapter.cpython-*.pyc"))
    if not pyc_files:
        warn("No adapter.pyc found in __pycache__")
    else:
        for pyc in pyc_files:
            pyc_mtime = datetime.fromtimestamp(pyc.stat().st_mtime)
            src_mtime_ts = adapter_src.stat().st_mtime
            pyc_mtime_ts = pyc.stat().st_mtime
            info(f"Pyc file : {pyc.name}")
            info(f"  src mtime : {datetime.fromtimestamp(src_mtime_ts)}")
            info(f"  pyc mtime : {pyc_mtime}")

            if pyc_mtime_ts >= src_mtime_ts:
                ok("Pyc is newer than or equal to source — should be in sync")
            else:
                fail(
                    f"Pyc is OLDER than source by "
                    f"{src_mtime_ts - pyc_mtime_ts:.0f}s — "
                    "stale bytecode may be used if Python doesn't recompile"
                )
                info("Fix: delete __pycache__ directories and restart")

            # Read pyc and check for the string 'authorised_quantity' in bytecode
            pyc_bytes = pyc.read_bytes()
            if b"authorised_quantity" in pyc_bytes:
                ok("Pyc bytecode CONTAINS 'authorised_quantity' — compiled from new source")
            else:
                fail(
                    "Pyc bytecode does NOT contain 'authorised_quantity' — "
                    "bytecode was compiled from old source and is still being used"
                )
                info("Fix: delete __pycache__ and restart Streamlit")


# ── 3. Git state ──────────────────────────────────────────────────────
hr("3. GIT STATE")

def run_git(cmd):
    try:
        result = subprocess.run(
            cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip(), result.returncode
    except Exception as e:
        return str(e), -1

branch, rc = run_git(["git", "rev-parse", "--abbrev-ref", "HEAD"])
info(f"Branch : {branch}")

commit, rc = run_git(["git", "log", "-1", "--format=%H %s"])
info(f"HEAD   : {commit}")

# Check if latest commit contains the fix
if "authorised_quantity" in commit or "auth" in commit.lower():
    ok("HEAD commit message references the fix")
else:
    warn("HEAD commit message doesn't obviously reference the fix — verify manually")

# Check for the fix keyword in the last 5 commits
log, _ = run_git(["git", "log", "-5", "--oneline"])
info("Last 5 commits:")
for line in log.splitlines():
    info(f"  {line}")

# Check for uncommitted changes to adapter.py
diff, _ = run_git(["git", "diff", "HEAD", "--", "brokers/zerodha/adapter.py"])
if diff.strip():
    warn("adapter.py has uncommitted local changes (not yet in HEAD):")
    for line in diff.splitlines()[:20]:
        info(f"  {line}")
else:
    ok("adapter.py has no uncommitted changes — source matches HEAD")

# Check if remote is ahead
remote_status, _ = run_git(["git", "status", "-sb"])
info(f"Remote status: {remote_status.splitlines()[0] if remote_status else '?'}")
if "behind" in remote_status:
    fail("Local branch is BEHIND remote — git pull needed")
elif "ahead" in remote_status:
    warn("Local branch is AHEAD of remote — push needed")
else:
    ok("Branch is in sync with remote")


# ── 4. Module import path ─────────────────────────────────────────────
hr("4. PYTHON MODULE IMPORT PATH")

sys.path.insert(0, str(ROOT))

# Force fresh import by removing any cached version
for key in list(sys.modules.keys()):
    if "adapter" in key or "zerodha" in key or "brokers" in key:
        del sys.modules[key]

try:
    from brokers.zerodha.adapter import ZerodhaAdapter
    loaded_file = inspect.getfile(ZerodhaAdapter)
    info(f"Imported from : {loaded_file}")

    if Path(loaded_file).resolve() == adapter_src.resolve():
        ok("Import path matches expected source file")
    else:
        fail(f"Import path MISMATCH — expected {adapter_src}, got {loaded_file}")

    # Inspect the actual source code of the loaded class
    try:
        loaded_src = inspect.getsource(ZerodhaAdapter.get_holdings)
        if "authorised_quantity" in loaded_src:
            ok("Loaded get_holdings() source contains 'authorised_quantity'")
            for i, line in enumerate(loaded_src.splitlines(), 1):
                if "authorised_quantity" in line or "total_qty" in line:
                    info(f"  line {i:3d}: {line.rstrip()}")
        else:
            fail(
                "Loaded get_holdings() does NOT contain 'authorised_quantity' — "
                "the old version is loaded in memory"
            )
            info("This means Python imported a stale .pyc or a different file.")
    except Exception as e:
        warn(f"Could not inspect loaded source: {e}")

except ImportError as e:
    fail(f"Could not import ZerodhaAdapter: {e}")


# ── 5. Multiple adapter.py copies ────────────────────────────────────
hr("5. MULTIPLE ADAPTER.PY FILES ON THE SYSTEM")

search_dirs = [
    Path.home(),
    Path("/opt"),
    Path("/srv"),
    Path("/var"),
    Path("/home"),
    Path("/root"),
]

found_adapters: list[Path] = []
for search_root in search_dirs:
    if not search_root.exists():
        continue
    try:
        for p in search_root.rglob("adapter.py"):
            if "zerodha" in str(p) and "__pycache__" not in str(p):
                found_adapters.append(p)
    except PermissionError:
        pass

# Always include the expected one
if adapter_src not in found_adapters:
    found_adapters.insert(0, adapter_src)

info(f"Found {len(found_adapters)} zerodha adapter.py file(s):")
for p in found_adapters:
    has_fix = "authorised_quantity" in p.read_text(encoding="utf-8", errors="replace")
    marker = "✓ has fix" if has_fix else "✗ OLD CODE"
    active = " ← THIS IS THE ONE IMPORTED" if p.resolve() == Path(loaded_file).resolve() else ""
    line = f"  {marker}  {p}{active}"
    if not has_fix:
        fail(f"Old adapter found at {p}")
    else:
        ok(f"Fixed adapter at {p}{active}")


# ── 6. Running Streamlit processes ───────────────────────────────────
hr("6. RUNNING STREAMLIT / PYTHON PROCESSES")

try:
    ps_out = subprocess.run(
        ["ps", "aux"], capture_output=True, text=True, timeout=5
    ).stdout
    streamlit_procs = [
        line for line in ps_out.splitlines()
        if "streamlit" in line.lower() or ("python" in line.lower() and "main.py" in line.lower())
    ]
    if streamlit_procs:
        info(f"Found {len(streamlit_procs)} Streamlit/Python process(es):")
        for line in streamlit_procs:
            # Print PID, command, and working directory portions
            parts = line.split()
            pid  = parts[1] if len(parts) > 1 else "?"
            cmd  = " ".join(parts[10:]) if len(parts) > 10 else line
            info(f"  PID={pid}: {cmd[:120]}")
            # Try to get the cwd of this process
            try:
                cwd = Path(f"/proc/{pid}/cwd").resolve()
                info(f"    cwd → {cwd}")
                if cwd.resolve() != ROOT.resolve():
                    fail(f"Process PID={pid} is running from {cwd}, expected {ROOT}")
                else:
                    ok(f"Process PID={pid} cwd matches project root")
            except Exception:
                pass
    else:
        warn("No running Streamlit or main.py processes found")
        info("The app may not be running, or ps output was filtered")
except FileNotFoundError:
    # Windows — use tasklist
    try:
        ps_out = subprocess.run(
            ["tasklist", "/FO", "CSV"], capture_output=True, text=True
        ).stdout
        py_procs = [l for l in ps_out.splitlines() if "python" in l.lower()]
        if py_procs:
            info(f"Python processes: {len(py_procs)}")
            for l in py_procs[:5]:
                info(f"  {l}")
        else:
            warn("No Python processes found via tasklist")
    except Exception as e:
        warn(f"Could not list processes: {e}")


# ── 7. Live API call with 4-field trace ──────────────────────────────
hr("7. LIVE API CALL — QUANTITY FIELD TRACE FOR FIRST HOLDING")

# Load .env
def _load_dotenv(path):
    if not Path(path).exists(): return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, _, v = line.partition("=")
        k = k.strip(); v = v.strip().strip('"').strip("'")
        if k and k not in os.environ: os.environ[k] = v

_load_dotenv(ROOT / ".env")

# Get credentials (DB first)
import sqlite3
PLACEHOLDER = {"", "your_api_key_here", "your_access_token_here", "xxx"}
def _real(v): return bool(v) and v.strip() not in PLACEHOLDER

cred = None
db_path = ROOT / os.getenv("DB_PATH", "data/dashboard.db")
if db_path.exists():
    try:
        con = sqlite3.connect(str(db_path))
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM stored_tokens ORDER BY generated_at DESC").fetchall()
        con.close()
        for row in rows:
            if _real(row["api_key"]) and _real(row["access_token"]):
                cred = {"api_key": row["api_key"], "access_token": row["access_token"],
                        "label": f"DB:{row['account_id']}"}
                break
    except Exception as e:
        warn(f"DB read failed: {e}")

if not cred:
    for prefix in ["KITE", "ZERODHA"]:
        k = os.getenv(f"{prefix}_API_KEY", "").strip()
        t = os.getenv(f"{prefix}_ACCESS_TOKEN", "").strip()
        if _real(k) and _real(t):
            cred = {"api_key": k, "access_token": t, "label": f"env:{prefix}_*"}
            break

if not cred:
    warn("No credentials found — skipping live API call")
    info("Set KITE_API_KEY+KITE_ACCESS_TOKEN in .env or run the auth page to store a token")
else:
    info(f"Using credentials: {cred['label']}")
    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=cred["api_key"])
        kite.set_access_token(cred["access_token"])
        profile = kite.profile()
        ok(f"Authenticated as {profile.get('user_name')} ({profile.get('user_id')})")

        t0 = time.monotonic()
        raw = kite.holdings()
        ms = (time.monotonic() - t0) * 1000
        info(f"kite.holdings() returned {len(raw)} rows in {ms:.0f}ms")

        if not raw:
            warn("API returned 0 holdings rows — nothing to trace")
        else:
            print(f"\n  {'symbol':<22} {'qty':>5} {'t1':>5} {'auth':>6} {'used':>6} {'total':>7}  {'lp':>10}  status")
            print(f"  {'-'*80}")
            for r in raw:
                sym  = str(r.get("tradingsymbol", "?"))[:22]
                qty  = int(r.get("quantity", 0)            or 0)
                t1   = int(r.get("t1_quantity", 0)         or 0)
                auth = int(r.get("authorised_quantity", 0) or 0)
                used = int(r.get("used_quantity", 0)       or 0)
                tot  = qty + t1 + auth + used
                lp   = r.get("last_price", "?")
                ct   = r.get("collateral_type", "")
                status = ""
                if tot == 0:
                    status = "← WOULD BE SKIPPED"
                elif auth > 0 and used == 0:
                    status = "← PLEDGE PENDING AUTH"
                elif used > 0:
                    status = "← PLEDGED"
                elif t1 > 0 and qty == 0:
                    status = "← T+1 ONLY"
                print(f"  {sym:<22} {qty:>5} {t1:>5} {auth:>6} {used:>6} {tot:>7}  {str(lp):>10}  {status}")

    except Exception as e:
        fail(f"Live API call failed: {e}")


# ── Summary ───────────────────────────────────────────────────────────
hr("SUMMARY")

if not failures:
    print(f"\n  {PASS} All checks passed.")
    print("  The runtime IS executing the new 4-field quantity logic.")
    print("  If the dashboard still shows wrong values, clear @st.cache_resource")
    print("  via the 🔬 Debug Trace page → 'Clear All Caches' button.")
else:
    print(f"\n  {FAIL} {len(failures)} check(s) failed:\n")
    for f in failures:
        print(f"    ✗ {f}")
    print()
    print("  Likely fix sequence:")
    print("    1.  cd /path/to/dashboard && git pull")
    print("    2.  find . -type d -name __pycache__ | xargs rm -rf")
    print("    3.  pkill -f 'streamlit run'   (or systemctl restart <service>)")
    print("    4.  streamlit run main.py --server.headless true &")
    print("    5.  Re-run this script to confirm")

sys.exit(0 if not failures else 1)
