import streamlit as st
import re
import requests, pandas as pd, json, time, datetime
import os, pathlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager

# ── psycopg2 (PostgreSQL driver) ───────────────────────────────────────────────
try:
    import psycopg2
    import psycopg2.pool
except ImportError as _pg_err:
    raise ImportError(
        "psycopg2 not found — install it with:  pip install psycopg2-binary"
    ) from _pg_err

# ── Load .env file if present (optional; falls back to real env vars) ──────────
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()
except ImportError:
    pass  # python-dotenv is optional; set DATABASE_URL in your environment instead

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Registry Intelligence Platform",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Base ── */
.block-container { padding: 0 2rem 3rem !important; max-width: 1500px; }
html, body, [class*="css"] { font-family: 'Inter', system-ui, sans-serif; }

/* ── Hero ── */
.hero {
    background: linear-gradient(160deg, #04070f 0%, #081422 55%, #060d1c 100%);
    border-bottom: 1px solid #12243d;
    padding: 2rem 0 1.6rem;
    margin: 0 -2rem 2rem;
}
.hero-inner { max-width: 1500px; margin: 0 auto; padding: 0 2rem; }
.hero-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 2rem; }
.hero-eyebrow {
    font-size: 0.67rem; font-weight: 700; letter-spacing: 3px;
    text-transform: uppercase; color: #06b6d4;
    margin-bottom: 0.55rem; display: flex; align-items: center; gap: 0.5rem;
}
.hero-eyebrow::before { content:''; display:inline-block; width:18px; height:1px; background:#06b6d4; }
.hero-title { font-size: 1.95rem; font-weight: 800; letter-spacing: -0.6px; color: #f1f5f9; margin: 0; line-height: 1.2; }
.hero-title em { color: #06b6d4; font-style: normal; }
.hero-sub { color: #4a6580; font-size: 0.85rem; margin-top: 0.45rem; line-height: 1.7; max-width: 540px; }
.hero-right { display:flex; flex-direction:column; align-items:flex-end; gap:0.3rem; flex-shrink:0; padding-top:0.2rem; }
.live-badge { display:flex; align-items:center; gap:0.4rem; font-size:0.72rem; color:#10b981; font-weight:600; }
.live-dot { width:7px; height:7px; border-radius:50%; background:#10b981; box-shadow:0 0 6px #10b981; animation:pulse 2s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
.hero-divider { border:none; border-top:1px solid #0f1e30; margin:1.3rem 0 1.2rem; }
.hero-stats { display:flex; gap:2.5rem; }
.hstat-val { font-size:1.35rem; font-weight:800; color:#06b6d4; line-height:1; }
.hstat-lbl { font-size:0.65rem; color:#4a6580; text-transform:uppercase; letter-spacing:0.8px; margin-top:0.15rem; }

/* ── Form ── */
div[data-testid="stForm"] {
    background:#070d1b !important; border:1px solid #12243d !important;
    border-radius:14px !important; padding:1.4rem 1.6rem !important;
}
div[data-testid="stForm"] textarea {
    background:#040810 !important; border:1px solid #1a2d47 !important;
    color:#e2e8f0 !important; font-family:'JetBrains Mono',monospace !important;
    font-size:0.86rem !important; border-radius:8px !important; line-height:1.7 !important;
}
div[data-testid="stForm"] textarea:focus { border-color:#06b6d4 !important; box-shadow:0 0 0 2px rgba(6,182,212,0.1) !important; }

/* ── Scan button ── */
div[data-testid="stFormSubmitButton"]:first-of-type > button {
    background:linear-gradient(135deg,#035a8e 0%,#06b6d4 100%) !important;
    color:#fff !important; border:none !important; border-radius:10px !important;
    font-weight:700 !important; font-size:0.92rem !important; letter-spacing:0.5px !important;
    padding:0.68rem 1.5rem !important; transition:all 0.18s !important;
    box-shadow:0 2px 14px rgba(6,182,212,0.22) !important;
}
div[data-testid="stFormSubmitButton"]:first-of-type > button:hover {
    background:linear-gradient(135deg,#0369a1 0%,#22d3ee 100%) !important;
    transform:translateY(-2px) !important; box-shadow:0 6px 22px rgba(6,182,212,0.38) !important;
}

/* ── KPI metrics ── */
div[data-testid="stMetric"] {
    background:#070d1b; border:1px solid #12243d;
    border-radius:12px; padding:1.1rem 1.3rem; transition:all 0.18s;
}
div[data-testid="stMetric"]:hover { border-color:#06b6d4; box-shadow:0 0 18px rgba(6,182,212,0.08); }
div[data-testid="stMetricValue"] { color:#06b6d4 !important; font-size:2.1rem !important; font-weight:800 !important; }
div[data-testid="stMetricLabel"] { color:#4a7090 !important; font-size:0.7rem !important; text-transform:uppercase; letter-spacing:1px; font-weight:700 !important; }

/* ── Table ── */
div[data-testid="stDataFrame"] { border:1px solid #12243d !important; border-radius:12px !important; overflow:hidden !important; }

/* ── Vuln card ── */
.vuln-card {
    background:rgba(239,68,68,0.04); border:1px solid rgba(239,68,68,0.18);
    border-left:3px solid #ef4444; border-radius:10px;
    padding:0.9rem 1.1rem; margin-bottom:0.55rem;
    display:flex; align-items:flex-start; gap:1rem;
}
.vuln-lib  { font-weight:700; color:#fca5a5; font-size:0.88rem; }
.vuln-meta { font-size:0.73rem; color:#475569; margin-top:0.15rem; }
.vuln-cves {
    font-family:'JetBrains Mono',monospace; font-size:0.76rem; color:#f87171;
    margin-top:0.3rem; background:rgba(239,68,68,0.08);
    padding:0.2rem 0.5rem; border-radius:4px; display:inline-block;
}

/* ── Download buttons ── */
div[data-testid="stDownloadButton"] > button {
    background:#070d1b !important; border:1px solid #12243d !important;
    color:#4a7090 !important; border-radius:8px !important;
    font-size:0.82rem !important; font-weight:600 !important;
    padding:0.5rem 1.1rem !important; transition:all 0.18s !important;
}
div[data-testid="stDownloadButton"] > button:hover {
    border-color:#06b6d4 !important; color:#06b6d4 !important;
    background:rgba(6,182,212,0.05) !important;
}

/* ── Alert / expander ── */
div[data-testid="stAlert"] { border-radius:10px !important; font-size:0.88rem !important; }
div[data-testid="stExpander"] { border:1px solid #12243d !important; border-radius:10px !important; background:#070d1b !important; }
summary { color:#4a7090 !important; font-size:0.83rem !important; }

/* ── Sidebar ── */
section[data-testid="stSidebar"] { background:#060c18 !important; border-right:1px solid #162030 !important; }
section[data-testid="stSidebar"] .stTextInput input {
    background:#0a1525 !important; border-color:#1e3350 !important;
    color:#7eb3d4 !important; font-size:0.81rem !important;
}
section[data-testid="stSidebar"] label { color:#5a89a8 !important; font-size:0.78rem !important; }

/* ── Sidebar section label ── */
.sb-label {
    font-size:0.65rem; font-weight:800; text-transform:uppercase;
    letter-spacing:2px; color:#2e6080;
    margin:1.3rem 0 0.55rem; padding-bottom:0.35rem;
    border-bottom:1px solid #162030;
}

/* ── Registry row ── */
.reg-row {
    display:flex; align-items:center; gap:0.5rem;
    padding:0.3rem 0; font-size:0.78rem;
    border-bottom:1px solid rgba(255,255,255,0.03);
}
.rdot { width:6px; height:6px; border-radius:50%; flex-shrink:0; }
.rdot.on  { background:#10b981; box-shadow:0 0 4px #10b981; }
.rdot.key { background:#f59e0b; box-shadow:0 0 4px #f59e0b; }
.rdot.off { background:#243850; }
.reg-name { color:#6aaac8; font-weight:600; }
.reg-desc { color:#2e6080; font-size:0.7rem; }

/* ── Section label ── */
.sec-label {
    font-size:0.68rem; font-weight:700; text-transform:uppercase;
    letter-spacing:1.5px; color:#2e6080;
    margin:1.6rem 0 0.6rem; padding-bottom:0.35rem;
    border-bottom:1px solid #0f1e30;
}
</style>
""", unsafe_allow_html=True)

# ── Constants ──────────────────────────────────────────────────────────────────
SEARCH_LIMIT = 4
TIMEOUT      = 9

# ── PostgreSQL connection ───────────────────────────────────────────────────────
# Set DATABASE_URL in your .env file or as an environment variable.
# Local:      postgresql://postgres:postgres@localhost:5432/registry_intel
# Production: set DATABASE_URL to your cloud provider's connection string
def _load_db_url() -> str:
    # 1. Environment variable (GitHub Actions, .env, system env)
    url = os.environ.get("DATABASE_URL", "")
    if url and "PASTE_YOUR" not in url:
        return url
    # 2. Read .streamlit/secrets.toml directly (reliable at module load time)
    try:
        _s = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          ".streamlit", "secrets.toml")
        if os.path.exists(_s):
            with open(_s, encoding="utf-8") as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line.startswith("DATABASE_URL"):
                        _parts = _line.split("=", 1)
                        if len(_parts) == 2:
                            _v = _parts[1].strip().strip('"').strip("'")
                            if _v and "PASTE_YOUR" not in _v:
                                return _v
    except Exception:
        pass
    # 3. Fallback: localhost (dev only)
    return "postgresql://postgres:postgres@localhost:5432/registry_intel"

DATABASE_URL = _load_db_url()

# ── Telegram config ────────────────────────────────────────────────────────────
def _load_telegram_config() -> tuple:
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID",   "")
    try:
        _s = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          ".streamlit", "secrets.toml")
        if os.path.exists(_s):
            with open(_s, encoding="utf-8") as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line.startswith("TELEGRAM_BOT_TOKEN"):
                        v = _line.split("=", 1)[1].strip().strip('"').strip("'")
                        if v: token = v
                    elif _line.startswith("TELEGRAM_CHAT_ID"):
                        v = _line.split("=", 1)[1].strip().strip('"').strip("'")
                        if v: chat_id = v
    except Exception:
        pass
    return token, chat_id

_TELEGRAM_TOKEN, _TELEGRAM_CHAT_ID = _load_telegram_config()

_SEV_EMOJI_TG = {"critical": "🚨", "high": "⚠️", "medium": "🔔", "info": "ℹ️"}
_FIELD_LABEL_TG = {
    "maintainer_email_domain": "Email domain changed (P1 — hijack signal)",
    "maintainer":              "Maintainer changed",
    "cves":                    "CVEs detected",
    "version":                 "Version changed",
    "license":                 "License changed",
    "last_updated":            "Last-updated date changed",
}

def _notify_telegram(library: str, registry: str, severity: str,
                     field: str, old_val: str, new_val: str):
    if not _TELEGRAM_TOKEN or not _TELEGRAM_CHAT_ID:
        return
    try:
        em    = _SEV_EMOJI_TG.get(severity, "•")
        label = _FIELD_LABEL_TG.get(field, field)
        text  = (
            f"{em} *{severity.upper()}* — `{library}` · {registry}\n"
            f"*{label}*\n"
            f"Before: `{old_val[:80]}`\n"
            f"After:  `{new_val[:80]}`"
        )
        requests.post(
            f"https://api.telegram.org/bot{_TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": _TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
            timeout=6,
        )
    except Exception:
        pass

_pg_pool: "psycopg2.pool.ThreadedConnectionPool | None" = None

def _get_pg_pool() -> "psycopg2.pool.ThreadedConnectionPool":
    global _pg_pool
    if _pg_pool is None:
        _pg_pool = psycopg2.pool.ThreadedConnectionPool(1, 5, dsn=DATABASE_URL)
    return _pg_pool

@contextmanager
def _pg_conn():
    """Yield a psycopg2 connection from the pool; commit on success, rollback on error."""
    pool = _get_pg_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)

# ── HTML markdown helper ───────────────────────────────────────────────────────
# st.markdown still runs Markdown before rendering HTML. Any line that starts
# with 4 or more spaces is treated as a Markdown code block and the HTML tags
# inside it appear as raw text instead of being rendered. This helper collapses
# leading-space runs of 4+ down to 3 so HTML is always rendered correctly,
# regardless of how the f-string was indented.
def _md(html: str) -> None:
    st.markdown(re.sub(r"(?m)^( {4,})", lambda m: " " * min(len(m.group(1)), 3), html),
                unsafe_allow_html=True)

# ── PostgreSQL cache & persistence ─────────────────────────────────────────────
def _init_db():
    """Create all application tables if they do not already exist."""
    with _pg_conn() as conn:
        cur = conn.cursor()
        # Generic API-response cache (TTL-based)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key  TEXT PRIMARY KEY,
                data TEXT    NOT NULL,
                ts   FLOAT8  NOT NULL
            )
        """)
        # GitHub username → country lookup cache (24 h TTL)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS country_cache (
                username TEXT PRIMARY KEY,
                country  TEXT   NOT NULL,
                ts       FLOAT8 NOT NULL
            )
        """)
        # Per-package profile data (replaces profile_cache/*.json files)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS profile_cache (
                pkg_key  TEXT PRIMARY KEY,
                data     JSONB  NOT NULL,
                saved_at FLOAT8 NOT NULL
            )
        """)
        # Completed scan history — packages + raised queries + risk summary
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scan_history (
                id             SERIAL PRIMARY KEY,
                scanned_at     TIMESTAMPTZ DEFAULT NOW(),
                packages       JSONB,
                raised_queries JSONB,
                summary        JSONB
            )
        """)
        cur.close()


def _country_cache_get(username: str) -> "str | None":
    """Return cached country for username (24-hour TTL). None if missing/expired."""
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT country, ts FROM country_cache WHERE username=%s",
                (username.lower(),)
            )
            r = cur.fetchone()
            cur.close()
        if r and (time.time() - r[1]) < 86400:
            return r[0]
    except Exception:
        pass
    return None


def _country_cache_set(username: str, country: str):
    """Persist country lookup to PostgreSQL."""
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO country_cache (username, country, ts)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (username) DO UPDATE
                   SET country = EXCLUDED.country, ts = EXCLUDED.ts""",
                (username.lower(), country, time.time())
            )
            cur.close()
    except Exception:
        pass


def cache_get(key, ttl=86400):
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT data, ts FROM cache WHERE key=%s", (key,))
            r = cur.fetchone()
            cur.close()
        if r and (time.time() - r[1]) < ttl:
            return json.loads(r[0])
    except Exception:
        pass
    return None


def cache_set(key, data):
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO cache (key, data, ts) VALUES (%s, %s, %s)
                   ON CONFLICT (key) DO UPDATE
                   SET data = EXCLUDED.data, ts = EXCLUDED.ts""",
                (key, json.dumps(data), time.time())
            )
            cur.close()
    except Exception:
        pass


def cache_clear():
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM cache")
            cur.close()
    except Exception:
        pass


def country_cache_clear():
    """Wipe every row in the DB country_cache table.

    Call this when the country-resolution logic has been updated and
    stale cached results (e.g. false 'United States') need to be
    re-resolved with the corrected code.
    """
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM country_cache")
            cur.close()
    except Exception:
        pass


def cache_delete(key):
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM cache WHERE key=%s", (key,))
            cur.close()
    except Exception:
        pass


def save_scan_history(audit_rows: list, raised_queries: list, summary: dict):
    """Persist a completed scan run (raised queries + summary) to PostgreSQL.

    Deduplication: skip insert if an identical set of libraries+registries
    was scanned within the last 5 minutes (prevents double-inserts from
    rapid re-clicks and Streamlit re-runs).
    """
    try:
        # Build a canonical fingerprint: sorted list of "library@registry" strings
        pkg_keys = sorted(
            f"{r.get('Library','?')}@{r.get('Registry','?')}"
            for r in audit_rows
        )
        fingerprint = json.dumps(pkg_keys)

        with _pg_conn() as conn:
            cur = conn.cursor()

            # Deduplication check — same package set scanned in the last 5 min?
            cur.execute(
                """SELECT id FROM scan_history
                   WHERE summary->>'_fingerprint' = %s
                     AND scanned_at >= NOW() - INTERVAL '5 minutes'
                   LIMIT 1""",
                (fingerprint,)
            )
            if cur.fetchone():
                cur.close()
                return   # duplicate — skip

            # Embed fingerprint in summary so the dedup query works
            summary_stored = dict(summary)
            summary_stored["_fingerprint"] = fingerprint

            cur.execute(
                """INSERT INTO scan_history (raised_queries, summary)
                   VALUES (%s::jsonb, %s::jsonb)""",
                (
                    json.dumps(raised_queries, default=str),
                    json.dumps(summary_stored,  default=str),
                )
            )
            cur.close()
    except Exception:
        pass


_init_db()

# ── Per-package profile cache (PostgreSQL — replaces profile_cache/*.json) ─────
# Per-field TTLs (seconds) — unchanged from the file-based version
_FIELD_TTL = {
    "contrib_intel":     7 * 86400,  # 7 days  — LinkedIn, orgs, 2FA (identity)
    "owner_prof":        7 * 86400,  # 7 days  — org/user profile
    "maint_gh_profiles": 7 * 86400,  # 7 days  — individual maintainer profiles
    "openssf":               86400,  # 1 day   — scorecard refreshed weekly
    "raw_maintainers":       86400,  # 1 day   — registry maintainer list
    "owner_repos":           86400,  # 1 day   — top repos list
    "gh_path":               86400,  # 1 day   — repo path (rarely changes)
    "handle":                86400,  # 1 day
    "repo_info":              3600,  # 1 hour  — stars/forks change often
    "repo_cmts":              3600,  # 1 hour  — commits happen daily
    "last_commit_date":       3600,  # 1 hour
}


def _pkg_cache_key(pkg_name: str, reg_name: str) -> str:
    """Build a stable, filesystem-safe primary key for a package + registry pair."""
    return (f"{pkg_name}__{reg_name}"
            .replace("/", "_").replace("\\", "_").replace(":", "_")
            .replace("@", "_").replace(" ", "_"))


def _load_json_cache(pkg_name: str, reg_name: str) -> dict:
    """Load the profile cache dict for a package from PostgreSQL."""
    key = _pkg_cache_key(pkg_name, reg_name)
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT data FROM profile_cache WHERE pkg_key=%s", (key,))
            r = cur.fetchone()
            cur.close()
        if r:
            # psycopg2 returns JSONB columns already as Python dicts
            return r[0] if isinstance(r[0], dict) else json.loads(r[0])
    except Exception:
        pass
    return {}


def _save_json_cache(pkg_name: str, reg_name: str, cache: dict):
    """Persist the profile cache dict for a package to PostgreSQL."""
    key = _pkg_cache_key(pkg_name, reg_name)
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO profile_cache (pkg_key, data, saved_at)
                   VALUES (%s, %s::jsonb, %s)
                   ON CONFLICT (pkg_key) DO UPDATE
                   SET data = EXCLUDED.data, saved_at = EXCLUDED.saved_at""",
                (key, json.dumps(cache, default=str), time.time())
            )
            cur.close()
    except Exception:
        pass


def _jcache_get(cache: dict, field: str):
    """Return (value, is_fresh). is_fresh=True means within TTL → skip API call."""
    entry = cache.get(field)
    if not isinstance(entry, dict):
        return None, False
    age = time.time() - entry.get("saved_at", 0)
    return entry.get("data"), age < _FIELD_TTL.get(field, 86400)


def _jcache_set(cache: dict, field: str, value):
    cache[field] = {"data": value, "saved_at": time.time()}


def _delete_json_cache(pkg_name: str, reg_name: str):
    """Remove the profile cache entry for a package from PostgreSQL."""
    key = _pkg_cache_key(pkg_name, reg_name)
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM profile_cache WHERE pkg_key=%s", (key,))
            cur.close()
    except Exception:
        pass


# Auto-clear cache when schema changes (old rows carry "Status", new rows carry "Maintainer")
def _migrate_cache():
    """Wipe cache rows from older schema versions."""
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT key, data FROM cache LIMIT 30")
            rows = cur.fetchall()
            for key, raw in rows:
                try:
                    items  = json.loads(raw)
                    sample = items[0] if isinstance(items, list) else items
                    if ("Status" in sample and "Maintainer" not in sample) or \
                       ("Last Updated" not in sample and "Library" in sample):
                        cur.execute("DELETE FROM cache")
                        break
                except Exception:
                    pass
            cur.close()
    except Exception:
        pass


_migrate_cache()

# ══════════════════════════════════════════════════════════════════════════════
# MONITORING PIPELINE  — DB is the engine, UI is read-only display
# ══════════════════════════════════════════════════════════════════════════════

_MONITOR_FIELD_SEVERITY = {
    "cves":                    "critical",
    "maintainer_email_domain": "high",
    "maintainer":              "high",
    "last_updated":            "high",
    "license":                 "medium",
    "deprecated":              "medium",
    "version":                 "info",
}


def _monitor_upsert(library: str, registry: str):
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO monitored_packages (library, registry, enrolled_at, next_check_at)
                   VALUES (%s, %s, NOW(), NOW() + INTERVAL '6 hours')
                   ON CONFLICT (library, registry) DO NOTHING""",
                (library, registry),
            )
            cur.close()
    except Exception:
        pass


def _monitor_update_checked(library: str, registry: str):
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """UPDATE monitored_packages
                   SET last_checked  = NOW(),
                       next_check_at = NOW() + INTERVAL '6 hours'
                   WHERE library = %s AND registry = %s""",
                (library, registry),
            )
            cur.close()
    except Exception:
        pass


def _snapshot_get_latest(library: str, registry: str) -> "dict | None":
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT snapshot FROM package_snapshots
                   WHERE library = %s AND registry = %s
                   ORDER BY snapped_at DESC LIMIT 1""",
                (library, registry),
            )
            row = cur.fetchone()
            cur.close()
        return row[0] if row else None
    except Exception:
        return None


def _snapshot_insert(library: str, registry: str, snapshot: dict):
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO package_snapshots (library, registry, snapped_at, snapshot)
                   VALUES (%s, %s, NOW(), %s::jsonb)""",
                (library, registry, json.dumps(snapshot, default=str)),
            )
            cur.execute(
                """DELETE FROM package_snapshots
                   WHERE library = %s AND registry = %s
                     AND id NOT IN (
                         SELECT id FROM package_snapshots
                         WHERE library = %s AND registry = %s
                         ORDER BY snapped_at DESC LIMIT 10
                     )""",
                (library, registry, library, registry),
            )
            cur.close()
    except Exception:
        pass


_EMPTY_VALS = {"", "—", "N/A", "None", "null", "n/a", "unknown"}

# Corporate email domain groups — changes within a group are not hijack signals
_DOMAIN_ALIASES = [
    {"google.com", "gmail.com", "googlemail.com"},
    {"microsoft.com", "outlook.com", "hotmail.com", "live.com"},
    {"apple.com", "icloud.com", "me.com", "mac.com"},
    {"facebook.com", "meta.com", "fb.com"},
    {"amazon.com", "amazonaws.com"},
]

# Known garbage/test version values that should never be used as a baseline
_GARBAGE_VERSIONS = {"xd", "test", "dummy", "placeholder", "todo", "tbd", "dev", "wip", "na", "n/a"}


def _normalise_for_diff(field: str, val: str) -> str:
    val = val.strip()
    if field == "version":
        val = re.sub(r'\s*\(.*?\)', '', val).strip()
        val = re.sub(r'^v(?=\d)', '', val)
        if val == "0.0.0":
            val = ""
    elif field == "maintainer":
        if '·' in val:
            val = val.split('·', 1)[1].strip()
        val = re.sub(r'\s*\+\d+.*$', '', val).strip()
        val = val.split(',')[0].strip().lower()
    return val


def _is_noise(field: str, old_val: str, new_val: str) -> bool:
    if old_val in _EMPTY_VALS:
        return True
    if new_val in _EMPTY_VALS:
        return True
    if field == "version":
        old_v = re.sub(r'^v', '', old_val.strip().lower())
        if old_v in _GARBAGE_VERSIONS:
            return True
        if re.search(r'\(yanked\)', old_val, re.IGNORECASE):
            return True
    if _normalise_for_diff(field, old_val) == _normalise_for_diff(field, new_val):
        return True
    if field == "maintainer":
        n = new_val.strip()
        if n in ("User", "Org", "User ·", "Org ·"):
            return True
        if n.endswith(("· None", "· —", "· N/A", "· null")):
            return True
    if field == "cves":
        if not re.search(r'CVE-\d{4}-\d+|GHSA-', new_val, re.IGNORECASE):
            return True
    if field == "maintainer_email_domain":
        old_d = old_val.lower().strip()
        new_d = new_val.lower().strip()
        for group in _DOMAIN_ALIASES:
            if old_d in group and new_d in group:
                return True
    if field == "license":
        # Old license is subset of new (more permissive) — not a security event
        old_norm = re.sub(r'[^a-z0-9]', '', old_val.lower())
        new_norm = re.sub(r'[^a-z0-9]', '', new_val.lower())
        if old_norm and old_norm in new_norm:
            return True
    if field == "deprecated":
        # Only alert active → deprecated, not the reverse
        if new_val.lower() != "deprecated":
            return True
    return False


def _diff_and_alert(library: str, registry: str, old_snap: dict, new_snap: dict):
    _old_src = old_snap.get("source", "")
    _new_src = new_snap.get("source", "")
    _source_changed = bool(_old_src and _new_src and _old_src != _new_src)
    _fields = (
        {k: v for k, v in _MONITOR_FIELD_SEVERITY.items() if k == "cves"}
        if _source_changed else _MONITOR_FIELD_SEVERITY
    )
    alerts = []
    for field, severity in _fields.items():
        old_val = re.sub(r'\s+', ' ', str(old_snap.get(field, "") or "").strip())
        new_val = re.sub(r'\s+', ' ', str(new_snap.get(field, "") or "").strip())
        if old_val == new_val:
            continue
        if new_val in _EMPTY_VALS:
            continue
        if _is_noise(field, old_val, new_val):
            continue
        alerts.append((severity, field, old_val, new_val))
    if not alerts:
        return
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            for sev, fld, old_v, new_v in alerts:
                cur.execute(
                    """INSERT INTO package_alerts
                       (library, registry, detected_at, severity, field, old_value, new_value)
                       VALUES (%s, %s, NOW(), %s, %s, %s, %s)
                       ON CONFLICT (library, registry, field,
                                    COALESCE(new_value,''), _pa_utc_date(detected_at))
                       DO NOTHING""",
                    (library, registry, sev, fld, old_v, new_v),
                )
                _notify_telegram(library, registry, sev, fld, old_v, new_v)
            cur.close()
    except Exception:
        pass


def _pipeline_ingest(audit_rows: list):
    for ar in audit_rows:
        library  = ar.get("Library", "")
        registry = ar.get("Registry", "")
        if not library or not registry:
            continue
        row_data = ar.get("_row_data") or ar
        _status_raw = str(row_data.get("Status", "") or "").lower()
        snapshot = {
            "version":                 row_data.get("Version",                    "N/A"),
            "maintainer":              row_data.get("Maintainer",                 "—"),
            "cves":                    row_data.get("CVEs",                       "—"),
            "license":                 row_data.get("License",                    "—"),
            "last_updated":            row_data.get("Last Updated",               "—"),
            "downloads":               row_data.get("Downloads",                  "—"),
            "maintainer_email_domain": row_data.get("_maintainer_email_domain",   "") or "",
            "source":                  row_data.get("Repo",                       ""),
            "deprecated":              "deprecated" if "abandoned" in _status_raw else "active",
        }
        _monitor_upsert(library, registry)
        old_snap = _snapshot_get_latest(library, registry)
        if old_snap:
            if "source" not in old_snap:
                try:
                    with _pg_conn() as _conn:
                        _c = _conn.cursor()
                        _c.execute(
                            """DELETE FROM package_alerts
                               WHERE library = %s AND registry = %s
                                 AND field   <> 'cves'
                                 AND detected_at >= NOW() - INTERVAL '48 hours'""",
                            (library, registry)
                        )
                        _c.close()
                except Exception:
                    pass
                old_snap = None
            if old_snap:
                _diff_and_alert(library, registry, old_snap, snapshot)
        _snapshot_insert(library, registry, snapshot)


def _get_due_packages() -> list:
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT library, registry FROM monitored_packages
                   WHERE next_check_at <= NOW()
                   ORDER BY next_check_at ASC"""
            )
            rows = cur.fetchall()
            cur.close()
        return [(r[0], r[1]) for r in rows]
    except Exception:
        return []


def _alerts_get_all(limit: int = 200) -> list:
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT id, library, registry, detected_at, severity,
                          field, old_value, new_value, is_read
                   FROM package_alerts
                   WHERE
                     field != 'version'
                     AND old_value NOT IN ('', '--', 'N/A', 'None', 'null', 'unknown')
                     AND new_value NOT IN ('', '--', 'N/A', 'None', 'null', 'unknown')
                     AND NOT (field = 'maintainer'
                              AND new_value IN ('User', 'Org', 'User ·', 'Org ·'))
                     AND NOT (field = 'cves'
                              AND new_value !~ '(CVE-[0-9]{4}-[0-9]+|GHSA-)')
                   ORDER BY detected_at DESC
                   LIMIT %s""",
                (limit,),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.close()
        clean = []
        for row in rows:
            if not _is_noise(row.get("field",""), row.get("old_value","") or "", row.get("new_value","") or ""):
                clean.append(row)
        return clean
    except Exception:
        return []


def _alerts_mark_all_read():
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE package_alerts SET is_read = TRUE WHERE is_read = FALSE")
            cur.close()
    except Exception:
        pass


def _monitored_get_all() -> list:
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT m.library, m.registry,
                          m.enrolled_at, m.last_checked, m.next_check_at,
                          s.snapshot, s.snapped_at
                   FROM monitored_packages m
                   LEFT JOIN LATERAL (
                       SELECT snapshot, snapped_at
                       FROM package_snapshots
                       WHERE library = m.library AND registry = m.registry
                       ORDER BY snapped_at DESC LIMIT 1
                   ) s ON TRUE
                   ORDER BY m.library ASC"""
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.close()
        return rows
    except Exception:
        return []


def _auto_enroll_to_yaml(scan_rows: list):
    """Auto-save newly scanned packages to packages.yaml + DB.

    Called after every scan — silently adds new packages to the watchlist.
    Skips packages already listed. Appends to END of file (preserves comments).
    No-op if packages.yaml is missing or pyyaml not installed.
    """
    try:
        import yaml as _yaml
    except ImportError:
        return

    _yaml_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "packages.yaml"
    )
    try:
        with open(_yaml_path, "r", encoding="utf-8") as _f:
            _config = _yaml.safe_load(_f) or {}
    except Exception:
        return

    _existing = _config.get("packages") or []
    _existing_keys = set()
    for _e in _existing:
        _n = str(_e.get("name", "")).strip().lower()
        _r = str(_e.get("registry", "")).strip().lower()
        _gh = re.search(r"github\.com/(.+)", _n)
        if _gh:
            _n = _gh.group(1).rstrip("/")
        _existing_keys.add((_n, _r))

    _new_entries = []
    for _row in scan_rows:
        _lib = str(_row.get("Library", "")).strip()
        _reg = str(_row.get("Registry", "")).strip()
        if not _lib or not _reg:
            continue
        _lib_key = _lib.lower()
        _gh = re.search(r"github\.com/(.+)", _lib_key)
        if _gh:
            _lib_key = _gh.group(1).rstrip("/")
        if (_lib_key, _reg.lower()) in _existing_keys:
            continue
        _new_entries.append((_lib, _reg))
        _existing_keys.add((_lib_key, _reg.lower()))
        _monitor_upsert(_lib, _reg)

    if not _new_entries:
        return
    try:
        with open(_yaml_path, "a", encoding="utf-8") as _f:
            for _lib, _reg in _new_entries:
                _f.write(f"\n  - name: {_lib}\n    registry: {_reg}\n")
    except Exception:
        pass

# ── Utilities ──────────────────────────────────────────────────────────────────
def _exact_match(q, name):
    q = q.lower().strip(); n = name.lower().strip()
    if n == q: return True
    for sep in ("/", ":"):
        if sep in n and n.split(sep)[-1] == q: return True
    return False

def _is_search(q): return " " in q.strip()

def _name_match(query: str, result_name: str, threshold: float = 0.55) -> bool:
    """Return True if result_name is a plausible match for the user's query.

    Security-researcher rules — NO fuzzy matching, NO arbitrary substring
    matching. This was the source of false positives like:
      query "react"  → matched "Win11React"   (substring at end — REJECT)
      query "axios"  → matched "Microsoft.Axios.Foo"  (substring in middle — REJECT)

    Accept ONLY when:
      1. Exact (case/punctuation insensitive) match
      2. Path-style suffix match: query == name.split('/:.')[ -1 ]
      3. Name starts with query (e.g. "react" → "react-dom", "reactjs")
      4. First word of name (CamelCase-aware) starts with query
         e.g. "node" → "Node.js"      ✓ first token "Node" starts with "node"
              "react" → "Win11React"  ✗ first token "Win11" doesn't
    """
    q = query.lower().strip()
    n = result_name.lower().strip()
    if not q or not n:
        return False

    # Rule 1 — exact (case-insensitive)
    if q == n:
        return True

    # Rule 2 — path-style suffix: "Mozilla.Firefox" matches "firefox"
    for sep in ("/", ":", "."):
        if sep in n and n.split(sep)[-1] == q:
            return True
        if sep in q and q.split(sep)[-1] == n:
            return True

    # Rule 3 — strip non-alphanumeric, compare again
    qa = re.sub(r"[^a-z0-9]", "", q)
    na = re.sub(r"[^a-z0-9]", "", n)
    if not qa or not na:
        return False
    if qa == na:
        return True

    # Rule 4 — prefix match only (NEVER arbitrary substring/suffix)
    # Both sides must be ≥ 4 chars to avoid noise from short tokens like "ng".
    if len(qa) >= 4 and len(na) >= 4:
        if na.startswith(qa) or qa.startswith(na):
            return True

    # Rule 5 — first-token (CamelCase-aware) starts with query
    # "Node.js"   → first token "Node"   → starts with "node"  ✓
    # "Win11React"→ first token "Win11"  → starts with "win11" ✗ (good)
    # "react-dom" → first token "react"  → starts with "react" ✓
    first_token = re.split(r'[\s\-_.:/]|(?<=[a-z0-9])(?=[A-Z])',
                           result_name.strip())[0]
    ft = re.sub(r"[^a-z0-9]", "", first_token.lower())
    if ft and len(qa) >= 4 and (ft == qa or ft.startswith(qa) or qa.startswith(ft)):
        return True

    return False

def _trunc(s, n=72):
    if not s or s == "N/A": return "—"
    s = s.strip()
    return s[:n].rstrip() + ("…" if len(s) > n else "")

def _clean_for_json_export(df: "pd.DataFrame") -> str:
    """Return a clean, human-readable JSON string from a results DataFrame.

    Fixes two problems that appear in the raw pandas .to_json() output:
      1. Unicode escapes (·, 🚨 …) — caused by force_ascii=True default.
         Fixed by converting to Python dicts first then json.dumps(ensure_ascii=False).
      2. Emoji prefixes in display columns (Status, Risk, License Risk, etc.).
         Fixed by stripping any leading non-ASCII run + optional space from string values
         in the affected columns before serialising.
    """
    # Columns that carry emoji prefixes in their display values
    _EMOJI_COLS = {
        "Status", "Risk", "License Risk",
        "Single Maintainer", "Country Tier",
    }
    _strip_emoji = lambda v: re.sub(r'^[^\x00-\x7F\s]+\s*', '', str(v)).strip() if isinstance(v, str) else v

    clean = df.copy()
    for col in _EMOJI_COLS:
        if col in clean.columns:
            clean[col] = clean[col].apply(_strip_emoji)

    records = json.loads(clean.to_json(orient="records", force_ascii=False))
    return json.dumps(records, indent=2, ensure_ascii=False)

# ── Maintainer Country Intelligence ────────────────────────────────────────────
# Maps free-text GitHub location strings → standardised country names.
# Covers cities, common abbreviations, and alternate spellings.
_COUNTRY_NORM: dict[str, str] = {
    # United Kingdom
    "uk":"United Kingdom","u.k.":"United Kingdom","gb":"United Kingdom",
    "united kingdom":"United Kingdom","great britain":"United Kingdom",
    "britain":"United Kingdom","england":"United Kingdom","scotland":"United Kingdom",
    "wales":"United Kingdom","northern ireland":"United Kingdom",
    "london":"United Kingdom","manchester":"United Kingdom","birmingham":"United Kingdom",
    "leeds":"United Kingdom","liverpool":"United Kingdom","bristol":"United Kingdom",
    "edinburgh":"United Kingdom","glasgow":"United Kingdom","oxford":"United Kingdom",
    "cambridge":"United Kingdom","sheffield":"United Kingdom","nottingham":"United Kingdom",
    # United States — country aliases, then states (full names + 2-letter codes
    # SCOPED with "us" prefix to disambiguate from country codes like "ca"=Canada),
    # then major cities.
    "us":"United States","usa":"United States","u.s.":"United States","u.s.a.":"United States",
    "united states":"United States","united states of america":"United States",
    "america":"United States",
    # US states — full names (safe to substring-match)
    "california":"United States","texas":"United States","florida":"United States",
    "new york state":"United States","washington state":"United States",
    "massachusetts":"United States","colorado":"United States","oregon":"United States",
    "illinois":"United States","pennsylvania":"United States","georgia":"United States",
    "virginia":"United States","north carolina":"United States","ohio":"United States",
    "michigan":"United States","minnesota":"United States","arizona":"United States",
    "tennessee":"United States","indiana":"United States","missouri":"United States",
    "wisconsin":"United States","maryland":"United States","new jersey":"United States",
    "connecticut":"United States","utah":"United States","nevada":"United States",
    "kentucky":"United States","louisiana":"United States","oklahoma":"United States",
    "arkansas":"United States","mississippi":"United States","kansas":"United States",
    "iowa":"United States","nebraska":"United States","alabama":"United States",
    "south carolina":"United States","new mexico":"United States","west virginia":"United States",
    "hawaii":"United States","alaska":"United States","rhode island":"United States",
    "delaware":"United States","montana":"United States","wyoming":"United States",
    "north dakota":"United States","south dakota":"United States","vermont":"United States",
    "new hampshire":"United States","maine":"United States","idaho":"United States",
    # Major US cities
    "new york":"United States","san francisco":"United States",
    "san francisco bay area":"United States","silicon valley":"United States",
    "seattle":"United States","los angeles":"United States","chicago":"United States",
    "menlo park":"United States","palo alto":"United States","cupertino":"United States",
    "mountain view":"United States","sunnyvale":"United States","san jose":"United States",
    "redmond":"United States","irvine":"United States","santa clara":"United States",
    "boston":"United States","austin":"United States","portland":"United States",
    "denver":"United States","atlanta":"United States","dallas":"United States",
    "washington":"United States","dc":"United States","washington dc":"United States",
    "san diego":"United States","miami":"United States","phoenix":"United States",
    "minneapolis":"United States","pittsburgh":"United States","raleigh":"United States",
    "remote, us":"United States","remote, usa":"United States",
    # Germany
    "germany":"Germany","deutschland":"Germany","berlin":"Germany","munich":"Germany",
    "münchen":"Germany","hamburg":"Germany","frankfurt":"Germany","cologne":"Germany",
    "köln":"Germany","düsseldorf":"Germany","stuttgart":"Germany","leipzig":"Germany",
    # France
    "france":"France","paris":"France","lyon":"France","marseille":"France","toulouse":"France",
    # India
    "india":"India","bangalore":"India","bengaluru":"India","mumbai":"India",
    "delhi":"India","new delhi":"India","hyderabad":"India","pune":"India",
    "chennai":"India","kolkata":"India","ahmedabad":"India","noida":"India","gurugram":"India",
    # China
    "china":"China","prc":"China","beijing":"China","shanghai":"China",
    "shenzhen":"China","guangzhou":"China","hangzhou":"China","chengdu":"China",
    # Russia
    "russia":"Russia","russian federation":"Russia","moscow":"Russia",
    "saint petersburg":"Russia","st. petersburg":"Russia","novosibirsk":"Russia",
    # Canada
    "canada":"Canada","toronto":"Canada","vancouver":"Canada","montreal":"Canada",
    "ottawa":"Canada","calgary":"Canada","edmonton":"Canada","waterloo":"Canada",
    # Australia
    "australia":"Australia","sydney":"Australia","melbourne":"Australia",
    "brisbane":"Australia","perth":"Australia","adelaide":"Australia","canberra":"Australia",
    # Netherlands
    "netherlands":"Netherlands","the netherlands":"Netherlands","holland":"Netherlands",
    "amsterdam":"Netherlands","rotterdam":"Netherlands","utrecht":"Netherlands",
    # Japan
    "japan":"Japan","tokyo":"Japan","osaka":"Japan","kyoto":"Japan","fukuoka":"Japan",
    # South Korea
    "south korea":"South Korea","korea":"South Korea","seoul":"South Korea","busan":"South Korea",
    # Brazil
    "brazil":"Brazil","são paulo":"Brazil","sao paulo":"Brazil","rio de janeiro":"Brazil",
    "brasília":"Brazil","belo horizonte":"Brazil","curitiba":"Brazil",
    # Sweden
    "sweden":"Sweden","stockholm":"Sweden","gothenburg":"Sweden","malmö":"Sweden",
    # Norway
    "norway":"Norway","oslo":"Norway","bergen":"Norway","trondheim":"Norway",
    # Finland
    "finland":"Finland","helsinki":"Finland","espoo":"Finland","tampere":"Finland",
    # Denmark
    "denmark":"Denmark","copenhagen":"Denmark","aarhus":"Denmark",
    # Switzerland
    "switzerland":"Switzerland","zurich":"Switzerland","zürich":"Switzerland",
    "geneva":"Switzerland","bern":"Switzerland","basel":"Switzerland",
    # Spain
    "spain":"Spain","madrid":"Spain","barcelona":"Spain","valencia":"Spain","seville":"Spain",
    # Italy
    "italy":"Italy","rome":"Italy","milan":"Italy","milano":"Italy",
    "turin":"Italy","naples":"Italy","florence":"Italy","bologna":"Italy",
    # Poland
    "poland":"Poland","warsaw":"Poland","kraków":"Poland","wrocław":"Poland","gdańsk":"Poland",
    # Ukraine
    "ukraine":"Ukraine","kyiv":"Ukraine","kharkiv":"Ukraine","lviv":"Ukraine","odesa":"Ukraine",
    # Israel
    "israel":"Israel","tel aviv":"Israel","jerusalem":"Israel","haifa":"Israel",
    # Singapore
    "singapore":"Singapore",
    # Taiwan
    "taiwan":"Taiwan","taipei":"Taiwan",
    # Portugal
    "portugal":"Portugal","lisbon":"Portugal","porto":"Portugal",
    # Czech Republic
    "czech republic":"Czech Republic","czechia":"Czech Republic","prague":"Czech Republic",
    "brno":"Czech Republic",
    # Romania
    "romania":"Romania","bucharest":"Romania","cluj":"Romania","timișoara":"Romania",
    # Belgium
    "belgium":"Belgium","brussels":"Belgium","ghent":"Belgium","antwerp":"Belgium",
    # Austria
    "austria":"Austria","vienna":"Austria","wien":"Austria","graz":"Austria",
    # New Zealand
    "new zealand":"New Zealand","auckland":"New Zealand","wellington":"New Zealand",
    # Argentina
    "argentina":"Argentina","buenos aires":"Argentina","córdoba":"Argentina",
    # Mexico
    "mexico":"Mexico","mexico city":"Mexico","guadalajara":"Mexico","monterrey":"Mexico",
    # South Africa
    "south africa":"South Africa","cape town":"South Africa","johannesburg":"South Africa",
    "durban":"South Africa",
    # Pakistan
    "pakistan":"Pakistan","karachi":"Pakistan","lahore":"Pakistan","islamabad":"Pakistan",
    # Iran
    "iran":"Iran","tehran":"Iran",
    # Turkey
    "turkey":"Turkey","türkiye":"Turkey","istanbul":"Turkey","ankara":"Turkey",
    # Egypt
    "egypt":"Egypt","cairo":"Egypt","alexandria":"Egypt",
    # Nigeria
    "nigeria":"Nigeria","lagos":"Nigeria","abuja":"Nigeria",
    # Indonesia
    "indonesia":"Indonesia","jakarta":"Indonesia","bandung":"Indonesia","surabaya":"Indonesia",
    # Vietnam
    "vietnam":"Vietnam","ho chi minh":"Vietnam","hanoi":"Vietnam",
    # Thailand
    "thailand":"Thailand","bangkok":"Thailand",
    # Malaysia
    "malaysia":"Malaysia","kuala lumpur":"Malaysia",
    # Philippines
    "philippines":"Philippines","manila":"Philippines","cebu":"Philippines",
    # Bangladesh
    "bangladesh":"Bangladesh","dhaka":"Bangladesh",
    # Hungary
    "hungary":"Hungary","budapest":"Hungary",
    # Greece
    "greece":"Greece","athens":"Greece","thessaloniki":"Greece",
    # Slovakia
    "slovakia":"Slovakia","bratislava":"Slovakia",
    # Croatia
    "croatia":"Croatia","zagreb":"Croatia",
    # Serbia
    "serbia":"Serbia","belgrade":"Serbia",
    # Bulgaria
    "bulgaria":"Bulgaria","sofia":"Bulgaria",
    # Lithuania
    "lithuania":"Lithuania","vilnius":"Lithuania",
    # Latvia
    "latvia":"Latvia","riga":"Latvia",
    # Estonia
    "estonia":"Estonia","tallinn":"Estonia",
    # Colombia
    "colombia":"Colombia","bogotá":"Colombia","medellin":"Colombia",
    # Chile
    "chile":"Chile","santiago":"Chile",
    # Peru
    "peru":"Peru","lima":"Peru",
    # Morocco
    "morocco":"Morocco","casablanca":"Morocco","rabat":"Morocco",
    # Kenya
    "kenya":"Kenya","nairobi":"Kenya",
    # Ghana
    "ghana":"Ghana","accra":"Ghana",
    # Ethiopia
    "ethiopia":"Ethiopia","addis ababa":"Ethiopia",
    # Saudi Arabia
    "saudi arabia":"Saudi Arabia","riyadh":"Saudi Arabia","jeddah":"Saudi Arabia",
    # UAE
    "uae":"United Arab Emirates","united arab emirates":"United Arab Emirates",
    "dubai":"United Arab Emirates","abu dhabi":"United Arab Emirates",
    # Hong Kong
    "hong kong":"Hong Kong","hk":"Hong Kong",
    # Cyprus
    "cyprus":"Cyprus","nicosia":"Cyprus","limassol":"Cyprus","larnaca":"Cyprus",
    "paphos":"Cyprus","famagusta":"Cyprus",
    # Malta
    "malta":"Malta","valletta":"Malta",
    # Ireland
    "ireland":"Ireland","dublin":"Ireland",
    # Iceland
    "iceland":"Iceland","reykjavik":"Iceland",
    # Luxembourg
    "luxembourg":"Luxembourg",
    # Belarus
    "belarus":"Belarus","minsk":"Belarus",
    # Kazakhstan
    "kazakhstan":"Kazakhstan","almaty":"Kazakhstan",
    # Remote / global
    "remote":"🌐 Remote / Global","worldwide":"🌐 Remote / Global",
    "global":"🌐 Remote / Global","earth":"🌐 Remote / Global",
    "internet":"🌐 Remote / Global","everywhere":"🌐 Remote / Global",
    # ── ISO 3166-1 alpha-2 codes (2-letter) ──────────────────────────────────
    # These appear on GitHub profiles as "RU", "DE", "FR" etc.
    # Must map to full names so short codes are NEVER displayed in the UI.
    "ru":"Russia","cn":"China","de":"Germany","fr":"France","in":"India",
    "jp":"Japan","kr":"South Korea","br":"Brazil","au":"Australia","ca":"Canada",
    "nl":"Netherlands","se":"Sweden","no":"Norway","fi":"Finland","dk":"Denmark",
    "ch":"Switzerland","es":"Spain","it":"Italy","pl":"Poland","ua":"Ukraine",
    "il":"Israel","pt":"Portugal","cz":"Czech Republic","ro":"Romania",
    "be":"Belgium","at":"Austria","nz":"New Zealand","ar":"Argentina",
    "mx":"Mexico","za":"South Africa","pk":"Pakistan","ir":"Iran",
    "tr":"Turkey","eg":"Egypt","ng":"Nigeria","id":"Indonesia","vn":"Vietnam",
    "th":"Thailand","my":"Malaysia","ph":"Philippines","bd":"Bangladesh",
    "hu":"Hungary","gr":"Greece","ie":"Ireland","sk":"Slovakia","hr":"Croatia",
    "rs":"Serbia","bg":"Bulgaria","lt":"Lithuania","lv":"Latvia","ee":"Estonia",
    "co":"Colombia","cl":"Chile","pe":"Peru","ma":"Morocco","ke":"Kenya",
    "gh":"Ghana","et":"Ethiopia","sa":"Saudi Arabia","ae":"United Arab Emirates",
    "tw":"Taiwan","kz":"Kazakhstan","by":"Belarus","is":"Iceland","lu":"Luxembourg",
    "lk":"Sri Lanka","np":"Nepal","mm":"Myanmar","kh":"Cambodia","uz":"Uzbekistan",
    "ge":"Georgia","az":"Azerbaijan","am":"Armenia","md":"Moldova","al":"Albania",
    "mk":"North Macedonia","ba":"Bosnia and Herzegovina","me":"Montenegro",
    "si":"Slovenia","cy":"Cyprus","mt":"Malta","li":"Liechtenstein","mc":"Monaco",
    "sm":"San Marino","va":"Vatican City","ad":"Andorra","tn":"Tunisia",
    "dz":"Algeria","ly":"Libya","sd":"Sudan","ao":"Angola","tz":"Tanzania",
    "ug":"Uganda","zm":"Zambia","zw":"Zimbabwe","mz":"Mozambique","bw":"Botswana",
    "ci":"Ivory Coast","cm":"Cameroon","sn":"Senegal","ml":"Mali","bf":"Burkina Faso",
    "ve":"Venezuela","ec":"Ecuador","bo":"Bolivia","py":"Paraguay","uy":"Uruguay",
    "gt":"Guatemala","cr":"Costa Rica","pa":"Panama","cu":"Cuba","do":"Dominican Republic",
    "jm":"Jamaica","tt":"Trinidad and Tobago","hn":"Honduras","sv":"El Salvador",
    "ni":"Nicaragua","pr":"Puerto Rico","jo":"Jordan","lb":"Lebanon","sy":"Syria",
    "iq":"Iraq","kw":"Kuwait","qa":"Qatar","bh":"Bahrain","om":"Oman","ye":"Yemen",
    "af":"Afghanistan","uz":"Uzbekistan","tm":"Turkmenistan","tj":"Tajikistan",
    "mn":"Mongolia","kp":"North Korea","bt":"Bhutan","mv":"Maldives",
    "fj":"Fiji","pg":"Papua New Guinea","nz":"New Zealand",
}

def _normalize_country(location: str) -> str:
    """Map a free-text GitHub location → standardised country name."""
    if not location or not location.strip():
        return "Unknown"
    loc = location.lower().strip()

    # Pre-sort aliases once: longest first so more specific matches win
    _sorted = sorted(_COUNTRY_NORM.items(), key=lambda x: -len(x[0]))
    # Short aliases (≤ 3 chars: "ru", "in", "de", "fr", "it" …) are ONLY
    # safe as exact tokens — never as substrings.
    # "Bengaluru" contains "ru" → must NOT → Russia.
    # "Trivandrum" contains "ru" → must NOT → Russia.
    # "Indiana"   contains "in" → must NOT → India.
    _short = {a for a in _COUNTRY_NORM if len(a) <= 3}

    # 1. Direct full-string exact match
    if loc in _COUNTRY_NORM:
        return _COUNTRY_NORM[loc]

    # 2. Comma-split — try each token as an exact match (handles "Bengaluru, India")
    parts = [p.strip() for p in loc.split(",")]
    for part in reversed(parts):          # last token is usually the country
        if part in _COUNTRY_NORM:
            return _COUNTRY_NORM[part]

    # 3. Substring scan — LONG aliases only (> 3 chars)
    #    "london" in "london, uk" ✓   "ru" in "bengaluru" ✗ (blocked)
    for part in parts:
        for alias, country in _sorted:
            if alias in _short:
                continue                  # skip "ru", "in", "de" etc. here
            if alias in part:
                return country

    # 4. Full-string substring scan — again long aliases only
    for alias, country in _sorted:
        if alias in _short:
            continue
        if alias in loc:
            return country

    # 5. No match found — always return "Unknown".
    #    Never display raw location strings (city names, abbreviations, slang).
    #    Only values explicitly listed in _COUNTRY_NORM are shown as country names.
    return "Unknown"

def _username_variants(name: str) -> list:
    """
    Generate plausible GitHub username variants for a freeform maintainer name.
    Tried in order of likelihood:
      1. Exact (e.g. "google")
      2. Lowercase (e.g. "Microsoft" → "microsoft")
      3. No-spaces (e.g. "Mark Finger" → "MarkFinger")
      4. Hyphenated (e.g. "Mark Finger" → "mark-finger")
      5. First word only (already the default if no spaces present)
    Duplicates are removed while preserving order.
    """
    if not name:
        return []
    seen, out = set(), []
    candidates = [
        name,
        name.lower(),
        re.sub(r"\s+", "", name),               # "Mark Finger" → "MarkFinger"
        re.sub(r"\s+", "-", name).lower(),       # "Mark Finger" → "mark-finger"
        re.sub(r"\s+", "_", name).lower(),       # "Mark Finger" → "mark_finger"
        name.split()[0] if " " in name else "",  # First word fallback
    ]
    for c in candidates:
        c = re.sub(r"[^a-zA-Z0-9_\-]", "", c.strip())
        if c and c not in seen and 1 <= len(c) <= 39:  # GitHub username limit
            seen.add(c)
            out.append(c)
    return out

# Curated mapping for well-known orgs whose GitHub profile location is
# unreliable, missing, or generic ("Worldwide", "Internet"). Many large
# tech companies leave the field blank because they have multiple offices.
# Without this map, React's "Org · facebook" lookup would fail to resolve
# even though Meta is clearly headquartered in California, USA.
_KNOWN_ORG_COUNTRY: dict[str, str] = {
    # ─── USA — Big Tech, frameworks, runtimes, popular individual maintainers ───
    "facebook":"United States","meta":"United States","meta-llama":"United States",
    "google":"United States","googlecloudplatform":"United States","googleapis":"United States",
    "googlechrome":"United States","googlechromelabs":"United States",
    "microsoft":"United States","azure":"United States","azure-sdk":"United States",
    "dotnet":"United States","aspnet":"United States",
    "apple":"United States","amazon":"United States","aws":"United States","awslabs":"United States",
    "netflix":"United States","airbnb":"United States","uber":"United States","lyft":"United States",
    "twitter":"United States","x":"United States","linkedin":"United States","pinterest":"United States",
    "github":"United States","gitlab":"United States","atlassian":"United States",
    "mozilla":"United States","openai":"United States","anthropic":"United States",
    "reactjs":"United States","vercel":"United States","nextjs":"United States",
    "nodejs":"United States","npm":"United States","ibm":"United States",
    "oracle":"United States","salesforce":"United States","slack":"United States",
    "dropbox":"United States","stripe":"United States","redhat":"United States",
    "vmware":"United States","tensorflow":"United States","pytorch":"United States",
    "huggingface":"United States","datadoghq":"United States","palantir":"United States",
    "elastic":"United States","grafana":"United States","hashicorp":"United States",
    "docker":"United States","kubernetes":"United States","cncf":"United States",
    "apache":"United States","apachecn":"United States","django":"United States",
    "pypa":"United States","python":"United States",
    "pallets":"United States","jupyter":"United States","jupyterlab":"United States",
    "rails":"United States","rubygems":"United States","ruby":"United States",
    "expressjs":"United States","webpack":"United States","babel":"United States",
    "gatsbyjs":"United States","prisma":"United States",
    "supabase":"United States","mongodb":"United States","postgres":"United States",
    "postgresql":"United States","redis":"United States","memcached":"United States",
    "sindresorhus":"United States","substack":"United States",
    "tj":"United States","gaearon":"United States","sebmarkbage":"United States",
    "addyosmani":"United States","feross":"United States","kentcdodds":"United States",
    "psf":"United States","matplotlib":"United States","numpy":"United States",
    "scipy":"United States","scikit-learn":"United States","pandas-dev":"United States",
    "pytest-dev":"United States","sphinx-doc":"United States","tox-dev":"United States",
    "actions":"United States","github-marketplace":"United States",
    "boto":"United States","ansible":"United States","mitchellh":"United States",
    "spf13":"United States","golang":"United States","goreleaser":"United States",
    "kubernetes-sigs":"United States","prometheus":"United States","grafana-labs":"United States",
    "argoproj":"United States","istio":"United States","helm":"United States",
    "fluxcd":"United States","cilium":"United States","traefik":"United States",
    "envoyproxy":"United States","stedolan":"United States","jqlang":"United States",
    "google-research":"United States","google-deepmind":"United States",
    "tldr-pages":"United States","ohmyzsh":"United States","robbyrussell":"United States",
    "homebrew":"United States","brew":"United States","laradock":"United States",
    "twbs":"United States","tailwindlabs":"United States","tailwindcss":"United States",
    "shadcn":"United States","shadcn-ui":"United States",
    "nestjs":"United States","kamilmysliwiec":"United States",
    "remix-run":"United States","kentcdodds":"United States","jaredpalmer":"United States",
    "formidablelabs":"United States","reduxjs":"United States","reactstrap":"United States",
    "storybookjs":"United States","cypress-io":"United States","jest-community":"United States",
    "facebookresearch":"United States","facebookincubator":"United States",
    # ─── UK ───
    "canonical":"United Kingdom","arm":"United Kingdom","deepmind":"United Kingdom",
    "preactjs":"United Kingdom","developit":"United Kingdom",
    "ubuntu":"United Kingdom","raspberrypi":"United Kingdom",
    # ─── France ───
    "ocaml":"France","ocaml-community":"France","mirage":"France",
    "ovh":"France","scaleway":"France","gitlabhq":"France","dailymotion":"France",
    # ─── Germany ───
    "sap":"Germany","saphanaone":"Germany","contao":"Germany",
    "matomo-org":"Germany","piwik":"Germany","typo3":"Germany",
    # ─── Czech Republic ───
    "jetbrains":"Czech Republic","kotlin":"Czech Republic","jetbrains-research":"Czech Republic",
    # ─── Sweden ───
    "spotify":"Sweden","klarna":"Sweden","mojang":"Sweden","minecraft":"Sweden",
    "minecrafter":"Sweden",
    # ─── Norway ───
    "opera":"Norway","operasoftware":"Norway",
    # ─── Netherlands ───
    "tomtom":"Netherlands","booking":"Netherlands","elastic":"Netherlands",
    "adyen":"Netherlands","mollie":"Netherlands",
    # ─── Russia / former USSR ───
    "nginx":"Russia","yandex":"Russia","kaspersky":"Russia","mailru":"Russia",
    "tarantool":"Russia","clickhouse":"Russia",
    # ─── China ───
    "alibaba":"China","alibabacloud":"China","tencent":"China","baidu":"China",
    "bytedance":"China","huawei":"China","huaweicloud":"China","didi":"China",
    "antdesign":"China","ant-design":"China","element-plus":"China","vuejs":"China",
    "vuetifyjs":"China","quasarframework":"China","element":"China",
    # ─── India ───
    "redhuntlabs":"India","tcs":"India","infosys":"India","wipro":"India",
    "freshworks":"India","zoho":"India","flipkart":"India","ola":"India",
    "myntra":"India","paytm":"India","razorpay":"India","swiggy":"India",
    # ─── Japan ───
    "lineage":"Japan","mercari":"Japan","sony":"Japan","sonyplaystation":"Japan",
    "rakuten":"Japan","rubykaigi":"Japan","cookpad":"Japan","line":"Japan",
    # ─── South Korea ───
    "kakao":"South Korea","navercorp":"South Korea","samsung":"South Korea",
    "lge":"South Korea",
    # ─── Australia ───
    "atlassian":"Australia","canva":"Australia","camjackson":"Australia",
    "envato":"Australia","abc":"Australia",
    # ─── Canada ───
    "shopify":"Canada","slack":"Canada","hootsuite":"Canada","blackberry":"Canada",
    # ─── Switzerland ───
    "google-deepmind":"Switzerland","cern":"Switzerland","openzeppelin":"Switzerland",
    # ─── Finland ───
    "nokia":"Finland","supercell":"Finland","linus":"Finland","linuxfoundation":"Finland",
    # ─── Spain ───
    "telefonica":"Spain","glovo":"Spain",
    # ─── Italy ───
    "ferrari":"Italy","luigi":"Italy",
    # ─── ADDITIONAL VERIFIED ENTRIES (from real-world scan data) ────────────
    # USA — popular JS/CSS libraries and individual maintainers
    "twbs":"United States",                    # Bootstrap
    "jquery":"United States",                  # jQuery Foundation
    "jqueryfoundation":"United States",
    "jashkenas":"United States",               # Jeremy Ashkenas (Backbone, Underscore)
    "backbone":"United States","underscore":"United States",
    "modernizr":"United States",               # Modernizr team
    "fullcalendar":"United States",            # Adam Shaw, FullCalendar Inc.
    "select2":"United States",                 # Kevin Brown
    "kevin-brown":"United States",
    "kenwheeler":"United States",              # Slick carousel
    "zenorocha":"United States",               # Clipboard.js
    "mrdoob":"Spain",                          # Three.js — Ricardo Cabello
    "three":"Spain","threejs":"Spain",
    "greensock":"United States",               # GSAP
    "lit":"United States","lit-element":"United States","lit-html":"United States",
    "polymer":"United States",
    "tj":"United States","tjholowaychuk":"United States",  # TJ Holowaychuk
    "expressjs":"United States","koajs":"United States",
    "feross":"United States","webtorrent":"United States",
    "ant-design":"China","alipay":"China","alipay-com":"China",
    "fancyapps":"Lithuania",                   # Fancybox — Janis Skarnelis
    "ckeditor":"Poland","ckeditor4":"Poland","ckeditor5":"Poland",
    "tinymce":"Sweden","ephox":"Sweden",
    "froala":"Romania","froalalabs":"Romania",
    "froala-labs":"Romania",
    "splidejs":"Japan",                        # Splide — Naotoshi Fujita
    "naotoshifujita":"Japan",
    "splide":"Japan",
    "nolimits4web":"Belarus",                  # Swiper — Vladimir Kharlampidi
    "swiperjs":"Belarus","framework7io":"Belarus",
    "aFarkas":"Germany","afarkas":"Germany",   # Lazysizes — Alexander Farkas
    "hammerjs":"Netherlands","eightmedia":"Netherlands",  # Hammer.js — Jorik Tangelder
    "jorik":"Netherlands",
    "marijnh":"Netherlands","codemirror":"Netherlands",   # CodeMirror — Marijn Haverbeke
    "prosemirror":"Netherlands",
    "emotion-js":"United States","threepointone":"United States",  # Emotion CSS-in-JS
    "mxstbr":"Germany","styled-components":"United States",  # Max Stoiber — but team is global
    "chartjs":"Canada",                        # Chart.js — Will Bird et al.
    "willbird":"Canada",
    "datatables":"United Kingdom",             # Allan Jardine
    "allanjardine":"United Kingdom",
    "socketio":"United States",                # Socket.IO — Guillermo Rauch
    "rauchg":"United States","vercel":"United States",
    "automerge":"United Kingdom",
    "dropzone":"Germany",                      # Dropzone — Matias Meno (Berlin)
    "matiasmeno":"Germany",
    "lazysizes":"Germany",
    "components":"United States",              # GitHub "components" maintenance org
    "webjars":"United States",                 # WebJars — Sonatype
    "sonatype":"United States",
    "spring-projects":"United States",
    "fasterxml":"United States",
    "jboss":"United States","jbossorg":"United States",
    "eclipse":"Canada","eclipse-platform":"Canada",
    # Ukraine
    "redhuntlabs":"India","macpaw":"Ukraine","macpaw-research":"Ukraine",
    "galetahub":"Ukraine",
    # NOTE: zloirock (Denis Pushkarev, core-js) — removed override.
    # His current GitHub location is "Cyprus, Larnaca" so the API + the
    # _COUNTRY_NORM "cyprus" entry resolves it correctly to Cyprus.
    # The override would have incorrectly forced "Russia" (his nationality,
    # not current location).
    "denysdovhan":"Ukraine","sindresorhus":"Norway","sebmck":"United States",
    "sergi":"Spain",
    # India
    "bdthemes":"Bangladesh",                   # BdThemes (Element Pack)
    "bdwm":"Bangladesh",
    "elementor":"Israel","prosperty":"Israel",
    "wpastra":"India","brainstormforce":"India",
    "themehunk":"India","themeisle":"Romania",
    # Sweden
    "lottiefiles":"Sweden",
    # Bangladesh
    "wpdeveloper":"Bangladesh",
    # Rancher / SUSE
    "rancher":"Germany","suse":"Germany","rancherlabs":"Germany",
    # Iconography
    "lucide-icons":"United States","feathericons":"United States",
    "fontawesome":"United States","Fonticons":"United States",
    # Design system
    "MahApps":"Germany","mahapps":"Germany",
    "MaterialDesignInXAML":"Ireland",          # Material Design Toolkit
    "materialdesigninxaml":"Ireland",
    # Markdown / parsers
    "markedjs":"United Kingdom","chjj":"United States",
    # Closure
    "google-closure-library":"United States",
    # AOS — Animate On Scroll
    "michalsnik":"Poland",                     # Michał Sajnóg
    # popper
    "atomiks":"United Kingdom","popperjs":"United Kingdom",
    "floating-ui":"United Kingdom",
    # axios — jasonsaayman (South Africa) is current maintainer, resolved via live GitHub API
    "jasonsaayman":"South Africa",
    # Bootstrap-related
    "mdo":"United States","fat":"United States",  # Mark Otto, Jacob Thornton
    # Animation
    "daneden":"United Kingdom","danedenco":"United Kingdom",  # Daniel Eden (animate.css)
    "animate-css":"United Kingdom",
    # JS frameworks
    "preactjs":"United Kingdom","developit":"United Kingdom",
    "alpinejs":"South Africa","calebporzio":"United States",
    "svelte":"United Kingdom","sveltejs":"United Kingdom","rich-harris":"United Kingdom",
    "solidjs":"Canada","ryansolid":"Canada",
    "vuejs":"China","yyx990803":"China","evanyou":"China",
    # Chinese tech orgs & maintainers
    "elemefe":"China","ElemeFE":"China",             # Element UI — Ele.me (Alibaba)
    "element-plus":"China",                          # Element Plus — Vue 3 port
    "ant-design":"China","ant-design-vue":"China",   # Ant Design — Alibaba
    "alibaba":"China","alipay":"China","aliyun":"China",
    "tencent":"China","arco-design":"China",         # Arco Design — ByteDance
    "bytedance":"China","modern-js":"China",
    "youzan":"China","vant-ui":"China",              # Vant — Youzan
    "angular":"United States","angularjs":"United States",
    # CSS frameworks
    "bulma":"United Kingdom","jgthms":"United Kingdom",
    "tailwindlabs":"United States","tailwindcss":"United States","adamwathan":"United States",
    # Editors
    "slab":"United States",                    # Quill (after acquisition by Slab)
    "quilljs":"United States","jhchen":"United States",
    # WP plugins maintainers
    "ramoonus":"Netherlands",                  # WP plugins author
    # zepto
    "madrobby":"United States",                # Thomas Fuchs (now in USA)
    # Closure Library
    "closure-library":"United States",
    # protobuf
    "protobuf":"United States","protocolbuffers":"United States",
    # Twitter Bootstrap historical
    "twitter":"United States",
    # Material UI
    "mui":"United States","mui-org":"United States","material-ui":"United States",
    "callemall":"United States",
    # WordPress maintainers
    "automattic":"United States","matt":"United States",
    # Hugging Face
    "huggingface":"United States","facebookresearch":"United States",
    # Composables
    "composablehorizons":"United Kingdom",
    "io-getquill":"United States","getquill":"United States",
    # Community orgs — no single country, contributors worldwide
    # Explicitly marking these "Unknown" blocks the repo-search fallback from
    # assigning a false country via an unrelated popular repo.
    "definitelytyped":"Unknown",        # TypeScript types — global community
    "types":"Unknown",                  # @types/* packages — global community
    "webjars":"Unknown",                # WebJars — Maven wrappers, no country
    "jsr":"Unknown",                    # JSR spec orgs
    "tc39":"Unknown",                   # ECMAScript committee — global
}

@st.cache_data(ttl=7200, show_spinner=False)
def _fetch_github_country(username: str, token: str = "",
                          skip_hardcode: bool = False) -> str:
    """
    Return the normalised country for a GitHub username.

    Tries multiple username variants because registry maintainer fields don't
    always exactly match GitHub usernames (e.g. "Mark Finger" → try
    MarkFinger, mark-finger, mark, etc. — first that returns HTTP 200 wins).

    Cache hierarchy:
      0. Curated known-orgs map  — overrides for big tech with unreliable profiles
      1. SQLite persistent cache — 24-hour TTL (survives restarts)
      2. GitHub API call         — last resort, tries multiple variants

    skip_hardcode=True: used by _country_via_repo_search so it reads the live
    GitHub location only, never inheriting a hardcoded country for an unrelated
    popular org (e.g. avoids 'lodash/lodash' → _KNOWN_ORG_COUNTRY → US).

    IMPORTANT — confirmed-found rule:
    If the GitHub API returns HTTP 200 for any variant but the location field is
    empty or unrecognisable, this function returns "Unknown" immediately and does
    NOT signal the caller to run a repo-search fallback.  The maintainer's profile
    exists — their location is simply not public.  Repo-search cannot improve on
    that and would only produce false results from unrelated popular repos.
    """
    if not username or username in ("—", ""):
        return "Unknown"

    # 0. DB cache — 24-hour TTL, only trust real country results.
    cached = _country_cache_get(username)
    if cached is not None and cached not in ("Unknown", "⚠️ Rate Limited", ""):
        return cached

    # 1. GitHub API — live lookup, always tried first before any hardcoded map.
    #    Priority: repo owner live location → if Org with no location → "❓ Org"
    #    so the caller (Signal 2) can check the individual maintainer's profile.
    headers = {"User-Agent": "RegistryIntelligencePlatform/1.0",
               "Accept":     "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    rate_limited  = False
    profile_found = False
    api_result    = None   # "❓ Org" / "Unknown" / None
    for variant in _username_variants(username):
        try:
            r = requests.get(f"https://api.github.com/users/{variant}",
                             headers=headers, timeout=TIMEOUT)
            if r.status_code == 200:
                profile_found = True
                data    = r.json()
                loc     = data.get("location") or ""
                country = _normalize_country(loc)
                if country and country != "Unknown":
                    _country_cache_set(username, country)
                    return country
                # Profile found but no location set.
                #   "❓ Org"  → GitHub Organisation — caller should try individual maintainer.
                #   "Unknown" → individual user who chose not to share location.
                api_result = "❓ Org" if data.get("type") == "Organization" else "Unknown"
                break
            if r.status_code in (403, 429):
                rate_limited = True
                break
        except Exception:
            continue

    if rate_limited:
        return "⚠️ Rate Limited"

    # Return "❓ Org" immediately — let Signal 2 check the individual maintainer.
    # Do NOT override with hardcoded map here; the maintainer's live location
    # is more accurate than a static entry written when the project had a different owner.
    if api_result == "❓ Org":
        return "❓ Org"

    # 2. Hardcoded map — last resort only.
    #    Used when: (a) no GitHub profile exists at all ("❓ No Profile"), OR
    #               (b) individual user has no location set ("Unknown").
    #    Covers big-tech orgs (facebook, google) where the org profile is empty
    #    AND the individual maintainer signal is also absent.
    #    Skipped for repo-search calls (skip_hardcode=True) to avoid cross-registry
    #    contamination.
    if not skip_hardcode and username.lower() in _KNOWN_ORG_COUNTRY:
        hardcoded = _KNOWN_ORG_COUNTRY[username.lower()]
        _country_cache_set(username, hardcoded)
        return hardcoded

    if not profile_found:
        return "❓ No Profile"

    return "Unknown"

def _extract_gh_username(maintainer: str) -> str:
    """
    Extract the GitHub username from a formatted maintainer string.
      "Org · redhuntlabs"  →  "redhuntlabs"
      "User · z4yx"        →  "z4yx"
      "👤 username"        →  "username"
      "🏢 OrgName"         →  "OrgName"
      "—" / ""             →  ""

    CRITICAL: Filters out person-name display strings.
    "User · Jeremy Ashkenas" → "" (don't lookup random Jeremy on GitHub)
    "Org · The Bootstrap Authors" → "" (don't lookup "The")
    These produce false-positive country results from random GitHub users
    who happen to share a first name with the real maintainer.
    """
    # Common words that are never GitHub usernames
    _NOISE = {"org", "user", "the", "a", "an", "and", "or", "foundation", "fdn",
              "inc", "incorporated", "ltd", "limited", "llc", "corp", "corporation",
              "team", "authors", "author", "community", "project", "labs", "lab",
              "group", "co", "company", "developers", "dev", "developer",
              "contributors", "contributor", "maintainers", "maintainer",
              "—", "", "all", "various", "anonymous", "official", "open",
              "source", "opensource"}
    m = str(maintainer).strip()
    if not m or m == "—":
        return ""
    if " · " in m:
        after = m.split(" · ", 1)[1].strip()
    else:
        after = re.sub(r"^[^\w]*", "", m).strip()

    # Strip trailing "+N" marker (e.g. "jQuery Foundation +1" → "jQuery Foundation")
    after = re.sub(r"\s*\+\d+\s*$", "", after).strip()
    if not after:
        return ""

    parts = after.split()
    uname = parts[0] if parts else ""

    # ── Person-name guard ──────────────────────────────────────────────
    # If the maintainer has MULTIPLE space-separated words AND each word is
    # an alphabetic capitalised token, this is a person's DISPLAY NAME
    # (e.g. "Jeremy Ashkenas", "Faruk Ateş", "The Bootstrap Authors") —
    # not a GitHub handle. Looking up such names produces wrong countries
    # because random GitHub users share these first names.
    if len(parts) >= 2:
        looks_like_display_name = all(
            p[0].isupper() and p[1:].replace(".", "").isalpha()
            for p in parts if p and len(p) > 1
        )
        if looks_like_display_name:
            return ""

    # First word is a noise word → skip
    if uname.lower() in _NOISE:
        return ""

    # Reverse-DNS Maven groupIds (com.google.guava, org.apache.commons …) are
    # NOT GitHub usernames. Map them to the most likely GitHub org name:
    # the SECOND segment after the TLD prefix.
    #   com.google.guava       → "google"
    #   org.apache.commons     → "apache"
    #   io.netty.client        → "netty"
    #   org.springframework.*  → "spring-projects"  (well-known mapping)
    if "." in uname and any(uname.lower().startswith(p) for p in (
            "com.", "org.", "io.", "net.", "edu.", "gov.", "co.", "uk.",
            "dev.", "app.", "me.", "ai.")):
        segs = uname.split(".")
        if len(segs) >= 2 and segs[1]:
            # Known mappings (when the segment != GitHub org name)
            _MAPS = {
                "springframework": "spring-projects",
                "fasterxml":       "FasterXML",
                "jboss":           "jbossorg",
                "eclipse":         "eclipse",
                "googlecode":      "google",
                "sun":             "openjdk",
            }
            second = segs[1].lower()
            uname = _MAPS.get(second, segs[1])

    return re.sub(r"[^a-zA-Z0-9\-]", "", uname)

# ── Package-name → canonical GitHub org map ──────────────────────────────────
# For widely-known packages where the registry (especially NuGet/Packagist)
# doesn't link to the upstream GitHub repo AND the maintainer is a person's
# display name (blocked by safety guard), this map provides the canonical
# GitHub org so the country lookup can resolve. Used as a fallback layer.
_PACKAGE_TO_GH_ORG: dict[str, str] = {
    # jQuery family
    "jquery":"jquery", "jqueryui":"jquery", "jquerymigrate":"jquery",
    "jqueryuicombined":"jquery", "jquerytouchpunch":"jquery",
    "jqueryuirails":"jquery", "jquerymigraterails":"jquery",
    # Bootstrap & related
    "bootstrap":"twbs", "modernizr":"Modernizr",
    # Date/time
    "momentjs":"moment", "moment":"moment",
    "datefns":"date-fns", "dayjs":"iamkun",
    # Underscore/Backbone (Jeremy Ashkenas)
    "underscorejs":"jashkenas", "underscore":"jashkenas",
    "backbonejs":"jashkenas", "backbone":"jashkenas",
    # Charts / data viz
    "chartjs":"chartjs", "d3":"d3", "d3js":"d3", "threejs":"mrdoob",
    # Editors
    "ckeditor":"ckeditor", "ckeditor4":"ckeditor", "ckeditor5":"ckeditor",
    "froalaeditor":"froala-labs", "froala":"froala-labs",
    "froalaeditorsdk":"froala-labs", "tinymce":"tinymce",
    "codemirror":"codemirror", "quill":"slab", "quilljs":"slab",
    "monacoeditor":"microsoft", "monaco":"microsoft",
    # UI components / carousels / lightboxes
    "dropzone":"dropzone", "fancybox":"fancyapps", "lightbox":"lokeshdhakar",
    "lightbox2":"lokeshdhakar",
    "select2":"select2", "slick":"kenwheeler", "swiper":"nolimits4web",
    "splide":"Splidejs", "splidejs":"Splidejs",
    "aos":"michalsnik", "lazysizes":"aFarkas",
    "clipboardjs":"zenorocha", "clipboard":"zenorocha",
    "hammerjs":"hammerjs", "hammer":"hammerjs",
    "fullcalendar":"fullcalendar",
    "datatables":"DataTables", "datatablesnet":"DataTables",
    "pdfjs":"mozilla", "pdfjsdist":"mozilla",
    # Notifications
    "toastr":"CodeSeven", "sweetalert":"sweetalert2", "sweetalert2":"sweetalert2",
    # CSS / animation / icons
    "animatecss":"animate-css", "animate":"animate-css",
    "gsap":"greensock",
    "popper":"popperjs", "popperjs":"popperjs", "floatingui":"floating-ui",
    "lottiefiles":"LottieFiles", "lottie":"LottieFiles", "lottieweb":"airbnb",
    "lucide":"lucide-icons", "lucideicons":"lucide-icons",
    "fontawesome":"FortAwesome", "feathericons":"feathericons",
    # Modern JS frameworks/libs
    "react":"facebook", "reactdom":"facebook", "reactnative":"facebook",
    "vue":"vuejs", "vuejs":"vuejs",
    "angular":"angular", "angularjs":"angular",
    "svelte":"sveltejs", "sveltejs":"sveltejs",
    "ember":"emberjs", "emberjs":"emberjs",
    "preact":"preactjs", "preactjs":"preactjs",
    "solid":"solidjs", "solidjs":"solidjs",
    "alpine":"alpinejs", "alpinejs":"alpinejs",
    # CSS frameworks
    "tailwindcss":"tailwindlabs", "tailwind":"tailwindlabs",
    "bulma":"jgthms", "foundation":"foundation",
    # CSS-in-JS / styling
    "styledcomponents":"styled-components", "emotion":"emotion-js",
    # UI kits
    "materialui":"mui", "mui":"mui",
    "antdesign":"ant-design", "antd":"ant-design",
    "chakraui":"chakra-ui", "chakra":"chakra-ui",
    "radixui":"radix-ui", "elementui":"ElemeFE", "elementplus":"element-plus",
    "framermotion":"framer",
    # Older / legacy
    "prototype":"prototypejs", "prototypejs":"prototypejs",
    "zepto":"madrobby", "zeptojs":"madrobby",
    "knockoutjs":"knockout", "knockout":"knockout",
    "scriptaculous":"madrobby", "mootools":"mootools",
    # Markdown
    "marked":"markedjs", "markdownit":"markdown-it", "showdown":"showdownjs",
    # Other popular
    "lodash":"lodash", "axios":"axios",
    "socketio":"socketio", "socketioparser":"socketio",
    "closurelibrary":"google", "googleclosurelibrary":"google",
    "corejs":"zloirock",
    "expressjs":"expressjs", "express":"expressjs",
    "nextjs":"vercel", "next":"vercel",
    "nuxt":"nuxt", "nuxtjs":"nuxt",
    "gatsby":"gatsbyjs", "gatsbyjs":"gatsbyjs",
    "prism":"PrismJS", "prismjs":"PrismJS",
    "litelement":"lit", "lithtml":"lit", "lit":"lit",
    "zonejs":"angular", "zone":"angular",
}

def _normalize_pkg_name(s: str) -> str:
    """Strip separators + lowercase for package-name lookup."""
    return re.sub(r'[\s._\-/:@]', '', str(s or "").lower())

def _enrich_countries(df, github_token: str = "") -> "pd.DataFrame":
    """
    Add a 'Country' column to the results dataframe — PARALLEL implementation.

    Optimization strategy:
      1. Collect all unique (gh_owner, extracted_username) candidates across rows
      2. Deduplicate — same name across many rows is looked up only ONCE
      3. Fetch ALL unique names in PARALLEL via ThreadPoolExecutor (8 workers)
      4. For rows still Unknown, do parallel repo-search fallback (4 workers)
      5. Stitch results back to each row

    Why this is much faster:
      • Old code: 30 rows → 30+ sequential API calls (3-15s)
      • New code: ~10-15 unique names → batched parallel (1-2s)
      • Repo search only runs for genuinely unresolved rows, also parallel
    """
    if df.empty:
        df = df.copy()
        df.insert(df.columns.get_loc("Maintainer") + 1, "Country", [])
        return df

    # ── Pass 1: extract candidates for every row ──────────────────────────
    candidates = []
    for _, row in df.iterrows():
        lib       = row.get("Library", "") or ""
        gh_owner  = (row.get("_gh_owner") or "").strip()
        uname     = _extract_gh_username(row.get("Maintainer", "") or "")
        # Package-name canonical lookup — well-known packages with no upstream link
        pkg_org   = _PACKAGE_TO_GH_ORG.get(_normalize_pkg_name(lib), "")
        candidates.append({
            "lib":      lib,
            "gh_owner": gh_owner,
            "uname":    uname,
            "pkg_org":  pkg_org,
        })

    # ── Pass 2: collect unique names that need a GitHub API lookup ────────
    unique_names = set()
    for c in candidates:
        if c["gh_owner"]:
            unique_names.add(c["gh_owner"])
        if c["uname"]:
            unique_names.add(c["uname"])
        if c["pkg_org"]:
            unique_names.add(c["pkg_org"])

    # ── Pass 3: parallel fetch every unique name (8 workers) ──────────────
    name_to_country: dict[str, str] = {}
    if unique_names:
        with ThreadPoolExecutor(max_workers=8) as _ex:
            _futures = {_ex.submit(_fetch_github_country, n, github_token): n
                        for n in unique_names}
            for _fut in as_completed(_futures):
                _name = _futures[_fut]
                try:
                    name_to_country[_name] = _fut.result() or "Unknown"
                except Exception:
                    name_to_country[_name] = "Unknown"

    # ── Pass 3b: org top-contributor lookup ───────────────────────────────
    # When an org has no public location ("❓ Org"), fetch its top contributor
    # and use their country. e.g. axios org → jasonsaayman → South Africa.
    org_to_contributor: dict[str, str] = {}
    _orgs_no_loc = {n for n, c in name_to_country.items() if c == "❓ Org"}
    if _orgs_no_loc:
        _org_repo_map: dict[str, str] = {}
        for _c in candidates:
            # Only use gh_owner (explicit GitHub URL from adapter) — NOT pkg_org.
            # pkg_org is inferred from package name and would produce wrong
            # contributor lookups for cross-registry packages (NuGet "axios" ≠ npm axios).
            _org = _c.get("gh_owner", "")
            if _org and _org in _orgs_no_loc and _org not in _org_repo_map:
                _rn = _c["lib"].split("/")[-1]
                if _rn and len(_rn) >= 2:
                    _org_repo_map[_org] = f"{_org}/{_rn}"

        def _fetch_top_contributor(repo_path: str) -> str:
            # Use most recent committer (not all-time top contributor) —
            # reflects the current active maintainer, not the original author.
            _h = {"Accept": "application/vnd.github+json",
                  "User-Agent": "RegistryIntelligencePlatform/1.0"}
            if github_token: _h["Authorization"] = f"Bearer {github_token}"
            try:
                _r = requests.get(
                    f"https://api.github.com/repos/{repo_path}/commits?per_page=1",
                    headers=_h, timeout=TIMEOUT)
                if _r.status_code == 200:
                    _items = _r.json()
                    if isinstance(_items, list) and _items:
                        _author = _items[0].get("author") or {}
                        return _author.get("login", "")
            except Exception:
                pass
            return ""

        with ThreadPoolExecutor(max_workers=4) as _ex:
            _cfuts = {_ex.submit(_fetch_top_contributor, rp): org
                      for org, rp in _org_repo_map.items()}
            for _fut in as_completed(_cfuts):
                _org = _cfuts[_fut]
                try:
                    _contrib = _fut.result() or ""
                    if _contrib:
                        org_to_contributor[_org] = _contrib
                except Exception:
                    pass

        _new_names = set(org_to_contributor.values()) - set(name_to_country.keys())
        if _new_names:
            with ThreadPoolExecutor(max_workers=4) as _ex:
                _nfuts = {_ex.submit(_fetch_github_country, n, github_token): n
                          for n in _new_names}
                for _fut in as_completed(_nfuts):
                    _n = _nfuts[_fut]
                    try:
                        name_to_country[_n] = _fut.result() or "Unknown"
                    except Exception:
                        name_to_country[_n] = "Unknown"

    # ── Pass 4: stitch per-row country + collect repo-search candidates ───
    # Resolution order per row:
    #   1. _gh_owner  (from adapter repo URL — authoritative signal)
    #   2. uname      (from Maintainer field — ONLY when _gh_owner absent)
    #   3. pkg_org    (well-known package→org map — ONLY when both above absent)
    #   4. repo search (ONLY when no GitHub profile found at all)
    #
    # CRITICAL RULE — two distinct sentinel values:
    #   "Unknown"      = GitHub profile WAS found, location simply not public
    #                    → FINAL answer, do NOT fall through to uname/pkg_org
    #   "❓ No Profile" = no GitHub profile exists for any variant tried
    #                    → continue to next signal; repo-search allowed
    #
    # This prevents the false-country bug: _gh_owner returns "Unknown" (empty
    # location on real profile) → old code fell through to uname → matched a
    # different person with same name who had a US location → showed "United States"
    countries          = []
    repo_search_queue  = []
    _FINAL   = {"Unknown", "⚠️ Rate Limited"}          # confirmed answer — stop chain
    _MISSING = {"❓ No Profile", "❓ Org", "", None}    # no info yet — try next signal
    for i, c in enumerate(candidates):
        country = "❓ No Profile"

        # Signal 1: _gh_owner from source repo URL (most reliable — direct from metadata)
        if c["gh_owner"]:
            country = name_to_country.get(c["gh_owner"], "❓ No Profile")

        # Signal 1b: pkg_org from curated package→org map.
        # Runs ONLY when _gh_owner was absent (no repo URL in metadata).
        # Checked BEFORE uname because it is a curated package-level signal
        # (high confidence), whereas uname is individual-level (lower confidence)
        # and can return "Unknown" (FINAL) which would block Signal 2.
        if not c["gh_owner"] and c["pkg_org"]:
            pkg_result = name_to_country.get(c["pkg_org"], "❓ No Profile")
            if pkg_result not in _MISSING:
                country = pkg_result

        # Signal 2: uname from Maintainer display name.
        # Runs when _gh_owner absent AND pkg_org absent/unresolved, OR
        # when _gh_owner returned "❓ Org" (org with no location — individual may have one).
        # Never runs when _gh_owner returned "Unknown" — individual chose not to share.
        if country in _MISSING and c["uname"]:
            country = name_to_country.get(c["uname"], "❓ No Profile")

        # Signal 1c: org top-contributor fallback.
        # Only fires when _gh_owner is explicitly set (adapter provided a real
        # GitHub URL) AND the org has no public location. Using pkg_org here
        # would produce false positives for cross-registry name collisions
        # (e.g. NuGet "axios" ≠ npm axios, but shares the same pkg_org="axios").
        if country in _MISSING and c["gh_owner"] and c["gh_owner"] in org_to_contributor:
            _cc = name_to_country.get(org_to_contributor[c["gh_owner"]], "❓ No Profile")
            if _cc not in _MISSING:
                country = _cc

        # Repo-search fallback: only when no GitHub profile was found at all.
        if country == "❓ No Profile" and c["lib"] and len(c["lib"]) >= 3:
            repo_search_queue.append((i, c["lib"]))
            countries.append("Unknown")    # placeholder, may be overridden
        else:
            countries.append(country if country not in _MISSING else "Unknown")

    # ── Pass 5: parallel repo-search fallback for still-Unknown rows ──────
    # Use a smaller pool (4) — search API has stricter rate limits than user API
    if repo_search_queue:
        # Deduplicate by library name too
        unique_libs = {lib for _, lib in repo_search_queue}
        lib_to_country: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=4) as _ex:
            _futs = {_ex.submit(_country_via_repo_search, lib, github_token): lib
                     for lib in unique_libs}
            for _fut in as_completed(_futs):
                _lib = _futs[_fut]
                try:
                    lib_to_country[_lib] = _fut.result() or "Unknown"
                except Exception:
                    lib_to_country[_lib] = "Unknown"
        # Apply repo-search results back to the corresponding rows
        for idx, lib in repo_search_queue:
            c = lib_to_country.get(lib, "Unknown")
            if c not in _MISSING:
                countries[idx] = c

    df = df.copy()
    df.insert(df.columns.get_loc("Maintainer") + 1, "Country", countries)
    return df

@st.cache_data(ttl=7200, show_spinner=False)
def _country_via_repo_search(pkg_name: str, token: str = "") -> str:
    """
    Last-resort country lookup: search GitHub for repos named like the package,
    take the top-starred result's owner, and look up THEIR country.

    Works WITHOUT a token (lower rate limits but still functional).
    Most popular packages have a canonical upstream GitHub repo — if "react"
    returns facebook/react as the top hit, that's the right project.
    """
    if not pkg_name or len(pkg_name) < 3:
        return "Unknown"
    headers = {"User-Agent": "RegistryIntelligencePlatform/1.0",
               "Accept":     "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.get(
            f"https://api.github.com/search/repositories"
            f"?q={requests.utils.quote(pkg_name)}+in:name"
            f"&sort=stars&per_page=5",
            headers=headers, timeout=8)
        if r.status_code != 200:
            return "Unknown"
        for item in r.json().get("items", []):
            # Filter: only accept high-confidence name matches to avoid
            # picking unrelated repos (e.g., "react" should match "react"
            # not "react-native-some-tiny-pkg")
            repo_name = (item.get("name", "") or "").lower()
            if repo_name != pkg_name.lower() and pkg_name.lower() not in repo_name:
                continue
            owner = (item.get("owner") or {}).get("login", "")
            if owner:
                # skip_hardcode=True: read live GitHub location only.
                # Prevents inheriting a hardcoded country for a popular org
                # that has nothing to do with the package being searched.
                country = _fetch_github_country(owner, token, skip_hardcode=True)
                if country not in ("Unknown", "⚠️ Rate Limited", "❓ No Profile"):
                    return country
    except Exception:
        pass
    return "Unknown"

def _flag(country: str) -> str:
    """Return a Unicode flag emoji for common countries."""
    _FLAGS = {
        "United Kingdom":"🇬🇧","United States":"🇺🇸","Germany":"🇩🇪","France":"🇫🇷",
        "India":"🇮🇳","China":"🇨🇳","Russia":"🇷🇺","Canada":"🇨🇦","Australia":"🇦🇺",
        "Netherlands":"🇳🇱","Japan":"🇯🇵","South Korea":"🇰🇷","Brazil":"🇧🇷",
        "Sweden":"🇸🇪","Norway":"🇳🇴","Finland":"🇫🇮","Denmark":"🇩🇰",
        "Switzerland":"🇨🇭","Spain":"🇪🇸","Italy":"🇮🇹","Poland":"🇵🇱",
        "Ukraine":"🇺🇦","Israel":"🇮🇱","Singapore":"🇸🇬","Taiwan":"🇹🇼",
        "Portugal":"🇵🇹","Czech Republic":"🇨🇿","Romania":"🇷🇴","Belgium":"🇧🇪",
        "Austria":"🇦🇹","New Zealand":"🇳🇿","Argentina":"🇦🇷","Mexico":"🇲🇽",
        "South Africa":"🇿🇦","Pakistan":"🇵🇰","Iran":"🇮🇷","Turkey":"🇹🇷",
        "Egypt":"🇪🇬","Nigeria":"🇳🇬","Indonesia":"🇮🇩","Vietnam":"🇻🇳",
        "Thailand":"🇹🇭","Malaysia":"🇲🇾","Philippines":"🇵🇭","Bangladesh":"🇧🇩",
        "Hungary":"🇭🇺","Greece":"🇬🇷","Ireland":"🇮🇪","Hong Kong":"🇭🇰",
        "United Arab Emirates":"🇦🇪","Saudi Arabia":"🇸🇦","Colombia":"🇨🇴",
        "Chile":"🇨🇱","Morocco":"🇲🇦","Kenya":"🇰🇪","Ghana":"🇬🇭",
        "🌐 Remote / Global":"🌐","Unknown":"❓",
    }
    return _FLAGS.get(country, "🏳")

def _fmt_country(country: str) -> str:
    return f"{_flag(country)} {country}"

# ── Flag image URLs (flagcdn.com) ──────────────────────────────────────────────
# Maps full country name → ISO 3166-1 alpha-2 lowercase code used by flagcdn.com
_COUNTRY_ISO2: dict[str, str] = {
    "United Kingdom":"gb","United States":"us","Germany":"de","France":"fr",
    "India":"in","China":"cn","Russia":"ru","Canada":"ca","Australia":"au",
    "Netherlands":"nl","Japan":"jp","South Korea":"kr","Brazil":"br",
    "Sweden":"se","Norway":"no","Finland":"fi","Denmark":"dk",
    "Switzerland":"ch","Spain":"es","Italy":"it","Poland":"pl",
    "Ukraine":"ua","Israel":"il","Singapore":"sg","Taiwan":"tw",
    "Portugal":"pt","Czech Republic":"cz","Romania":"ro","Belgium":"be",
    "Austria":"at","New Zealand":"nz","Argentina":"ar","Mexico":"mx",
    "South Africa":"za","Pakistan":"pk","Iran":"ir","Turkey":"tr",
    "Egypt":"eg","Nigeria":"ng","Indonesia":"id","Vietnam":"vn",
    "Thailand":"th","Malaysia":"my","Philippines":"ph","Bangladesh":"bd",
    "Hungary":"hu","Greece":"gr","Ireland":"ie","Hong Kong":"hk",
    "United Arab Emirates":"ae","Saudi Arabia":"sa","Colombia":"co",
    "Chile":"cl","Peru":"pe","Morocco":"ma","Kenya":"ke","Ghana":"gh",
    "Ethiopia":"et","Algeria":"dz","Tunisia":"tn","Libya":"ly",
    "Sudan":"sd","Angola":"ao","Tanzania":"tz","Uganda":"ug","Zambia":"zm",
    "Zimbabwe":"zw","Mozambique":"mz","Botswana":"bw","Ivory Coast":"ci",
    "Cameroon":"cm","Senegal":"sn","Venezuela":"ve","Ecuador":"ec",
    "Bolivia":"bo","Paraguay":"py","Uruguay":"uy","Guatemala":"gt",
    "Costa Rica":"cr","Panama":"pa","Cuba":"cu","Dominican Republic":"do",
    "Jamaica":"jm","Honduras":"hn","El Salvador":"sv","Nicaragua":"ni",
    "Jordan":"jo","Lebanon":"lb","Syria":"sy","Iraq":"iq","Kuwait":"kw",
    "Qatar":"qa","Bahrain":"bh","Oman":"om","Yemen":"ye","Afghanistan":"af",
    "Sri Lanka":"lk","Nepal":"np","Myanmar":"mm","Cambodia":"kh",
    "Uzbekistan":"uz","Georgia":"ge","Azerbaijan":"az","Armenia":"am",
    "Moldova":"md","Albania":"al","North Macedonia":"mk",
    "Bosnia and Herzegovina":"ba","Montenegro":"me","Slovenia":"si",
    "Slovakia":"sk","Croatia":"hr","Serbia":"rs","Bulgaria":"bg",
    "Lithuania":"lt","Latvia":"lv","Estonia":"ee","Belarus":"by",
    "Kazakhstan":"kz","Mongolia":"mn","North Korea":"kp","Bhutan":"bt",
    "Maldives":"mv","Fiji":"fj","Papua New Guinea":"pg",
    "Iceland":"is","Luxembourg":"lu","Cyprus":"cy","Malta":"mt",
    "Liechtenstein":"li","Monaco":"mc","San Marino":"sm","Vatican City":"va",
    "Andorra":"ad","Puerto Rico":"pr","Trinidad and Tobago":"tt",
}

def _country_flag_url(country: str) -> str:
    """
    Return a flagcdn.com image URL for the given full country name.
    Returns an empty string for Unknown / Remote / Global so the
    ImageColumn shows nothing instead of a broken image.
    """
    iso2 = _COUNTRY_ISO2.get(country, "")
    if not iso2:
        return ""
    return f"https://flagcdn.com/20x15/{iso2}.png"

def _fmt_dl(n):
    if not n or n == 0: return "—"
    if n >= 1_000_000_000: return f"{n/1_000_000_000:.1f}B"
    if n >= 1_000_000:     return f"{n/1_000_000:.1f}M"
    if n >= 1_000:         return f"{n/1_000:.0f}K"
    return str(n)

def _lic(val):
    """
    Normalise a license value (string OR URL) into a clean SPDX-style identifier.

    Handles common garbage like:
      "LICENSE" / "license" / "LICENSE.txt"  (just the filename of a license file)
      "mit-license.php"                      (legacy opensource.org filenames)
      "https://github.com/foo/bar/blob/main/LICENSE"  (URLs to license files)
      "https://opensource.org/licenses/MIT"  (canonical SPDX URLs)
      "https://www.apache.org/licenses/LICENSE-2.0"
    All of these should resolve to a clean SPDX identifier.
    """
    if not val or str(val).strip() in ("—", "N/A", ""):
        return "—"
    raw = str(val).strip()

    # Reject pure noise tokens — license filenames, not licenses
    _NOISE = {"license", "license.txt", "license.md", "license.html",
              "licence", "licence.txt", "copying", "copyright", "notice",
              "license.rst"}
    if raw.lower() in _NOISE:
        return "—"

    # Map common license-related URL fragments / filenames to SPDX
    _PATTERNS = [
        # (substring needle to look for in lowercase, SPDX result)
        ("apache-2.0", "Apache-2.0"), ("apache2.0", "Apache-2.0"),
        ("apache-license-2", "Apache-2.0"), ("licenses/license-2.0", "Apache-2.0"),
        ("apache 2.0", "Apache-2.0"),
        ("gpl-3.0", "GPL-3.0"), ("gpl-2.0", "GPL-2.0"),
        ("gplv3", "GPL-3.0"), ("gplv2", "GPL-2.0"),
        ("agpl-3.0", "AGPL-3.0"), ("agpl", "AGPL-3.0"),
        ("lgpl-2.1", "LGPL-2.1"), ("lgpl-3.0", "LGPL-3.0"), ("lgpl", "LGPL"),
        ("mit-license", "MIT"), ("licenses/mit", "MIT"), ("/mit", "MIT"),
        ("bsd-3-clause", "BSD-3-Clause"), ("bsd-2-clause", "BSD-2-Clause"),
        ("bsd 3-clause", "BSD-3-Clause"), ("bsd 2-clause", "BSD-2-Clause"),
        ("bsd-3", "BSD-3-Clause"), ("bsd-2", "BSD-2-Clause"),
        ("mpl-2.0", "MPL-2.0"), ("mpl 2.0", "MPL-2.0"),
        ("isc-license", "ISC"), ("/isc", "ISC"),
        ("unlicense", "Unlicense"), ("cc0-1.0", "CC0-1.0"), ("cc-by", "CC-BY"),
        ("epl-2.0", "EPL-2.0"), ("epl-1.0", "EPL-1.0"),
        ("zlib", "Zlib"), ("wtfpl", "WTFPL"), ("artistic", "Artistic"),
    ]
    lower = raw.lower()
    for needle, spdx in _PATTERNS:
        if needle in lower:
            return spdx

    # If it's a URL but didn't match a known pattern → unparseable
    if raw.startswith("http"):
        # Last-resort: take last path segment, but reject if it's just a filename
        tail = raw.rstrip("/").split("/")[-1].split("?")[0]
        if tail.lower() in _NOISE or "." in tail.lower():
            return "—"   # don't show "LICENSE" or "LICENSE.txt"
        return tail or "—"

    return raw or "—"

def _clean_repo_url(url):
    """
    Normalize a repository URL to a clean https:// link.

    npm returns URLs like:
      git+https://github.com/axios/axios.git
      git://github.com/axios/axios.git
      https://github.com/axios/axios.git

    All of these should become:
      https://github.com/axios/axios

    Returns None when no valid URL exists, so Streamlit's LinkColumn
    renders an empty cell instead of a broken link like /N/A.
    """
    if not url or url in ("N/A", "—", "", "N\\A"):
        return None
    if isinstance(url, dict):
        url = url.get("url") or ""
    url = str(url).strip()
    if not url or url in ("N/A", "—", "N\\A"):
        return None
    # Strip git+ or git:// prefix
    url = re.sub(r"^git\+", "", url)
    url = re.sub(r"^git://", "https://", url)
    url = re.sub(r"^ssh://git@", "https://", url)
    # Strip .git suffix
    if url.endswith(".git"):
        url = url[:-4]
    # Force https://
    if url.startswith("http://"):
        url = "https://" + url[7:]
    # Final validation — must be a real web URL
    if not url.startswith(("https://", "http://")):
        return None
    return url

def _fmt_date(s):
    """Return YYYY-MM-DD from any ISO-ish string, or '—'."""
    if not s or str(s).strip() in ("—","N/A",""): return "—"
    s = str(s).strip()
    # OData /Date(ms)/ format (Chocolatey)
    if s.startswith("/Date("):
        try:
            ms = int(s.split("(")[1].split(")")[0].split("+")[0].split("-")[0])
            return datetime.datetime.utcfromtimestamp(ms/1000).strftime("%Y-%m-%d")
        except: return "—"
    # Maven epoch-ms (13-digit integer)
    if s.isdigit() and len(s) == 13:
        try:
            return datetime.datetime.utcfromtimestamp(int(s)/1000).strftime("%Y-%m-%d")
        except: return "—"
    # ISO / RFC 3339 strings
    return s[:10] if len(s) >= 10 else "—"

# ── Abandoned Package Detection ────────────────────────────────────────────────
def _pkg_status(last_updated: str) -> str:
    """
    Classify a package as Active / Aging / Abandoned based on last update date.

      ✅ Active    — updated within the last 6 months
      ⚠️ Aging     — last update between 6 months and 2 years ago
      🚨 Abandoned — no update in more than 2 years
      ❓ Unknown   — no date data available
    """
    if not last_updated or last_updated in ("—", "N/A", ""):
        return "❓ Unknown"
    try:
        date = datetime.datetime.strptime(last_updated[:10], "%Y-%m-%d")
        now  = datetime.datetime.utcnow()
        days = (now - date).days
        if days <= 180:
            return "✅ Active"
        elif days <= 730:
            return "⚠️ Aging"
        else:
            return "🚨 Abandoned"
    except Exception:
        return "❓ Unknown"

# ── Risk Classification (Phase 2 Security Suite) ───────────────────────────────
# License risk tiers — based on common compliance / supply-chain practice.
_LICENSE_SAFE = {
    "mit", "apache-2.0", "apache 2.0", "apache2", "apache",
    "bsd-3-clause", "bsd-2-clause", "bsd", "0bsd", "isc",
    "unlicense", "cc0-1.0", "cc0", "public domain", "wtfpl",
    "zlib", "x11", "boost",
}
_LICENSE_COPYLEFT = {
    "gpl-3.0", "gpl-2.0", "gpl-2", "gpl-3", "gpl", "gnu general public",
    "agpl-3.0", "agpl", "lgpl-2.1", "lgpl-3.0", "lgpl",
    "mpl-2.0", "mpl-1.1", "mpl",
    "epl-2.0", "epl-1.0", "epl", "cddl",
}

def _license_risk(license_str: str) -> str:
    """
    Classify a license string into one of:
      ✅ Safe       — MIT / Apache / BSD / ISC / Unlicense (permissive)
      ⚠️ Copyleft   — GPL / AGPL / LGPL / MPL (viral or weak-viral)
      ❌ Missing    — no license declared (legal grey area)
      ⚪ Other      — proprietary, custom, or unrecognised
    """
    if not license_str or str(license_str).strip() in ("—", "N/A", "", "license", "LICENSE"):
        return "❌ Missing"
    l = str(license_str).lower().strip()
    # Strip common noise tokens
    l = re.sub(r"\s+", " ", l)
    for safe in _LICENSE_SAFE:
        if safe in l:
            return "✅ Safe"
    for copyleft in _LICENSE_COPYLEFT:
        if copyleft in l:
            return "⚠️ Copyleft"
    return "⚪ Other"

# Country risk tiers — conservative defaults; user can adjust as needed.
_COUNTRY_TIER: dict[str, str] = {
    # 🟢 Trusted — Western democracies + strong tech-allied nations
    "United States":"Trusted","United Kingdom":"Trusted",
    "Germany":"Trusted","Canada":"Trusted","Australia":"Trusted",
    "Japan":"Trusted","South Korea":"Trusted","Singapore":"Trusted",
    "Netherlands":"Trusted","Sweden":"Trusted","France":"Trusted",
    "Switzerland":"Trusted","Norway":"Trusted","Finland":"Trusted",
    "Denmark":"Trusted","Ireland":"Trusted","New Zealand":"Trusted",
    "Austria":"Trusted","Belgium":"Trusted","Luxembourg":"Trusted",
    "Iceland":"Trusted","Taiwan":"Trusted","Israel":"Trusted",
    # Caution — large active dev communities but variable supply-chain hygiene
    "India":"Caution","Brazil":"Caution","Mexico":"Caution",
    "Poland":"Caution","Ukraine":"Caution","Romania":"Caution",
    "Czech Republic":"Caution","Spain":"Caution","Italy":"Caution",
    "Portugal":"Caution","Turkey":"Caution","Bulgaria":"Caution",
    "Hungary":"Caution","South Africa":"Caution","Greece":"Caution",
    "Argentina":"Caution","Chile":"Caution","Indonesia":"Caution",
    "Vietnam":"Caution","Malaysia":"Caution","Philippines":"Caution",
    "Thailand":"Caution","Egypt":"Caution","Pakistan":"Caution",
    "Bangladesh":"Caution","Nigeria":"Caution","Kenya":"Caution",
    "Morocco":"Caution","Colombia":"Caution","Saudi Arabia":"Caution",
    "United Arab Emirates":"Caution","Lithuania":"Caution",
    "Latvia":"Caution","Estonia":"Caution","Slovakia":"Caution",
    "Croatia":"Caution","Serbia":"Caution","Slovenia":"Caution",
    "Cyprus":"Caution","Malta":"Caution","Hong Kong":"Caution",
    # Restricted — commonly flagged in compliance / sanctions contexts
    "Russia":"Restricted","China":"Restricted",
    "Iran":"Restricted","North Korea":"Restricted",
    "Belarus":"Restricted","Cuba":"Restricted",
    "Syria":"Restricted","Venezuela":"Restricted",
    "Myanmar":"Restricted",
}

def _country_tier(country: str) -> str:
    """Map a country name to its risk tier (or empty if unknown)."""
    if not country or country in ("Unknown", "—", "", "❓ Unknown", "⚠️ Rate Limited"):
        return "❓ Unrated"
    if country == "🌐 Remote / Global":
        return "Caution"
    return _COUNTRY_TIER.get(country, "Caution")   # default unmapped = caution

# ═══════════════════════════════════════════════════════════════════════════════
# SECURITY AUDIT MODULE
# ═══════════════════════════════════════════════════════════════════════════════
# Self-contained, extensible per-library security check system.
#
# To add a new check (e.g. Check 6: SBOM signing verification):
#   1. Write a function `_check_<name>(row, context) -> dict` returning:
#        {"severity": "critical"|"high"|"medium"|"low"|"pass",
#         "label":    "🔴 Critical: short reason",
#         "details":  "longer human-readable explanation"}
#   2. Add an entry to _SECURITY_CHECKS below.
# That's it — UI auto-renders the new check as a new column.
# ───────────────────────────────────────────────────────────────────────────────

# Severity ranking (higher number = worse) — used by the worst-of aggregator
_SEV_RANK = {"pass": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
_SEV_EMOJI = {
    "pass":     "✓",  "low":      "✓",
    "medium":   "⚠",  "high":     "⚠",
    "critical": "✗",
}
_SEV_LABEL = {
    "pass":     "Pass",     "low":      "Low",
    "medium":   "Medium",   "high":     "High",
    "critical": "Critical",
}

# ── Typosquatting data ────────────────────────────────────────────────────────
_POPULAR_PYPI: set = {
    "numpy", "pandas", "requests", "scipy", "matplotlib", "pillow",
    "tensorflow", "torch", "scikit-learn", "flask", "django", "fastapi",
    "sqlalchemy", "boto3", "pytest", "click", "pydantic", "celery",
    "redis", "cryptography", "paramiko", "urllib3", "certifi", "six",
    "packaging", "setuptools", "wheel", "pip", "virtualenv", "black",
    "flake8", "mypy", "pylint", "isort", "aiohttp", "httpx", "uvicorn",
    "gunicorn", "starlette", "jinja2", "markupsafe", "werkzeug",
    "pyyaml", "toml", "attrs", "psycopg2", "pymongo", "asyncpg",
    "stripe", "twilio", "openai", "anthropic", "langchain", "transformers",
    "huggingface-hub", "charset-normalizer", "idna", "itsdangerous",
    "colorama", "tqdm", "rich", "typer", "loguru", "httpcore",
    "anyio", "sniffio", "h11", "h2", "hyperframe", "hpack",
    "google-auth", "google-cloud-storage", "grpcio", "protobuf",
    "pyarrow", "polars", "dask", "numba", "cython", "cffi",
    "lxml", "beautifulsoup4", "selenium", "playwright", "scrapy",
    "alembic", "sqlmodel", "tortoise-orm", "pymysql", "motor",
}

_POPULAR_NPM: set = {
    "react", "react-dom", "lodash", "express", "axios", "moment",
    "webpack", "babel-core", "typescript", "eslint", "jest", "mocha",
    "chalk", "commander", "yargs", "inquirer", "dotenv",
    "mongoose", "sequelize", "knex", "typeorm", "socket.io", "ws",
    "cors", "body-parser", "morgan", "passport", "jsonwebtoken",
    "bcrypt", "bcryptjs", "nodemailer", "multer", "sharp",
    "redux", "mobx", "rxjs", "ramda", "next", "nuxt", "gatsby",
    "vue", "angular", "tailwindcss", "bootstrap", "styled-components",
    "aws-sdk", "firebase", "stripe", "twilio", "prettier",
    "husky", "nodemon", "pm2", "uuid", "nanoid", "slugify",
    "dayjs", "date-fns", "luxon", "cheerio", "puppeteer", "playwright",
    "semver", "glob", "minimatch", "cross-env", "rimraf", "mkdirp",
    "fs-extra", "debug", "winston", "pino", "got", "node-fetch",
    "superagent", "compression", "helmet", "events", "readable-stream",
    "through2", "bluebird", "async", "underscore", "immutable",
    "classnames", "prop-types", "react-router", "react-redux",
    "webpack-cli", "babel-loader", "css-loader", "style-loader",
    "postcss", "autoprefixer", "sass", "less",
}

def _levenshtein(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if s1 == s2:
        return 0
    if len(s1) < len(s2):
        s1, s2 = s2, s1
    if not s2:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (c1 != c2)))
        prev = curr
    return prev[-1]

# ─── Check 1 — Suspicious New Maintainer Account ─────────────────────────────
def _check_account_age(row, context):
    """
    Looks up the primary maintainer's GitHub account age. New accounts =
    typosquatting / supply-chain compromise red flag (event-stream 2018,
    XZ Utils 2024). Lazy lookup with session caching to avoid extra API calls.
    """
    token = (context or {}).get("token", "")
    gh_owner = (row.get("_gh_owner") or "").strip()
    if not gh_owner:
        gh_owner = _extract_gh_username(row.get("Maintainer", "") or "")
    if not gh_owner:
        return {"severity": "low",
                "label":    "No maintainer to verify",
                "details":  "Maintainer field empty — cannot fetch account age"}

    # Cache key in session_state so multiple checks share lookups
    cache = st.session_state.setdefault("_account_age_cache", {})
    if gh_owner in cache:
        info = cache[gh_owner]
    else:
        info = {"created_at": None}
        try:
            headers = {"User-Agent": "RegistryIntelligencePlatform/1.0",
                       "Accept":     "application/vnd.github+json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            r = requests.get(f"https://api.github.com/users/{gh_owner}",
                             headers=headers, timeout=8)
            if r.status_code == 200:
                info["created_at"] = r.json().get("created_at")
        except Exception:
            pass
        cache[gh_owner] = info

    age = _account_age(info.get("created_at") or "")
    days = age.get("days")
    if days is None:
        return {"severity": "low",
                "label":    "Age unknown",
                "details":  f"Could not fetch account age for {gh_owner}"}
    if days < 30:
        return {"severity": "critical",
                "label":    f"Account only {days}d old",
                "details":  f"GitHub account {gh_owner} is less than 30 days old — high risk of namespace squat / hijack"}
    if days < 180:
        return {"severity": "high",
                "label":    f"New account ({days}d)",
                "details":  f"GitHub account {gh_owner} is less than 6 months old"}
    if days < 730:
        return {"severity": "medium",
                "label":    f"Account {round(days/365,1)}y old",
                "details":  f"GitHub account {gh_owner} is between 6m and 2y old"}
    return {"severity": "pass",
            "label":    f"{round(days/365,1)}y old",
            "details":  f"GitHub account {gh_owner} is mature ({days} days old)"}

# ─── Check 2 — Abandoned Package ─────────────────────────────────────────────
def _check_abandoned(row, context):
    """Wraps _pkg_status into a structured CheckResult."""
    status = row.get("Status", "") or _pkg_status(row.get("Last Updated", ""))
    if "Abandoned" in status:
        return {"severity": "critical",
                "label":    "Abandoned (2y+ stale)",
                "details":  f"Last updated {row.get('Last Updated','—')} — no maintenance in over 2 years"}
    if "Aging" in status:
        return {"severity": "medium",
                "label":    "Aging (6m–2y)",
                "details":  f"Last updated {row.get('Last Updated','—')} — slowing maintenance"}
    if "Unknown" in status:
        return {"severity": "low",
                "label":    "Status unknown",
                "details":  "Registry did not provide a last-updated date"}
    return {"severity": "pass",
            "label":    "Active",
            "details":  f"Last updated {row.get('Last Updated','—')} — within 6 months"}

# ─── Check 3 — Known CVE ─────────────────────────────────────────────────────
def _check_cve(row, context):
    """
    Parses the CVEs column. If any CVE present → High severity.
    (CVSS escalation could be added later — would require an extra OSV call
    per package for detailed scoring.)
    """
    cves = str(row.get("CVEs", "") or "")
    if cves in ("None", "—", "", "Timeout", "Error", "N/A"):
        return {"severity": "pass",
                "label":    "No known CVEs",
                "details":  "OSV.dev + GitHub Advisory DB returned no vulnerabilities"}
    # Count only properly-formatted CVE/GHSA IDs
    cve_count = sum(1 for c in cves.split(",") if c.strip().startswith(("CVE", "GHSA")))
    if cve_count == 0:
        # Non-empty field but no recognisable CVE IDs — treat as unverified, not a confirmed vuln
        return {"severity": "low",
                "label":    "CVE data unrecognised",
                "details":  f"CVE field contains unrecognised format: {cves[:120]}"}
    if cve_count >= 3:
        return {"severity": "critical",
                "label":    f"{cve_count}+ CVEs",
                "details":  f"Multiple known vulnerabilities: {cves[:120]}"}
    return {"severity": "high",
            "label":    f"{cve_count} CVE found",
            "details":  f"Known vulnerability: {cves[:120]}"}

# ─── Check 4 — Bus Factor ────────────────────────────────────────────────────
def _check_bus_factor(row, context):
    """≤5 maintainers + high downloads = supply-chain single point of failure."""
    sm = row.get("Single Maintainer", "") or _single_maintainer_risk(
        row.get("Maintainer", ""), row.get("Downloads", ""))
    downloads = _parse_download_num(row.get("Downloads", ""))
    if "Bus Factor" in sm:
        if downloads >= 10_000_000:
            return {"severity": "critical",
                    "label":    "Bus Factor: ≤5 maint + 10M+ dl",
                    "details":  f"<=5 maintainers for a package with {row.get('Downloads','')} downloads — left-pad/event-stream risk"}
        return {"severity": "high",
                "label":    "Bus Factor (<=5 maintainers)",
                "details":  f"<=5 maintainers + {row.get('Downloads','')} downloads"}
    if "Solo" in sm:
        return {"severity": "medium",
                "label":    "Small team (moderate dl)",
                "details":  f"<=5 maintainers with {row.get('Downloads','')} downloads"}
    return {"severity": "pass",
            "label":    "Healthy maintainer count",
            "details":  "More than 5 maintainers with publish rights"}

# ─── Check 5 — Restricted Geographic Origin ──────────────────────────────────
def _check_country(row, context):
    """Maps the maintainer's country to the org's risk tier."""
    country = row.get("Country", "")
    if not country or country in ("Unknown", "—", "", "❓ Unknown"):
        return {"severity": "low",
                "label":    "Country unverified",
                "details":  "Country could not be resolved — informational only"}
    tier = _country_tier(country)
    if "Unrated" in tier:
        return {"severity": "low",
                "label":    "Country unverified",
                "details":  f"Country '{country}' could not be resolved to a risk tier — informational only"}
    if "Restricted" in tier:
        return {"severity": "critical",
                "label":    f"Restricted ({country})",
                "details":  f"Maintainer in restricted country {country} — sanctions / export-control concern"}
    if "Caution" in tier:
        return {"severity": "medium",
                "label":    f"Caution ({country})",
                "details":  f"Maintainer in caution-tier country {country}"}
    return {"severity": "pass",
            "label":    f"Trusted ({country})",
            "details":  f"Maintainer in trusted country {country}"}

# ─── Check 6 — GitHub Maintainer Count ───────────────────────────────────────
def _check_maintainer_count(row, context):
    """
    Fetches the exact count of people with write access to the GitHub repo.
    Primary: /collaborators (requires token). Fallback: /contributors (public).
    """
    token = (context or {}).get("token", "")
    repo  = str(row.get("Repo", "") or "")

    m = re.match(r"https?://github\.com/([^/]+)/([^/\s?#]+?)(?:\.git)?/?$", repo)
    if not m:
        return {"severity": "info",
                "label":    "N/A",
                "details":  "Not a GitHub repository — maintainer count unavailable"}

    owner, repo_name = m.group(1), m.group(2)
    cache = st.session_state.setdefault("_maint_count_cache", {})
    cache_key = f"{owner}/{repo_name}"

    if cache_key in cache:
        count, source = cache[cache_key]
    else:
        headers = {"User-Agent": "RegistryIntelligencePlatform/1.0",
                   "Accept":     "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        count, source = None, "unknown"
        try:
            r = requests.get(
                f"https://api.github.com/repos/{owner}/{repo_name}/collaborators"
                "?affiliation=all&per_page=100",
                headers=headers, timeout=8
            )
            if r.status_code == 200:
                count  = len(r.json())
                source = "collaborators"
                if 'rel="next"' in r.headers.get("Link", ""):
                    count = f"{count}+"
            elif r.status_code in (403, 404):
                r2 = requests.get(
                    f"https://api.github.com/repos/{owner}/{repo_name}/contributors"
                    "?per_page=100&anon=false",
                    headers=headers, timeout=8
                )
                if r2.status_code == 200:
                    count  = len(r2.json())
                    source = "contributors"
                    if 'rel="next"' in r2.headers.get("Link", ""):
                        count = f"{count}+"
        except Exception:
            pass
        cache[cache_key] = (count, source)

    if count is None:
        return {"severity": "info",
                "label":    "Lookup failed",
                "details":  f"Could not fetch maintainer count for {owner}/{repo_name}"}

    count_str = str(count)
    count_int = int(count_str.rstrip("+")) if count_str.rstrip("+").isdigit() else 0
    plus      = "+" if count_str.endswith("+") else ""
    label     = f"{count_str} maintainer{'s' if count_int != 1 else ''}"
    src_note  = f" (via {source})"

    return {"severity": "info",
            "label":    label,
            "details":  f"{count_str}{plus} people with access on {owner}/{repo_name}{src_note}"}


# ─── Check 7 — Typosquatting Detection ───────────────────────────────────────
def _check_typosquatting(row, context):
    """
    Flags packages whose name is suspiciously close (edit distance ≤ 2) to a
    known popular package — classic typosquatting supply-chain vector.
    """
    library  = str(row.get("Library", "") or "").strip().lower()
    registry = str(row.get("Registry", "") or "").strip()

    if not library or len(library) < 4:
        return {"severity": "pass",
                "label":    "Name OK",
                "details":  "Package name too short to run typosquat check"}

    if registry == "PyPI":
        popular = _POPULAR_PYPI
    elif registry in ("NPM", "npm"):
        popular = _POPULAR_NPM
    else:
        return {"severity": "pass",
                "label":    "N/A",
                "details":  f"Typosquat check not available for {registry}"}

    # Exact match = it IS the popular package — pass immediately
    if library in popular:
        return {"severity": "pass",
                "label":    "Known popular package",
                "details":  f"'{library}' is in the trusted popular package list"}

    # Find the closest popular package by edit distance
    closest, min_dist = None, 999
    for pkg in popular:
        if abs(len(library) - len(pkg)) > 3:
            continue
        d = _levenshtein(library, pkg)
        if d < min_dist:
            min_dist, closest = d, pkg

    if min_dist == 1:
        return {"severity": "critical",
                "label":    f"Typosquat? (1 char from '{closest}')",
                "details":  (f"'{library}' is 1 edit away from popular package '{closest}'"
                             f" — very likely typosquatting attack")}
    if min_dist == 2:
        return {"severity": "high",
                "label":    f"Suspicious (2 edits from '{closest}')",
                "details":  (f"'{library}' is 2 edits away from '{closest}'"
                             f" — review carefully before use")}
    if min_dist == 3 and len(library) <= 7:
        return {"severity": "medium",
                "label":    f"Similar name to '{closest}'",
                "details":  (f"'{library}' has some similarity to '{closest}'"
                             f" — low confidence, informational only")}

    return {"severity": "pass",
            "label":    "No typosquat match",
            "details":  f"'{library}' does not closely match any known popular package"}


# ─── Check 8 — Homoglyph Attack ──────────────────────────────────────────────
def _check_homoglyph(row, context):
    """
    Detects non-ASCII lookalike characters in the package name.
    Attackers substitute Cyrillic/Greek/Math chars that look identical to Latin
    letters — terminal renders them the same, but they resolve to a different pkg.
    """
    library = str(row.get("Library", "") or "").strip()
    if not library:
        return {"severity": "pass", "label": "N/A", "details": "No library name"}

    try:
        library.encode("ascii")
    except UnicodeEncodeError:
        bad = [f"U+{ord(c):04X}('{c}')" for c in library if ord(c) > 127][:5]
        return {"severity": "critical",
                "label":   "Homoglyph chars in name",
                "details": (f"'{library}' contains non-ASCII lookalike characters: "
                            f"{', '.join(bad)} — classic homoglyph impersonation attack")}

    return {"severity": "pass",
            "label":    "Name clean",
            "details":  f"'{library}' contains only standard ASCII characters"}


# ─── Check 9 — Phantom Repository ────────────────────────────────────────────
def _check_phantom_repo(row, context):
    """
    Checks whether the linked GitHub repository actually exists.
    Attackers list a deleted/nonexistent repo URL to appear legitimate.
    A 404 on the claimed repo = phantom repo = credibility fraud.
    """
    repo = str(row.get("Repo", "") or "").strip()
    if not repo or repo in ("—", "N/A", ""):
        return {"severity": "medium",
                "label":    "No repo linked",
                "details":  "Package has no linked source repository — zero transparency"}

    if "github.com" not in repo.lower():
        return {"severity": "pass",
                "label":    "Non-GitHub repo",
                "details":  f"Repo present (non-GitHub): {repo[:60]}"}

    cache = st.session_state.setdefault("_phantom_repo_cache", {})
    if repo in cache:
        code = cache[repo]
    else:
        code = -1
        try:
            r = requests.head(repo, timeout=8, allow_redirects=True)
            code = r.status_code
        except Exception:
            pass
        cache[repo] = code

    if code == 404:
        return {"severity": "critical",
                "label":    "Phantom repo (404)",
                "details":  f"Claimed repo returns 404 — does not exist: {repo[:80]}"}
    if code == -1:
        return {"severity": "low",
                "label":    "Repo unreachable",
                "details":  "Could not reach repository URL — check manually"}
    return {"severity": "pass",
            "label":    f"Repo exists ({code})",
            "details":  f"Repository URL is reachable: {repo[:60]}"}


# ─── Check 10 — Namespace Squatting ──────────────────────────────────────────
_ORG_PREFIXES: dict = {
    "aws":         "amazon",      "google":      "google",
    "microsoft":   "microsoft",   "stripe":      "stripe",
    "twilio":      "twilio",      "firebase":    "firebase",
    "shopify":     "shopify",     "cloudflare":  "cloudflare",
    "hashicorp":   "hashicorp",   "vercel":      "vercel",
    "netlify":     "netlify",     "mongodb":     "mongodb",
    "elastic":     "elastic",     "docker":      "docker",
    "kubernetes":  "kubernetes",  "grafana":     "grafana",
    "datadog":     "datadog",     "sentry":      "sentry",
    "openai":      "openai",      "anthropic":   "anthropic",
    "huggingface": "huggingface", "pytorch":     "pytorch",
    "tensorflow":  "tensorflow",  "fastapi":     "tiangolo",
}

def _check_namespace_squatting(row, context):
    """
    Flags packages that use a well-known org name as a prefix (aws-*, google-*)
    but whose repo/maintainer does not actually belong to that organisation.
    Classic impersonation trick to get developers to install fake 'official' SDKs.
    """
    library    = str(row.get("Library",    "") or "").strip().lower()
    repo       = str(row.get("Repo",       "") or "").strip().lower()
    maintainer = str(row.get("Maintainer", "") or "").strip().lower()

    if not library:
        return {"severity": "pass", "label": "N/A", "details": "No library name"}

    matched_prefix = matched_org = None
    for prefix, org in _ORG_PREFIXES.items():
        if library.startswith(prefix + "-") or library.startswith(prefix + "_"):
            if org not in repo and org not in maintainer and prefix not in maintainer:
                matched_prefix, matched_org = prefix, org
                break

    if not matched_prefix:
        return {"severity": "pass",
                "label":    "No namespace squatting",
                "details":  "Package name does not impersonate a known organisation"}

    return {"severity": "high",
            "label":    f"Namespace squatting? ('{matched_prefix}-')",
            "details":  (f"Name starts with '{matched_prefix}-' but repo/maintainer "
                         f"doesn't belong to {matched_org} — possible impersonation of official SDK")}


# ── Security Checks — JSON node ───────────────────────────────────────────────
# Each check is a self-contained, JSON-serialisable record (no Python function
# refs here). To add a new check:
#   1. Append a new dict entry to _SECURITY_CHECKS_JSON below
#   2. Write   def _check_<name>(row, context) -> dict:   anywhere in this file
#   3. Add one line   "C6": _check_<name>   to _CHECK_FN_MAP
# The UI, audit loop, and Raised Queries auto-pick it up — no other changes needed.
_SECURITY_CHECKS_JSON = [
    {
        "id":          "C1",
        "json_id":     "MAINTAINER_ACCOUNT_AGE",
        "category":    "maintainer",
        "name":        "Maintainer Account Age",
        "description": "Flags packages whose primary GitHub maintainer account is "
                       "suspiciously new — a common vector for typosquatting and "
                       "supply-chain hijacks (e.g. event-stream 2018, XZ Utils 2024).",
        "enabled":     True,
        "severity_thresholds": {
            "critical": {"days_lt": 30,  "label": "Account only {days}d old",
                         "details": "GitHub account {handle} is less than 30 days old — high risk of namespace squat / hijack"},
            "high":     {"days_lt": 180, "label": "New account ({days}d)",
                         "details": "GitHub account {handle} is less than 6 months old"},
            "medium":   {"days_lt": 730, "label": "Account {years}y old",
                         "details": "GitHub account {handle} is between 6 months and 2 years old"},
            "pass":     {"label": "{years}y old",
                         "details": "GitHub account {handle} is mature ({days} days old)"},
        },
    },
    {
        "id":          "C2",
        "json_id":     "ABANDONED_PACKAGE",
        "category":    "maintenance",
        "name":        "Abandoned Package",
        "description": "Flags packages with no published updates in 6 months (aging) "
                       "or 2+ years (abandoned). Stale packages receive no security patches.",
        "enabled":     True,
        "severity_thresholds": {
            "critical": {"status": "Abandoned", "label": "Abandoned (2y+ stale)",
                         "details": "No maintenance in over 2 years"},
            "medium":   {"status": "Aging",     "label": "Aging (6m–2y)",
                         "details": "Slowing maintenance"},
            "low":      {"status": "Unknown",   "label": "Status unknown",
                         "details": "Registry did not provide a last-updated date"},
            "pass":     {"label": "Active",
                         "details": "Updated within the last 6 months"},
        },
    },
    {
        "id":          "C3",
        "json_id":     "KNOWN_CVE",
        "category":    "vulnerability",
        "name":        "Known CVE",
        "description": "Flags packages with registered CVE or GHSA advisories sourced "
                       "from OSV.dev, GitHub Advisory DB, and NVD.",
        "enabled":     True,
        "severity_thresholds": {
            "critical": {"cve_count_gte": 3, "label": "{count}+ CVEs",
                         "details": "Multiple known vulnerabilities: {cves}"},
            "high":     {"cve_count_gte": 1, "label": "CVE found",
                         "details": "Known vulnerability: {cves}"},
            "pass":     {"label": "No known CVEs",
                         "details": "OSV.dev + GitHub Advisory DB returned no vulnerabilities"},
        },
    },
    {
        "id":          "C4",
        "json_id":     "BUS_FACTOR",
        "category":    "ownership",
        "name":        "Bus Factor",
        "description": "Flags packages with ≤5 maintainers and high download counts — "
                       "a supply-chain single point of failure (left-pad, event-stream pattern).",
        "enabled":     True,
        "severity_thresholds": {
            "critical": {"condition": "bus_factor_and_downloads_gte_10m",
                         "label": "Bus Factor: ≤5 maint + 10M+ dl",
                         "details": "≤5 maintainers for a package with {downloads} downloads"},
            "high":     {"condition": "bus_factor",
                         "label": "Bus Factor (≤5 maintainers)",
                         "details": "≤5 maintainers + {downloads} downloads"},
            "medium":   {"condition": "small_team",
                         "label": "Small team (moderate dl)",
                         "details": "≤5 maintainers with {downloads} downloads"},
            "pass":     {"label": "Healthy maintainer count",
                         "details": "More than 5 maintainers with publish rights"},
        },
    },
    {
        "id":          "C5",
        "json_id":     "RESTRICTED_ORIGIN",
        "category":    "geopolitical",
        "name":        "Restricted Origin",
        "description": "Flags packages whose primary maintainer is located in a country "
                       "classified as Restricted or Caution based on sanctions and "
                       "export-control frameworks.",
        "enabled":     True,
        "severity_thresholds": {
            "critical": {"tier": "Restricted", "label": "Restricted ({country})",
                         "details": "Maintainer in restricted country {country} — sanctions / export-control concern"},
            "medium":   {"tier": "Caution",    "label": "Caution ({country})",
                         "details": "Maintainer in caution-tier country {country}"},
            "low":      {"tier": "Unknown",    "label": "Country unverified",
                         "details": "Country could not be resolved — informational only"},
            "pass":     {"label": "Trusted ({country})",
                         "details": "Maintainer in trusted country {country}"},
        },
    },
    {
        "id":          "C6",
        "json_id":     "MAINTAINER_COUNT",
        "category":    "ownership",
        "name":        "GitHub Maintainer Count",
        "description": "Fetches the exact number of people with write access to the "
                       "GitHub repository (collaborators API, falls back to contributors "
                       "when token permissions are insufficient).",
        "enabled":     True,
        "severity_thresholds": {},
    },
    {
        "id":          "C7",
        "json_id":     "TYPOSQUATTING",
        "category":    "identity",
        "name":        "Typosquatting Detection",
        "description": "Checks if the package name is a near-duplicate (edit distance ≤ 2) "
                       "of a known popular package — a classic supply-chain attack vector "
                       "where attackers register slightly misspelled package names to "
                       "intercept accidental installs.",
        "enabled":     True,
        "severity_thresholds": {
            "critical": {"edit_distance": 1, "label": "Typosquat? (1 char from '{match}')",
                         "details": "1 edit away from popular package — very likely typosquatting"},
            "high":     {"edit_distance": 2, "label": "Suspicious (2 edits from '{match}')",
                         "details": "2 edits away from popular package — review carefully"},
            "medium":   {"edit_distance": 3, "label": "Similar name to '{match}'",
                         "details": "Some name similarity — low confidence, informational"},
            "pass":     {"label": "No typosquat match",
                         "details": "Name does not closely match any known popular package"},
        },
    },
    {
        "id":          "C8",
        "json_id":     "HOMOGLYPH_ATTACK",
        "category":    "identity",
        "name":        "Homoglyph Attack Detection",
        "description": "Detects non-ASCII lookalike characters in the package name "
                       "(e.g. Cyrillic 'е' instead of Latin 'e'). Renders identically "
                       "in terminal but resolves to a completely different package.",
        "enabled":     True,
        "severity_thresholds": {
            "critical": {"label": "Homoglyph chars in name",
                         "details": "Non-ASCII lookalike characters found — homoglyph impersonation"},
            "pass":     {"label": "Name clean",
                         "details": "Package name contains only standard ASCII characters"},
        },
    },
    {
        "id":          "C9",
        "json_id":     "PHANTOM_REPO",
        "category":    "integrity",
        "name":        "Phantom Repository",
        "description": "Checks whether the linked GitHub repository actually exists. "
                       "Attackers list deleted or nonexistent repo URLs to appear "
                       "legitimate — a 404 response exposes this credibility fraud.",
        "enabled":     True,
        "severity_thresholds": {
            "critical": {"label": "Phantom repo (404)",
                         "details": "Claimed repository returns 404 — does not exist"},
            "medium":   {"label": "No repo linked",
                         "details": "Package has no source repository — zero transparency"},
            "pass":     {"label": "Repo exists",
                         "details": "Repository URL is reachable"},
        },
    },
    {
        "id":          "C10",
        "json_id":     "NAMESPACE_SQUATTING",
        "category":    "identity",
        "name":        "Namespace Squatting",
        "description": "Flags packages that use a well-known organisation prefix "
                       "(aws-*, google-*, stripe-*) but whose maintainer/repo does "
                       "not belong to that organisation — impersonating official SDKs.",
        "enabled":     True,
        "severity_thresholds": {
            "high": {"label": "Namespace squatting?",
                     "details": "Name uses org prefix but repo/maintainer doesn't match"},
            "pass": {"label": "No namespace squatting",
                     "details": "Package name does not impersonate a known organisation"},
        },
    },
]

# ── Check function map — one line per check ────────────────────────────────────
# Only bridge between the JSON node above and the Python logic below.
# Add  "C6": _check_mycheck  here when you add a new check.
_CHECK_FN_MAP: dict = {
    "C1": _check_account_age,
    "C2": _check_abandoned,
    "C3": _check_cve,
    "C4": _check_bus_factor,
    "C5": _check_country,
    "C6": _check_maintainer_count,
    "C7": _check_typosquatting,
    "C8": _check_homoglyph,
    "C9": _check_phantom_repo,
    "C10": _check_namespace_squatting,
}

# ── Rebuild _SECURITY_CHECKS for backward-compat with all existing references ──
# All callers use c["id"], c["name"], c["fn"] — structure is unchanged.
# Disabled checks (enabled=False) are automatically excluded.
_SECURITY_CHECKS = [
    {**chk, "fn": _CHECK_FN_MAP[chk["id"]]}
    for chk in _SECURITY_CHECKS_JSON
    if chk.get("enabled", True) and chk["id"] in _CHECK_FN_MAP
]

def _run_security_checks(row, token=""):
    """Run every registered check on a row. Returns list of {id, name, ...result}."""
    ctx = {"token": token}
    out = []
    for chk in _SECURITY_CHECKS:
        try:
            r = chk["fn"](row, ctx)
        except Exception as _e:
            r = {"severity": "low",
                 "label":    "🟢 Check error",
                 "details":  f"{type(_e).__name__}: {_e}"}
        out.append({"id": chk["id"], "name": chk["name"], **r})
    return out

# ── Per-check lookup map and weights ──────────────────────────────────────────
_CHECK_META   = {chk["id"]: chk for chk in _SECURITY_CHECKS_JSON}
# Max risk contribution per check (mirrors _risk_score() dimension weights)
_CHECK_WEIGHT = {"C1": 10, "C2": 30, "C3": 25, "C4": 15, "C5": 20, "C6": 5, "C7": 20, "C8": 25, "C9": 20, "C10": 15}
# Severity → human status label
_SEV_TO_STATUS = {
    "pass": "pass", "low": "pass",
    "medium": "warning", "high": "fail", "critical": "fail",
}
# Severity → fraction of check weight applied as risk_score
_SEV_FRAC = {"pass": 0.0, "low": 0.0, "medium": 0.5, "high": 0.8, "critical": 1.0}


def _extract_evidence(check_id: str, result: dict, row: dict) -> dict:
    """Build a structured evidence dict from row data for a given check ID."""
    label = result.get("label", "")

    if check_id == "C1":
        m = re.search(r'(\d+\.?\d*)y', label)
        return {"account_age_years": float(m.group(1)) if m else None}

    if check_id == "C2":
        lu = str(row.get("Last Updated", "—") or "—")
        months = None
        try:
            import datetime as _dt
            dt = _dt.datetime.strptime(lu[:7], "%Y-%m")
            months = int((_dt.datetime.utcnow() - dt).days / 30)
        except Exception:
            pass
        return {"last_updated": lu, "months_since_update": months}

    if check_id == "C3":
        raw = str(row.get("CVEs", "") or "")
        if raw in ("None", "—", "", "Timeout", "Error"):
            return {"cve_count": 0, "cves": []}
        lst = [c.strip() for c in raw.split(",") if c.strip().startswith(("CVE", "GHSA"))]
        return {"cve_count": len(lst), "cves": lst[:10]}

    if check_id == "C4":
        maint = str(row.get("Maintainer", "") or "")
        _m = re.search(r'\+\s*(\d+)', maint)
        cnt = (1 + int(_m.group(1))) if _m else (1 if maint.strip() and maint not in ("—", "") else 0)
        dl_raw = row.get("Downloads", "—")
        dl_int = _parse_download_num(dl_raw) if dl_raw not in ("—", "N/A", "", None) else None
        return {"maintainer_count": cnt, "downloads": dl_int}

    if check_id == "C5":
        country  = str(row.get("Country", "—") or "—")
        tier_raw = row.get("Country Tier", "") or _country_tier(country)
        tier     = tier_raw.split(" ", 1)[-1].split("(")[0].strip() if tier_raw else "Unknown"
        return {"country": country, "tier": tier}

    if check_id == "C7":
        library = str(row.get("Library", "") or "").strip().lower()
        m = re.search(r"from '([^']+)'", result.get("details", ""))
        closest = m.group(1) if m else None
        dist_m  = re.search(r"(\d+) edit", result.get("details", ""))
        dist    = int(dist_m.group(1)) if dist_m else None
        return {"package_name": library, "closest_match": closest, "edit_distance": dist}

    if check_id == "C8":
        library = str(row.get("Library", "") or "").strip()
        bad = [c for c in library if ord(c) > 127]
        return {"package_name": library, "non_ascii_chars": bad}

    if check_id == "C9":
        repo = str(row.get("Repo", "") or "").strip()
        m = re.search(r"\((\d+)\)", result.get("label", ""))
        code = int(m.group(1)) if m else None
        return {"repo_url": repo, "http_status": code}

    if check_id == "C10":
        library = str(row.get("Library", "") or "").strip().lower()
        m = re.search(r"'([^']+)-'", result.get("details", ""))
        prefix = m.group(1) if m else None
        return {"package_name": library, "matched_prefix": prefix}

    return {}


def _calc_confidence(row: dict) -> float:
    """Confidence 0–1: fraction of key data fields that are populated."""
    fields = ["CVEs", "Country", "Maintainer", "Last Updated", "License", "Repo"]
    blanks = {"—", "N/A", "", None, "Unknown", "❓ Unknown"}
    filled = sum(1 for f in fields if str(row.get(f, "")).strip() not in blanks)
    return round(filled / len(fields), 2)


def _fix_encoding(s: str) -> str:
    """Fix double-encoded UTF-8 strings (Mojibake).

    If a string was UTF-8 bytes misread as Latin-1 (common with
    registry API responses), re-encoding as Latin-1 gives back the
    original bytes, and decoding as UTF-8 restores the correct text.
    Falls back to the original string if conversion fails.
    """
    if not s:
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def _split_maintainer(maintainer_str: str):
    """Split a maintainer string into (maintainer_type, maintainer_name).

    Examples:
      "Org * facebook +2"  -> ("org", "facebook")
      "User * ken wheeler" -> ("user", "ken wheeler")
      "someuser"           -> ("unknown", "someuser")

    Returns a 2-tuple: (maintainer_type, maintainer_name)
    maintainer_type: "org" | "user" | "unknown"
    maintainer_name: bare name without type prefix or "+N" suffix.
    """
    s = _fix_encoding(str(maintainer_str or "")).strip()
    if not s or s in ("—", ""):
        return "unknown", ""

    middle_dot = "·"  # U+00B7 MIDDLE DOT (used as separator)

    if s.startswith("Org"):
        mtype = "org"
        name  = s.split(middle_dot, 1)[1].strip() if middle_dot in s else s[3:].strip()
    elif s.startswith("User"):
        mtype = "user"
        name  = s.split(middle_dot, 1)[1].strip() if middle_dot in s else s[4:].strip()
    else:
        mtype = "unknown"
        name  = s

    # Strip "+N more" suffix
    name = re.sub(r"\s*\+\d+.*$", "", name).strip()
    return mtype, name

def _build_raised_queries(audit_rows: list) -> list:
    """Build rich, structured Raised Query records for every package with ≥1 failed check.

    Each record contains nested library, overall_risk, checks (all 5), and metadata sections.
    audit_rows — list of dicts from the Tab-2 audit loop (must include _results, _row_data).
    """
    queries = []
    seq = 0   # sequential counter — only incremented for packages that raise a query
    for row in audit_rows:
        results  = row.get("_results", [])
        row_data = row.get("_row_data", row)   # full row dict

        # Only raise a query when at least one check is medium/high/critical
        has_issue = any(
            r.get("severity", "pass") not in ("pass", "low") for r in results
        )
        if not has_issue:
            continue

        seq += 1   # gap-free: only counted when we actually emit a query

        # Worst overall severity
        worst     = max(results, key=lambda r: _SEV_RANK.get(r.get("severity", "pass"), 0))
        worst_sev = worst.get("severity", "pass")

        # Overall risk score + band
        try:
            score    = _risk_score(row_data)
            band_raw = _risk_band(score)
            band     = re.sub(r'^[^\x00-\x7F]+\s*', '', band_raw).strip()
        except Exception:
            score, band = None, "unknown"

        # Confidence based on data completeness
        confidence = _calc_confidence(row_data)

        # Per-check output — ALL 5 checks included (pass + fail)
        checks_out = []
        for chk, result in zip(_SECURITY_CHECKS, results):
            cid      = chk["id"]
            meta     = _CHECK_META.get(cid, {})
            sev      = result.get("severity", "pass")
            weight   = _CHECK_WEIGHT.get(cid, 10)
            rscore   = int(weight * _SEV_FRAC.get(sev, 0.0))
            evidence = _extract_evidence(cid, result, row_data)
            # Reason: strip all non-ASCII (emojis, symbols) from details string
            reason = re.sub(r'[^\x00-\x7F]+', '',
                            result.get("details", "")).strip(" —·—")
            checks_out.append({
                "id":         meta.get("json_id", cid),
                "category":   meta.get("category", "general"),
                "severity":   sev,
                "status":     _SEV_TO_STATUS.get(sev, "warning"),
                "title":      chk["name"],
                "evidence":   evidence,
                "reason":     reason,
                "risk_score": rscore,
            })

        # Dynamic sources list based on registry
        registry = row.get("Registry", "")
        sources  = ["GitHub", "OSV"]
        if "PyPI"    in registry: sources.append("PyPI")
        if "npm"     in registry.lower(): sources.append("NPM")
        if "Maven"   in registry: sources.append("Maven")
        if "NuGet"   in registry: sources.append("NuGet")
        if "Crates"  in registry: sources.append("Crates.io")
        if "Docker"  in registry: sources.append("Docker Hub")
        if "Hugging" in registry: sources.append("HuggingFace")
        sources.append("NVD")

        # Split maintainer string into type + name
        raw_maint   = _fix_encoding(str(row_data.get("Maintainer", "") or ""))
        maint_type, maint_name = _split_maintainer(raw_maint)

        # Downloads as integer
        dl_raw = row_data.get("Downloads", "—")
        dl_int = _parse_download_num(dl_raw) if dl_raw not in ("—", "N/A", "", None) else None

        # Description — fix encoding
        description = _fix_encoding(str(row_data.get("Description", "") or "—"))

        queries.append({
            "query_id": f"RQ-{seq:03d}",
            "library": {
                "name":             row.get("Library", "—"),
                "registry":         row.get("Registry", "—"),
                "version":          row.get("Version", "N/A"),
                "description":      description,
                "license":          row_data.get("License", "—"),
                "downloads":        dl_int,
                "repo":             row_data.get("Repo", "N/A"),
                "maintainer_type":  maint_type,
                "maintainer_name":  maint_name,
            },
            "overall_risk": {
                "score":                score,
                "band":                 band,
                "worst_check_severity": worst_sev,
                "confidence":           confidence,
            },
            "checks": checks_out,
            "metadata": {
                "engine_version": "2.0.0",
                "sources":        sources,
            },
        })
    return queries


def _build_supply_chain_json(audit_rows: list) -> list:
    """Same rich JSON schema as _build_raised_queries but includes ALL packages
    (pass and fail alike). Used for the Supply Chain JSON export download."""
    records = []
    for row in audit_rows:
        results  = row.get("_results", [])
        row_data = row.get("_row_data", row)

        worst     = max(results, key=lambda r: _SEV_RANK.get(r.get("severity","pass"), 0),
                        default={"severity": "pass"})
        worst_sev = worst.get("severity", "pass")

        try:
            score    = _risk_score(row_data)
            band_raw = _risk_band(score)
            band     = re.sub(r'^[^\x00-\x7F]+\s*', '', band_raw).strip()
        except Exception:
            score, band = None, "unknown"

        confidence = _calc_confidence(row_data)

        checks_out = []
        for chk, result in zip(_SECURITY_CHECKS, results):
            cid      = chk["id"]
            meta     = _CHECK_META.get(cid, {})
            sev      = result.get("severity", "pass")
            weight   = _CHECK_WEIGHT.get(cid, 10)
            rscore   = int(weight * _SEV_FRAC.get(sev, 0.0))
            evidence = _extract_evidence(cid, result, row_data)
            reason   = re.sub(r'[^\x00-\x7F]+', '',
                              result.get("details", "")).strip(" —·—")
            checks_out.append({
                "id":         meta.get("json_id", cid),
                "category":   meta.get("category", "general"),
                "severity":   sev,
                "status":     _SEV_TO_STATUS.get(sev, "warning"),
                "title":      chk["name"],
                "evidence":   evidence,
                "reason":     reason,
                "risk_score": rscore,
            })

        registry = row.get("Registry", "")
        sources  = ["GitHub", "OSV"]
        if "PyPI"    in registry: sources.append("PyPI")
        if "npm"     in registry.lower(): sources.append("NPM")
        if "Maven"   in registry: sources.append("Maven")
        if "NuGet"   in registry: sources.append("NuGet")
        if "Crates"  in registry: sources.append("Crates.io")
        if "Docker"  in registry: sources.append("Docker Hub")
        if "Hugging" in registry: sources.append("HuggingFace")
        sources.append("NVD")

        # Split maintainer + fix encoding + parse downloads as int
        raw_maint   = _fix_encoding(str(row_data.get("Maintainer", "") or ""))
        maint_type, maint_name = _split_maintainer(raw_maint)
        dl_raw  = row_data.get("Downloads", "—")
        dl_int  = _parse_download_num(dl_raw) if dl_raw not in ("—", "N/A", "", None) else None
        desc    = _fix_encoding(str(row_data.get("Description", "") or "—"))

        records.append({
            "library": {
                "name":            row.get("Library", "—"),
                "registry":        row.get("Registry", "—"),
                "version":         row.get("Version", "N/A"),
                "description":     desc,
                "license":         row_data.get("License", "—"),
                "downloads":       dl_int,
                "repo":            row_data.get("Repo", "N/A"),
                "maintainer_type": maint_type,
                "maintainer_name": maint_name,
            },
            "overall_risk": {
                "score":                score,
                "band":                 band,
                "worst_check_severity": worst_sev,
                "confidence":           confidence,
            },
            "checks": checks_out,
            "metadata": {
                "engine_version": "2.0.0",
                "sources":        sources,
            },
        })
    return records


def _aggregate_severity(check_results):
    """Worst-of aggregation: highest severity across all checks wins."""
    if not check_results:
        return "pass"
    worst = max(check_results, key=lambda r: _SEV_RANK.get(r.get("severity","pass"), 0))
    return worst.get("severity", "pass")

def _severity_badge(severity):
    """Render a severity as a colored badge string for tables."""
    return f"{_SEV_EMOJI.get(severity,'⚪')} {_SEV_LABEL.get(severity,'—')}"

def _no_source_flag(repo: str) -> str:
    """Flag packages with no source repository — zero transparency = red flag."""
    if not repo or str(repo).strip() in ("N/A", "—", "", "None", "null"):
        return "🚨 No Source"
    return "✅"

def _parse_download_num(s) -> int:
    """Convert formatted download strings ('452.4M', '16K') back to integers."""
    if not s or s in ("—", "N/A", "", None):
        return 0
    s = str(s).strip().upper().replace(",", "")
    mult = 1
    if s.endswith("B"):   mult = 1_000_000_000; s = s[:-1]
    elif s.endswith("M"): mult = 1_000_000;     s = s[:-1]
    elif s.endswith("K"): mult = 1_000;         s = s[:-1]
    try:
        return int(float(s) * mult)
    except (ValueError, TypeError):
        return 0

def _single_maintainer_risk(maintainer: str, downloads) -> str:
    """
    Flag packages with ≤5 maintainers AND ≥1M downloads.
    Classic supply-chain risk pattern (cf. left-pad incident).
    Maintainer strings encode count as '+N' suffix, e.g. 'username +3' = 4 total.
    """
    dl = _parse_download_num(downloads)
    s  = str(maintainer or "")

    # Parse total maintainer count from '+N' suffix
    _m = re.search(r'\+\s*(\d+)', s)
    count = (1 + int(_m.group(1))) if _m else (1 if s.strip() and s not in ("—", "") else 0)

    if 0 < count <= 5 and dl >= 1_000_000:
        return "⚠️ Bus Factor"   # critical single point of failure
    if 0 < count <= 5 and dl >= 100_000:
        return "ℹ️ Solo"          # small team but moderate risk
    return ""

def _risk_score(row, rules=None) -> int:
    """
    Composite risk score 0-100 (higher = safer).
    Combines status, license, CVE, country, source, and maintainer signals.

    Breakdown (max 100):
      • Status     (30) — Active=30, Aging=15, Unknown=10, Abandoned=0
      • License    (20) — Safe=20, Copyleft/Other=10, Missing=0
      • CVEs       (20) — None=20, has CVE=0
      • Country    (15) — Trusted=15, Caution=10, Unrated=8, Restricted=0
      • Source     (10) — has repo=10, none=0
      • Maintainer (5)  — multi or low-dl solo=5, Bus Factor=0

    Optional: pass `rules` (loaded via _load_custom_rules) to apply user-defined
    score deductions for matched rules:
      • critical = -50  • high = -25  • medium = -10  • low = -3
    Score is clamped to [0, 100] so multiple matches never break the band logic.
    """
    score = 0
    # Status
    s = row.get("Status", "")
    if "Active" in s:        score += 30
    elif "Aging" in s:       score += 15
    elif "Unknown" in s:     score += 10
    # License risk
    lr = row.get("License Risk", "") or _license_risk(row.get("License", ""))
    if "Safe" in lr:                  score += 20
    elif "Copyleft" in lr or "Other" in lr: score += 10
    # CVE — also treat Timeout/Error/N/A as no confirmed CVEs for scoring purposes
    cves = str(row.get("CVEs", "") or "")
    if cves in ("None", "—", "", "Timeout", "Error", "N/A"):     score += 20
    # Country tier (only if country has been resolved)
    ct = row.get("Country Tier", "") or _country_tier(row.get("Country", ""))
    if "Trusted" in ct:    score += 15
    elif "Caution" in ct:  score += 10
    elif "Unrated" in ct:  score += 8
    # Source repo
    src = row.get("Repo", "")
    if src and str(src).strip() not in ("N/A", "—", "", "None"):
        score += 10
    # Maintainer / bus factor
    sm = row.get("Single Maintainer", "") or _single_maintainer_risk(
            row.get("Maintainer", ""), row.get("Downloads", ""))
    if "Bus Factor" not in sm:
        score += 5
    # ── Custom rules penalty (Phase 2: user-uploaded blocklist) ────────────
    if rules:
        for m in _custom_rule_match(row, rules):
            score -= _SEV_PENALTY.get(m["severity"], 0)
    return max(0, min(score, 100))

def _risk_band(score: int) -> str:
    """Convert a 0-100 risk score into a band emoji + label."""
    if score >= 80: return f"Low ({score})"
    if score >= 60: return f"Medium ({score})"
    if score >= 40: return f"High ({score})"
    return f"Critical ({score})"

# ── Custom Rules / Blocklist (user-uploaded CSV/JSON) ─────────────────────────
# Lets users define their own rules (e.g. banned packages, restricted licenses)
# that contribute to the existing 4-tier Risk classification via score deductions.
import csv as _csv_mod
import io as _io_mod
_VALID_FIELDS      = {"library","maintainer","country","license","registry","version"}
_VALID_MATCH_TYPES = {"exact","contains","regex"}
_VALID_SEVERITY    = {"low","medium","high","critical"}
_SEV_DEFAULT_EMOJI = {"low":"🟢","medium":"🟡","high":"🟠","critical":"🚨"}
_SEV_PENALTY       = {"low":3,"medium":10,"high":25,"critical":50}
# Rule field name → DataFrame column
_FIELD_TO_COL = {
    "library":"Library", "maintainer":"Maintainer", "country":"Country",
    "license":"License", "registry":"Registry",     "version":"Version",
}

def _load_custom_rules(uploaded_file):
    """
    Parse a Streamlit UploadedFile (CSV or JSON) into a normalised rule list.
    Returns (rules, warnings). Malformed rows are skipped with a per-row warning;
    regex rules that fail to compile are also dropped.

    File format is auto-detected from the filename extension (.json vs .csv).
    Bare JSON arrays and {"rules": [...]} wrappers are both accepted.
    """
    if uploaded_file is None:
        return [], []
    try:
        raw = uploaded_file.getvalue().decode("utf-8", errors="replace")
    except Exception as _e:
        return [], [f"Decode error: {_e}"]
    name = (getattr(uploaded_file, "name", "") or "").lower()
    rows = []
    warnings = []

    try:
        if name.endswith(".json"):
            obj = json.loads(raw)
            rows = obj.get("rules", obj) if isinstance(obj, dict) else obj
            if not isinstance(rows, list):
                return [], ["JSON must be an array or {\"rules\": [...]} object"]
        else:
            rows = list(_csv_mod.DictReader(_io_mod.StringIO(raw)))
    except Exception as _e:
        return [], [f"Parse error: {_e}"]

    out = []
    for i, r in enumerate(rows, start=1):
        if not isinstance(r, dict):
            warnings.append(f"Row {i}: not an object — skipped")
            continue
        rid    = str(r.get("rule_id","") or f"R{i:03d}").strip()
        field  = str(r.get("field","") or "").strip().lower()
        mtype  = str(r.get("match_type","") or "contains").strip().lower()
        patt   = str(r.get("pattern","") or "").strip()
        sev    = str(r.get("severity","") or "").strip().lower()

        if field not in _VALID_FIELDS:
            warnings.append(f"Row {i} ({rid}): bad field '{field}' — skipped"); continue
        if mtype not in _VALID_MATCH_TYPES:
            warnings.append(f"Row {i} ({rid}): bad match_type '{mtype}' — skipped"); continue
        if sev not in _VALID_SEVERITY:
            warnings.append(f"Row {i} ({rid}): bad severity '{sev}' — skipped"); continue
        if not patt:
            warnings.append(f"Row {i} ({rid}): empty pattern — skipped"); continue

        compiled = None
        if mtype == "regex":
            try:
                compiled = re.compile(patt, re.IGNORECASE)
            except re.error as _re_err:
                warnings.append(f"Row {i} ({rid}): regex error — {_re_err}"); continue

        out.append({
            "rule_id":    rid,
            "name":       str(r.get("name", rid) or rid).strip() or rid,
            "field":      field,
            "match_type": mtype,
            "pattern":    patt,
            "compiled":   compiled,
            "severity":   sev,
            "emoji":      str(r.get("emoji","") or _SEV_DEFAULT_EMOJI[sev]),
        })
    return out, warnings

def _custom_rule_match(row, rules):
    """
    Return the list of rule dicts that match this row.
    Pure function — no side effects. Mirrors _single_maintainer_risk pattern.
    """
    if not rules:
        return []
    matched = []
    for rule in rules:
        col = _FIELD_TO_COL.get(rule["field"])
        if not col:
            continue
        val = str(row.get(col, "") or "")
        if not val or val.strip() in ("—","N/A","None"):
            continue

        hit = False
        if rule["match_type"] == "exact":
            hit = val.strip().lower() == rule["pattern"].lower()
        elif rule["match_type"] == "contains":
            hit = rule["pattern"].lower() in val.lower()
        elif rule["match_type"] == "regex" and rule["compiled"] is not None:
            hit = bool(rule["compiled"].search(val))

        if hit:
            matched.append(rule)
    return matched

def _custom_flags_display(matched):
    """Render matched rules into the 'Custom Flags' column string."""
    if not matched:
        return ""
    return ", ".join(f"{m['emoji']} {m['name']}" for m in matched)

# ── Maintainer helpers ─────────────────────────────────────────────────────────
_ORG_TOKENS = {
    "inc","llc","ltd","corp","gmbh","foundation","project","team","group",
    "community","labs","software","systems","technologies","solutions",
    "organization","collective","network","alliance","consortium","institute",
}

def _m_org(name):
    """Format as Organisation."""
    return f"Org · {name}" if name and name != "—" else "Org"

def _m_user(name):
    """Format as Individual."""
    return f"User · {name}" if name and name != "—" else "User"

def _m_auto(name):
    """Best-guess: Org or User based on the name string."""
    if not name or name in ("—","N/A",""): return "—"
    name = str(name).strip()
    # Multiple authors (comma list) → team / org
    if "," in name:
        first = name.split(",")[0].strip()
        rest  = name.count(",")
        return f"Org · {first}" + (f" +{rest}" if rest else "")
    words = name.lower().split()
    if any(w in _ORG_TOKENS for w in words):
        return _m_org(name)
    return _m_user(name)

# ── Search relevance guard ────────────────────────────────────────────────────
_STOP = {"the","a","an","and","or","of","for","in","to","is","are","by","from",
         "with","on","at","as","its","it","this","that","be","was","were"}

def _name_clean(s: str) -> str:
    return (s.lower()
             .replace("-","").replace("_","").replace(":","")
             .replace("/","").replace(".","").replace(" ",""))

def _search_tokens(query: str) -> list:
    # Keep tokens ≥ 2 chars (so "UI", "JS", "CSS" survive — they're critical
    # disambiguators: "Radix UI" must require "ui", not just "radix").
    return [t.lower() for t in query.split()
            if len(t) >= 2 and t.lower() not in _STOP]

def _filter_search(data: list, query: str) -> list:
    """
    Precision filter for search-mode results.

    Two-layer rules:
      1. ALL significant query tokens must appear in the cleaned package name
         (e.g. "Radix UI" → must contain BOTH 'radix' AND 'ui').
      2. Name's first component (before first .  -  _  /  :) must START with
         the primary query token. This rejects compound names like
         "MahApps.Metro.IconPacks.RadixIcons" for query "Radix UI" — the
         first component "MahApps" doesn't start with "radix" → REJECT.
      3. Return at most the single highest-scoring match.
    """
    if not data:
        return []
    tokens = _search_tokens(query)
    if not tokens:
        return data[:1]
    primary = tokens[0]            # first significant query token

    def score(row):
        c = _name_clean(row.get("Library", ""))
        return sum(1 for t in tokens if t in c)

    def first_component_matches(row):
        """Reject compound names whose first component is unrelated."""
        name = row.get("Library", "").lower()
        # Strip @scope/ prefix (npm scoped packages like @radix-ui/themes)
        if name.startswith("@"):
            name = name.split("/", 1)[-1] if "/" in name else name[1:]
        # First component: chars before first separator (/ : . - _ space)
        first_seg = re.split(r"[/.:\-_ ]", name, maxsplit=1)[0]
        first_seg_clean = re.sub(r"[^a-z0-9]", "", first_seg)
        full_clean      = _name_clean(name)
        if not first_seg_clean:
            return False
        # Accept if either:
        #   • full cleaned name starts with primary token
        #   • first component starts with primary
        #   • primary starts with first component (handles shorter-name cases)
        return (full_clean.startswith(primary) or
                first_seg_clean.startswith(primary) or
                (primary.startswith(first_seg_clean) and len(first_seg_clean) >= 3))

    # Pass 1 — strict: all tokens present AND first component matches primary
    matched = [r for r in data
               if score(r) >= len(tokens) and first_component_matches(r)]

    # Pass 2 — slightly looser: all tokens present (drop first-component rule)
    # Only used if strict pass returns nothing, to avoid empty-result cliffs.
    if not matched:
        matched = [r for r in data if score(r) >= len(tokens)
                   and first_component_matches(r)]

    if not matched:
        return []   # nothing truly relevant — show nothing rather than noise

    return sorted(matched, key=score, reverse=True)[:1]

# ── OSV CVE check (returns CVE string only) ────────────────────────────────────
OSV_ECO = {"PyPI","npm","RubyGems","crates.io","Packagist","Maven","NuGet","Go"}

def check_vuln(pkg, eco):
    if eco not in OSV_ECO: return "—"
    try:
        r = requests.post("https://api.osv.dev/v1/query",
                          json={"package":{"name":pkg,"ecosystem":eco}}, timeout=6)
        if r.status_code != 200: return "—"
        vulns = r.json().get("vulns",[])
        if not vulns: return "None"
        cves = list(dict.fromkeys([
            next((a for a in (x.get("aliases") or []) if a.startswith("CVE")),
                 x.get("id","?"))
            for x in vulns
        ]))
        return ", ".join(cves[:4])
    except: return "—"

def _has_cve(cve_str):
    return cve_str not in ("—","None","","Timeout","Error") and bool(cve_str)

# ── Live CVE feed — detailed data for the Profile tab ─────────────────────────
# Registry display name → OSV ecosystem identifier
_REG_TO_OSV_ECO = {
    "NPM":           "npm",
    "PyPI":          "PyPI",
    "RubyGems":      "RubyGems",
    "Maven Central": "Maven",
    "NuGet":         "NuGet",
    "crates.io":     "crates.io",
    "Go Modules":    "Go",
    "Packagist":     "Packagist",
}

def _parse_osv_entry(v: dict) -> dict:
    """Convert a raw OSV vuln object into a normalised dict."""
    vid     = v.get("id", "")
    aliases = [a for a in (v.get("aliases") or []) if a.startswith("CVE")]
    cve_id  = aliases[0] if aliases else vid

    # Severity — prefer database_specific.severity (human-readable label)
    db_spec  = v.get("database_specific") or {}
    severity = (db_spec.get("severity") or "UNKNOWN").upper()

    # CVSS numeric score (some OSV entries expose it directly)
    cvss_score = None
    for sev in (v.get("severity") or []):
        try:
            cvss_score = float(sev.get("score", ""))
            break
        except (ValueError, TypeError):
            pass

    # Affected / fixed version ranges
    fixed_versions, vuln_versions = [], []
    for aff in (v.get("affected") or []):
        for rng in (aff.get("ranges") or []):
            for evt in (rng.get("events") or []):
                if "fixed" in evt:
                    fixed_versions.append(evt["fixed"])
                elif "introduced" in evt and evt["introduced"] != "0":
                    vuln_versions.append(f">= {evt['introduced']}")
        for ver in (aff.get("versions") or [])[:3]:
            if ver not in vuln_versions:
                vuln_versions.append(ver)

    # Up to 4 reference links
    refs = [{"type": ref.get("type","WEB"), "url": ref["url"]}
            for ref in (v.get("references") or [])[:4] if ref.get("url")]

    summary = v.get("summary","") or (v.get("details","") or "No description available.")[:200]

    return {
        "id":             vid,
        "cve_id":         cve_id,
        "aliases":        aliases,
        "summary":        summary,
        "severity":       severity,
        "cvss_score":     cvss_score,
        "fixed_versions": list(dict.fromkeys(fixed_versions))[:4],
        "vuln_versions":  list(dict.fromkeys(vuln_versions))[:4],
        "published":      (v.get("published","") or "")[:10],
        "modified":       (v.get("modified","") or "")[:10],
        "references":     refs,
        "osv_url":        f"https://osv.dev/vulnerability/{vid}",
        "source":         "OSV.dev",
    }


def _fetch_gh_repo_advisories(gh_path: str, token: str = None) -> list:
    """
    Fetch security advisories published directly against a GitHub repository.
    e.g. vercel/next.js → catches CVE-2026-44575, CVE-2026-45109 the moment
    Vercel/the reporter publishes the GHSA — days/weeks before NVD processes them.
    Endpoint: GET /repos/{owner}/{repo}/security-advisories (public, no token needed)
    """
    if not gh_path or "/" not in gh_path:
        return []

    results  = []
    headers  = {"Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        r = requests.get(
            f"https://api.github.com/repos/{gh_path}/security-advisories",
            params={"per_page": 30, "state": "published"},
            headers=headers,
            timeout=12)
        if r.status_code not in (200, 206):
            return []

        for adv in r.json():
            ghsa_id  = adv.get("ghsa_id", "")
            cve_id   = adv.get("cve_id", "") or ghsa_id
            severity = (adv.get("severity") or "unknown").upper()
            summary  = adv.get("summary", "") or adv.get("description", "")

            # CVSS score
            cvss_info  = adv.get("cvss") or {}
            cvss_score = cvss_info.get("score")

            # Fixed / affected versions from vulnerabilities array
            fixed_v, vuln_v = [], []
            for v in (adv.get("vulnerabilities") or []):
                pf = v.get("patched_versions", "") or ""
                av = v.get("vulnerable_versions", "") or ""
                if pf: fixed_v.append(pf)
                if av: vuln_v.append(av)

            # References
            refs = []
            if adv.get("html_url"):
                refs.append({"type": "ADVISORY", "url": adv["html_url"]})
            for ref in (adv.get("references") or [])[:3]:
                url = ref if isinstance(ref, str) else ref.get("url","")
                if url and url not in (adv.get("html_url",""),):
                    refs.append({"type": "WEB", "url": url})

            results.append({
                "id":             ghsa_id,
                "cve_id":         cve_id,
                "aliases":        ([cve_id] if cve_id.startswith("CVE") else []),
                "summary":        summary,
                "severity":       severity,
                "cvss_score":     cvss_score,
                "fixed_versions": fixed_v[:4],
                "vuln_versions":  vuln_v[:4],
                "published":      (adv.get("published_at","") or "")[:10],
                "modified":       (adv.get("updated_at","") or "")[:10],
                "references":     refs,
                "osv_url":        adv.get("html_url", ""),
                "source":         "GitHub Repo Advisory",
            })
    except Exception:
        pass

    return results


def _fetch_nvd_cves(pkg_name: str, eco: str) -> list:
    """
    Query NVD (National Vulnerability Database) API v2 for CVEs related to a package.
    NVD is the *primary* CVE registry — it often has fresh CVEs days/weeks before
    OSV or GitHub Advisory DB ingest them, making it essential for catching 0-days
    and newly disclosed vulnerabilities like CVE-2026-44575, CVE-2026-45109.
    """
    # Build search keyword variants
    # e.g. npm "next" → also try "next.js" since NVD descriptions say "Next.js"
    search_terms = [pkg_name]
    if eco == "npm" and not pkg_name.endswith(".js"):
        search_terms.append(f"{pkg_name}.js")
    elif eco == "PyPI":
        search_terms.append(f"{pkg_name} python")
    elif eco == "Maven":
        search_terms.append(f"{pkg_name} java")

    results   = []
    seen_ids  = set()

    for term in search_terms:
        try:
            r = requests.get(
                "https://services.nvd.nist.gov/rest/json/cves/2.0",
                params={
                    "keywordSearch":  term,
                    "resultsPerPage": 20,
                    "pubStartDate":   "2019-01-01T00:00:00.000",
                },
                timeout=15,
                headers={"User-Agent": "RegistryIntelligencePlatform/1.0"})

            if r.status_code == 429:
                break          # NVD rate-limited (5 req/30s without API key) — stop
            if r.status_code != 200:
                continue

            for item in r.json().get("vulnerabilities", []):
                cve_obj = item.get("cve", {})
                cve_id  = cve_obj.get("id", "")
                if not cve_id or cve_id in seen_ids:
                    continue

                # Relevance filter — description must mention the package name
                descs     = cve_obj.get("descriptions", [])
                desc_text = next((d["value"] for d in descs if d.get("lang") == "en"), "")
                pkg_norm  = pkg_name.lower().replace("-","").replace(".","")
                desc_norm = desc_text.lower().replace("-","").replace(".","")
                term_norm = term.lower().replace("-","").replace(".","")
                if pkg_norm not in desc_norm and term_norm not in desc_norm:
                    continue   # unrelated CVE — skip

                seen_ids.add(cve_id)

                # CVSS score + severity — prefer V3.1 → V3.0 → V2
                severity   = "UNKNOWN"
                cvss_score = None
                metrics    = cve_obj.get("metrics", {})
                for mkey in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
                    mlist = metrics.get(mkey, [])
                    if mlist:
                        cd         = mlist[0].get("cvssData", {})
                        cvss_score = cd.get("baseScore")
                        severity   = cd.get("baseSeverity", "UNKNOWN").upper()
                        break

                # References (up to 4)
                refs = [{"type": "WEB", "url": ref["url"]}
                        for ref in cve_obj.get("references", [])[:4]
                        if ref.get("url")]

                published = (cve_obj.get("published","") or "")[:10]
                modified  = (cve_obj.get("lastModified","") or "")[:10]

                results.append({
                    "id":             cve_id,
                    "cve_id":         cve_id,
                    "aliases":        [cve_id],
                    "summary":        (desc_text[:300] if desc_text
                                       else "No description available."),
                    "severity":       severity,
                    "cvss_score":     cvss_score,
                    "fixed_versions": [],   # NVD doesn't expose fix versions directly
                    "vuln_versions":  [],
                    "published":      published,
                    "modified":       modified,
                    "references":     refs,
                    "osv_url":        f"https://nvd.nist.gov/vuln/detail/{cve_id}",
                    "source":         "NVD",
                })
        except Exception:
            continue

    return results


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_live_cves(pkg_name: str, reg_name: str,
                    gh_path: str = None, token: str = None) -> list:
    """
    Fetch full CVE / advisory details for a package from 4 sources:
      1. OSV.dev               — broad ecosystem coverage
      2. GitHub Advisory DB    — ecosystem-wide advisories
      3. NVD                   — primary CVE database (fresh, official CVSS)
      4. GitHub Repo Advisories— repo-specific, published before NVD processes them
                                 (catches CVE-2026-44575, CVE-2026-45109, etc.)
    Results are deduplicated and sorted by severity then date.
    """
    eco = _REG_TO_OSV_ECO.get(reg_name)
    if not eco:
        return []

    results, seen_ids = [], set()

    # ── Source 1: OSV.dev ─────────────────────────────────────────────────────
    try:
        r = requests.post(
            "https://api.osv.dev/v1/query",
            json={"package": {"name": pkg_name, "ecosystem": eco}},
            timeout=12)
        if r.status_code == 200:
            for v in r.json().get("vulns", [])[:30]:
                entry = _parse_osv_entry(v)
                if entry["id"] not in seen_ids:
                    seen_ids.add(entry["id"])
                    results.append(entry)
    except Exception:
        pass

    # ── Source 2: GitHub Advisory Database ───────────────────────────────────
    try:
        r2 = requests.get(
            "https://api.github.com/advisories",
            params={"affects": f"{eco}/{pkg_name}", "per_page": 20},
            timeout=10,
            headers={"Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"})
        if r2.status_code == 200:
            for adv in r2.json():
                ghsa_id  = adv.get("ghsa_id", "")
                cve_id   = adv.get("cve_id", "") or ghsa_id
                severity = (adv.get("severity") or "unknown").upper()
                fixed_v  = []
                for vuln in (adv.get("vulnerabilities") or []):
                    pf = vuln.get("patched_versions", "") or ""
                    if pf: fixed_v.append(pf)
                cvss_info = adv.get("cvss") or {}
                entry = {
                    "id":             ghsa_id,
                    "cve_id":         cve_id,
                    "aliases":        [cve_id] if cve_id.startswith("CVE") else [],
                    "summary":        adv.get("summary", ""),
                    "severity":       severity,
                    "cvss_score":     cvss_info.get("score"),
                    "fixed_versions": fixed_v[:4],
                    "vuln_versions":  [],
                    "published":      (adv.get("published_at","") or "")[:10],
                    "modified":       (adv.get("updated_at","") or "")[:10],
                    "references":     ([{"type":"ADVISORY","url":adv["html_url"]}]
                                       if adv.get("html_url") else []),
                    "osv_url":        adv.get("html_url", ""),
                    "source":         "GitHub Advisory",
                }
                # Dedup: skip if same CVE already captured from OSV
                already = any(
                    e["cve_id"] == cve_id or e["id"] == ghsa_id
                    for e in results)
                if not already and ghsa_id not in seen_ids:
                    seen_ids.add(ghsa_id)
                    results.append(entry)
    except Exception:
        pass

    # ── Source 3: NVD (National Vulnerability Database) ──────────────────────
    # NVD is the authoritative primary registry — catches fresh CVEs (days/weeks)
    # before OSV or GitHub Advisory ingest them.
    # Specifically needed for: CVE-2026-44575, CVE-2026-45109, CVE-2025-30218, etc.
    try:
        _nvd_entries = _fetch_nvd_cves(pkg_name, eco)
        for entry in _nvd_entries:
            _nvd_cve = entry["cve_id"]
            # Dedup: skip if already captured from OSV or GitHub Advisory
            if _nvd_cve not in seen_ids and entry["id"] not in seen_ids:
                # Check against existing entries by CVE ID match
                already = any(e.get("cve_id") == _nvd_cve for e in results)
                if not already:
                    seen_ids.add(_nvd_cve)
                    results.append(entry)
            else:
                # Already have it — but if NVD has a better CVSS score, enrich it
                for existing in results:
                    if existing.get("cve_id") == _nvd_cve:
                        if existing.get("cvss_score") is None and entry.get("cvss_score"):
                            existing["cvss_score"] = entry["cvss_score"]
                        if existing.get("severity") in ("UNKNOWN", "") and entry.get("severity") not in ("UNKNOWN",""):
                            existing["severity"] = entry["severity"]
                        break
    except Exception:
        pass

    # ── Source 4: GitHub Repo Security Advisories ────────────────────────────
    # Published directly by the repo maintainers (e.g. vercel/next.js).
    # These appear IMMEDIATELY on disclosure — days/weeks before NVD processes them.
    # This is the fastest source for fresh CVEs like CVE-2026-44575, CVE-2026-45109.
    if gh_path:
        try:
            _repo_advs = _fetch_gh_repo_advisories(gh_path, token)
            for entry in _repo_advs:
                _rid = entry["cve_id"]
                already = any(e.get("cve_id") == _rid or e.get("id") == entry["id"]
                              for e in results)
                if not already and _rid not in seen_ids:
                    seen_ids.add(_rid)
                    seen_ids.add(entry["id"])
                    results.append(entry)
                else:
                    # Enrich existing entry with fix versions from repo advisory
                    for existing in results:
                        if existing.get("cve_id") == _rid:
                            if not existing.get("fixed_versions") and entry.get("fixed_versions"):
                                existing["fixed_versions"] = entry["fixed_versions"]
                            if not existing.get("vuln_versions") and entry.get("vuln_versions"):
                                existing["vuln_versions"] = entry["vuln_versions"]
                            if existing.get("cvss_score") is None and entry.get("cvss_score"):
                                existing["cvss_score"] = entry["cvss_score"]
                            break
        except Exception:
            pass

    # Sort: CRITICAL → HIGH → MEDIUM → LOW → UNKNOWN, then newest first within tier
    _sev_rank = {"CRITICAL":0,"HIGH":1,"MEDIUM":2,"LOW":3,"UNKNOWN":4,"":4}
    results.sort(key=lambda x: (
        _sev_rank.get(x.get("severity","UNKNOWN"), 4),
        "~" if not x.get("published") else x["published"]  # lexicographic desc trick
    ), reverse=False)
    # secondary sort: newest first inside each severity tier — re-sort stably
    from operator import itemgetter
    results.sort(key=lambda x: (
        _sev_rank.get(x.get("severity","UNKNOWN"), 4),
        -(int(x["published"].replace("-","")) if x.get("published","").replace("-","").isdigit() else 0)
    ))
    return results

# ── Base adapter ───────────────────────────────────────────────────────────────
class BaseAdapter:
    TTL = 86400
    def fetch(self, pkg, **kw): raise NotImplementedError
    def search(self, q, **kw): return []

def _gh_owner_from_url(url) -> str:
    """
    Extract the GitHub owner (org/user) from a repository URL.
      "git+https://github.com/facebook/react.git" → "facebook"
      "https://github.com/axios/axios"            → "axios"
      "https://gitlab.com/foo/bar"                → ""   (not GitHub)
    Used for country lookup so we resolve the REAL upstream org, not the
    registry's publishing-account name (npm "fb" → wrong → Germany).
    """
    if not url:
        return ""
    if isinstance(url, dict):
        url = url.get("url") or ""
    url = str(url).strip()
    m = re.search(r"github\.com[/:]([\w\-\.]+)/", url, flags=re.IGNORECASE)
    return m.group(1) if m else ""

def _email_domain(email: str) -> str:
    """Extract domain from an email address. Returns '' if not found."""
    if not email or "@" not in email:
        return ""
    return email.split("@")[-1].lower().strip()


def _row(lib, reg, ver="N/A", desc="—", lic="—", dl=0,
         maintainer="—", cves="—", repo="N/A", last_updated="—",
         gh_owner="", maintainer_email_domain=""):
    """
    `gh_owner` is the GitHub org/user from the upstream source repo.
    `maintainer_email_domain` is the primary maintainer's email domain — used
    by P1 monitoring to detect domain changes that may signal account hijack.
    Both fields are hidden from the UI.
    """
    return {
        "Library":      lib,
        "Registry":     reg,
        "Version":      ver or "N/A",
        "Maintainer":   maintainer or "—",
        "CVEs":         cves or "—",
        "License":      _lic(lic),
        "Downloads":    _fmt_dl(dl),
        "Last Updated": _fmt_date(last_updated),
        "Description":  _trunc(desc),
        "Repo":         _clean_repo_url(repo),
        "_dl_raw":      int(dl) if dl else 0,
        "_gh_owner":    gh_owner or "",                    # hidden: country lookup
        "_maintainer_email_domain": maintainer_email_domain or "",  # hidden: P1 monitoring
    }

# ── GitHub profile helpers ────────────────────────────────────────────────────
def _gh_handle(maintainer_str):
    """Extract (github_handle, is_org) from a Maintainer cell value."""
    if not maintainer_str or maintainer_str in ("—",):
        return None, False
    is_org = maintainer_str.startswith("Org")
    name   = maintainer_str.split("·", 1)[1].strip() if "·" in maintainer_str else maintainer_str
    name   = name.split("+")[0].strip()          # drop "+N more"
    if not name or "maintainer" in name.lower():
        return None, is_org
    # Maven groupId heuristic: com.google.guava → google
    if "." in name:
        parts = name.split(".")
        if parts[0] in ("com","org","io","net","edu") and len(parts) > 1:
            name = parts[1]
        else:
            name = parts[-1]
    return (name.strip() or None), is_org

def _gh_get(url, token=None):
    h = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = requests.get(url, headers=h, timeout=8)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 403:
            return {"_rate_limited": True}      # sentinel — callers check for "login"
        if r.status_code == 404:
            return {"_not_found": True}
        return None
    except:
        return None

def _gh_is_rate_limited(token=None):
    """True when the unauthenticated (or token) rate limit is exhausted."""
    h = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = requests.get("https://api.github.com/rate_limit", headers=h, timeout=5)
        if r.status_code == 200:
            rem = r.json().get("resources",{}).get("core",{}).get("remaining", 60)
            return rem == 0
    except:
        pass
    return False

def _is_versioned_variant(repo_name: str, base: str) -> bool:
    """
    Return True when repo_name looks like `base` followed by a bare version
    number — e.g. "junit4" for base "junit", or "log4j2" for "log4j".
    Non-versioned suffixes like "-framework" or "-core" return False.
    Also checks normalized (hyphen/underscore-stripped) forms so that
    "spring-boot-3" is recognised as versioned even when base is "springboot".
    """
    import re as _re
    rn, b = repo_name.lower(), base.lower()
    # Direct check
    if rn.startswith(b):
        suf = rn[len(b):]
        if _re.match(r'^[0-9]|^[-_\.][0-9]', suf):
            return True
    # Normalised check (strip hyphens / underscores)
    rn_n = rn.replace("-","").replace("_","")
    b_n  = b.replace("-","").replace("_","")
    if rn_n.startswith(b_n):
        suf_n = rn_n[len(b_n):]
        if _re.match(r'^[0-9]', suf_n):
            return True
    return False


_GH_SEARCH_CACHE: dict = {}   # module-level cache → survives dropdown reruns

def _gh_search_repo(pkg_name: str, token=None):
    """
    Search GitHub for a library's official repository when the registry
    doesn't provide a GitHub URL (e.g. Maven → mvnrepository.com).

    Algorithm (single stars-sorted request, 4 passes):
      Pass 1 – exact repo-name match, not a versioned variant
               "junit"         → skips "junit4"/"junit5", finds nothing exact
      Pass 2 – starts-with match, NOT a versioned variant
               "junit"         → skips "junit4", picks "junit-framework" ✅
               "bootstrap"     → picks "bootstrap"  (twbs/bootstrap)   ✅
               "spring-boot"   → picks "spring-boot"                   ✅
      Pass 3 – exact match even if versioned (fallback)
      Pass 4 – starts-with even if versioned (last resort)

    Base-name extraction:
      "junit:junit"                         → "junit"
      "@angular/core"                       → "core"
      "org.springframework.boot:spring-boot"→ "spring-boot"
    """
    import re as _re

    base = pkg_name.split(":")[-1].split("/")[-1].strip()
    for suf in ("-bom", "-api", "-core", "-main", "-parent", "_rs",
                "-starter", "-autoconfigure", "-actuator", "-test",
                "-common", "-commons", "-impl", "-support", "-all"):
        if base.endswith(suf) and len(base) > len(suf) + 2:
            base = base[: -len(suf)]
            break
    if not base or len(base) < 2:
        return None

    # Return cached result immediately (avoids GitHub Search rate-limit on re-views)
    _cache_key = base.lower()
    if _cache_key in _GH_SEARCH_CACHE:
        return _GH_SEARCH_CACHE[_cache_key]

    h = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = requests.get(
            "https://api.github.com/search/repositories"
            f"?q={requests.utils.quote(base)}+in:name"
            f"&sort=stars&order=desc&per_page=20",
            headers=h, timeout=9)
        if r.status_code != 200:
            return None
        pool = [i for i in r.json().get("items", []) if not i.get("fork")]

        base_n = base.lower().replace("-", "").replace("_", "")

        def _ret(val):
            _GH_SEARCH_CACHE[_cache_key] = val
            return val

        # Pass 1: exact name, non-versioned  (e.g. "bootstrap" → twbs/bootstrap)
        # Also matches normalised: "springboot" base == "spring-boot" repo name
        for item in pool:
            name = item.get("name", "").lower()
            name_n = name.replace("-", "").replace("_", "")
            if (name == base.lower() or name_n == base_n) and not _is_versioned_variant(name, base):
                return _ret(item["full_name"])

        # Pass 2: starts-with, non-versioned  (e.g. "junit" → junit-framework, skips junit4)
        # Normalised starts-with so "springboot" still picks up "spring-boot-…" variants
        for item in pool:
            name = item.get("name", "").lower()
            name_n = name.replace("-", "").replace("_", "")
            if (name.startswith(base.lower()) or name_n.startswith(base_n)) and not _is_versioned_variant(name, base):
                return _ret(item["full_name"])

        # Pass 3: exact name, any (including versioned)
        for item in pool:
            if item.get("name", "").lower() == base.lower():
                return _ret(item["full_name"])

        # Pass 4: starts-with, any (including versioned)
        for item in pool:
            if item.get("name", "").lower().startswith(base.lower()):
                return _ret(item["full_name"])

        # Pass 5: highest-starred non-fork (absolute fallback)
        return _ret(pool[0]["full_name"] if pool else None)

    except Exception:
        pass
    return None


def gh_profile(handle, is_org, token=None):
    """
    Fetch GitHub profile.  is_org can be True, False, or None (unknown).
    Tries both /orgs/ and /users/ — order depends on the hint.
    """
    order = ["orgs","users"] if is_org is True else ["users","orgs"]
    rate_hit = False
    for etype in order:
        d = _gh_get(f"https://api.github.com/{etype}/{handle}", token)
        if d and "login" in d:
            d["_etype"] = etype
            return d
        if isinstance(d, dict) and d.get("_rate_limited"):
            rate_hit = True
    return {"_rate_limited": True} if rate_hit else None

def gh_repos(handle, is_org, token=None):
    """Fetch top repos; tries both entity types if the first returns nothing."""
    for etype in (["orgs","users"] if is_org is True else ["users","orgs"]):
        data = _gh_get(
            f"https://api.github.com/{etype}/{handle}/repos"
            f"?sort=stars&per_page=6&type=public", token)
        if isinstance(data, list):
            return data
    return []

def _resolve_gh_handle(maintainer_str: str, repo_url: str = ""):
    """
    Multi-strategy GitHub handle extraction.

    Priority order:
      1. Repo-URL owner  — most accurate: github.com/twbs/bootstrap → "twbs"
         This is the org/user that actually OWNS the library on GitHub.
      2. Maintainer string fallback  — "User · mdo +3" → "mdo"
         Used only when there is no GitHub repo URL.

    Returns (handle, is_org)  — is_org may be None when unknown (gh_profile resolves it).
    """
    _NOISE = {"library","unknown","homebrew","docker","official","community",
              "chocolatey","microsoft","maintainer","maintainers"}

    # ── Strategy 1: repo URL owner (primary — definitive GitHub identity) ──────
    gh_path = _repo_url_to_gh(repo_url)
    if gh_path:
        owner = gh_path.split("/")[0]
        if owner and owner.lower() not in _NOISE:
            return owner, None      # is_org unknown; gh_profile() will figure it out

    # ── Strategy 2: maintainer string (fallback when no repo URL) ─────────────
    h, is_org = _gh_handle(maintainer_str)
    if h and h.lower() not in _NOISE:
        return h, is_org

    return None, False

def gh_commits(handle, token=None):
    events = _gh_get(
        f"https://api.github.com/users/{handle}/events?per_page=30", token)
    if not isinstance(events, list):
        return []
    out = []
    for e in events:
        if e.get("type") != "PushEvent":
            continue
        repo = e.get("repo", {}).get("name", "")
        for c in e.get("payload", {}).get("commits", [])[:2]:
            out.append({
                "repo":    repo,
                "message": c.get("message","").split("\n")[0][:80],
                "sha":     c.get("sha","")[:7],
                "date":    e.get("created_at","")[:10],
            })
        if len(out) >= 8:
            break
    return out

def _repo_url_to_gh(repo_url: str):
    """
    Extract 'owner/repo' from any GitHub URL, git+https URL, or npm/pypi repo field.
    Returns None if not a GitHub URL.
    """
    if not repo_url or repo_url in ("N/A", "—"):
        return None
    url = repo_url.strip()
    # Handle git+https://github.com/... or git://github.com/...
    url = url.replace("git+https://","https://").replace("git://","https://")
    # Must be github.com
    if "github.com" not in url.lower():
        return None
    # Strip trailing .git
    url = url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    # Extract path after github.com
    try:
        after = url.lower().split("github.com")[1].lstrip("/")
        parts = after.split("/")
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
    except:
        pass
    return None

def gh_repo_commits(repo_path: str, token=None):
    """
    Fetch the 8 most-recent commits on a GitHub repo directly.
    repo_path = 'owner/repo'
    Works for both org-owned and user-owned repos.
    """
    if not repo_path:
        return [], None
    data = _gh_get(
        f"https://api.github.com/repos/{repo_path}/commits?per_page=8", token)
    if not isinstance(data, list):
        return [], None
    out = []
    for c in data:
        commit = c.get("commit", {})
        author = commit.get("author", {}) or commit.get("committer", {})
        gh_au  = c.get("author") or {}
        out.append({
            "repo":    repo_path,
            "message": commit.get("message","").split("\n")[0][:80],
            "sha":     c.get("sha","")[:7],
            "date":    (author.get("date","") or "")[:10],
            "author":  gh_au.get("login","") or author.get("name","—"),
            "url":     c.get("html_url",""),
        })
    last_commit_date = out[0]["date"] if out else None
    return out, last_commit_date

def fetch_pkg_maintainers(pkg_name: str, registry: str) -> dict:
    """
    Fetch the original author + full active maintainer list from
    a specific registry's live API.

    Returns:
      {
        "author":      str,            # original creator / author field
        "maintainers": [               # current publish-rights holders
          {"name": str, "email": str, "url": str}, ...
        ]
      }
    """
    out = {"author": "", "maintainers": []}
    try:
        import re as _re

        if registry == "NPM":
            r = requests.get(f"https://registry.npmjs.org/{pkg_name}", timeout=9)
            if r.status_code != 200: return out
            d   = r.json()
            a   = d.get("author") or {}
            out["author"] = (a.get("name","") if isinstance(a,dict) else str(a)).strip()
            out["maintainers"] = [
                {"name":  m.get("name","").strip(),
                 "email": m.get("email","").strip(),
                 "url":   m.get("url","").strip()}
                for m in (d.get("maintainers") or [])
                if isinstance(m, dict) and m.get("name","").strip()
            ]

        elif registry == "PyPI":
            r = requests.get(f"https://pypi.org/pypi/{pkg_name}/json", timeout=9)
            if r.status_code != 200: return out
            d = r.json().get("info", {})
            out["author"] = (d.get("author") or "").strip()
            raw_m = (d.get("maintainer") or "").strip()
            if raw_m:
                out["maintainers"] = [{"name": n.strip(), "email":"","url":""}
                                       for n in raw_m.split(",") if n.strip()]
            elif out["author"]:
                out["maintainers"] = [{"name": out["author"], "email":"","url":""}]

        elif registry == "RubyGems":
            r = requests.get(
                f"https://rubygems.org/api/v1/gems/{pkg_name.lower()}.json", timeout=9)
            if r.status_code != 200: return out
            d   = r.json()
            raw = (d.get("authors") or "").strip()
            out["author"] = raw.split(",")[0].strip() if raw else ""
            out["maintainers"] = [{"name": n.strip(), "email":"","url":""}
                                   for n in raw.split(",") if n.strip()]

        elif registry == "Crates.io":
            # Teams first, then individual owners
            tu = requests.get(f"https://crates.io/api/v1/crates/{pkg_name}/owner_user",
                              headers={"User-Agent":"RegistryIntel/2.0"}, timeout=9)
            if tu.status_code == 200:
                users = tu.json().get("users",[])
                out["maintainers"] = [
                    {"name": u.get("login",""), "email":"",
                     "url":  f"https://github.com/{u.get('login','')}"}
                    for u in users if u.get("login")
                ]
                if users: out["author"] = users[0].get("login","")

        elif registry == "Maven Central":
            if ":" in pkg_name:
                g = pkg_name.split(":")[0]
                out["author"] = g
                out["maintainers"] = [{"name": g, "email":"","url":""}]

        elif registry == "NuGet":
            r = requests.get(
                f"https://azuresearch-usnc.nuget.org/query?q={pkg_name}&take=1", timeout=9)
            if r.status_code == 200:
                data = r.json().get("data",[])
                if data:
                    authors = data[0].get("authors",[]) or []
                    if isinstance(authors, str): authors = [authors]
                    out["author"] = authors[0] if authors else ""
                    out["maintainers"] = [{"name": a, "email":"","url":""} for a in authors if a]

        elif registry == "Packagist":
            rd = requests.get(f"https://packagist.org/packages/{pkg_name}.json", timeout=9)
            if rd.status_code == 200:
                pk = rd.json().get("package",{})
                ml = pk.get("maintainers",[])
                out["maintainers"] = [{"name": m.get("name",""), "email":"","url":""}
                                       for m in ml if m.get("name")]
                if ml: out["author"] = ml[0].get("name","")

        elif registry == "WordPress Plugins":
            r = requests.get(
                f"https://api.wordpress.org/plugins/info/1.2/"
                f"?action=plugin_information&request[slug]={pkg_name}", timeout=9)
            if r.status_code == 200:
                d = r.json()
                if isinstance(d, dict) and "error" not in d:
                    author = _re.sub(r"<[^>]+>","", d.get("author","")).strip()
                    out["author"] = author
                    out["maintainers"] = [{"name": author,"email":"","url":""}] if author else []

        elif registry == "Homebrew":
            for kind in ["formula","cask"]:
                r = requests.get(
                    f"https://formulae.brew.sh/api/{kind}/{pkg_name.lower()}.json", timeout=9)
                if r.status_code == 200:
                    out["author"] = "Homebrew Community"
                    out["maintainers"] = [{"name":"Homebrew Community","email":"",
                                           "url":"https://github.com/Homebrew"}]
                    break

    except:
        pass
    return out


# ── Email domain classifier ────────────────────────────────────────────────────
_FREE_WEBMAIL = {
    "gmail.com","yahoo.com","hotmail.com","outlook.com","protonmail.com",
    "icloud.com","me.com","live.com","aol.com","ymail.com","mail.com",
    "zoho.com","gmx.com","fastmail.com","tutanota.com","pm.me","hey.com",
}
_DISPOSABLE = {
    "mailinator.com","temp-mail.org","guerrillamail.com","throwam.com",
    "sharklasers.com","trashmail.com","yopmail.com","10minutemail.com",
    "dispostable.com","spamgourmet.com","trashmail.me","fakeinbox.com",
    "getnada.com","maildrop.cc","discard.email","tempinbox.com",
}
_TRUSTED_ORGS = {
    "apache.org","python.org","linux.com","mozilla.org","eclipse.org",
    "fsf.org","eff.org","openssl.org","postgresql.org","php.net",
    "ruby-lang.org","rust-lang.org","golang.org","nodejs.org",
    "linuxfoundation.org","cncf.io","openssf.org","owasp.org",
}

def _classify_email(email: str) -> dict:
    """Classify a maintainer email by domain type and return a risk signal."""
    if not email or "@" not in email:
        return {"domain": None, "category": "unknown", "risk": "unknown",
                "label": "—", "color": "#4a6580"}
    domain = email.split("@")[-1].lower().strip()
    if domain in _DISPOSABLE:
        return {"domain": domain, "category": "disposable", "risk": "high",
                "label": "🔴 Disposable email", "color": "#ef4444"}
    if domain in _FREE_WEBMAIL:
        return {"domain": domain, "category": "personal", "risk": "medium",
                "label": "🟡 Personal webmail", "color": "#f59e0b"}
    if domain in _TRUSTED_ORGS:
        return {"domain": domain, "category": "foundation", "risk": "low",
                "label": "🟢 Foundation / Trusted org", "color": "#22c55e"}
    return {"domain": domain, "category": "corporate", "risk": "low",
            "label": "🔵 Custom / Corporate domain", "color": "#06b6d4"}


# ── Account age risk ───────────────────────────────────────────────────────────
def _account_age(created_at: str) -> dict:
    """Return age in days + risk badge from a GitHub created_at timestamp."""
    if not created_at:
        return {"days": None, "label": "—", "risk": "unknown", "color": "#4a6580"}
    try:
        created = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        days    = (datetime.datetime.now(datetime.timezone.utc) - created).days
        yrs     = round(days / 365, 1)
        if days < 180:
            return {"days": days, "label": f"🔴 {days}d (very new)", "risk": "high",   "color": "#ef4444"}
        if days < 730:
            return {"days": days, "label": f"🟡 {yrs}y old",          "risk": "medium", "color": "#f59e0b"}
        return     {"days": days, "label": f"🟢 {yrs}y old",          "risk": "low",    "color": "#22c55e"}
    except Exception:
        return {"days": None, "label": "—", "risk": "unknown", "color": "#4a6580"}


# ── npm 2FA check ──────────────────────────────────────────────────────────────
def _npm_2fa(username: str) -> str:
    """
    Returns 'enabled', 'disabled', or 'unknown'.
    Uses the public npm profile endpoint — no auth required.
    """
    try:
        r = requests.get(
            f"https://registry.npmjs.org/-/npm/v1/users/{username}",
            timeout=6)
        if r.status_code != 200:
            return "unknown"
        tfa = r.json().get("tfa")
        if tfa is None:
            return "disabled"
        if isinstance(tfa, dict):
            return tfa.get("mode", "enabled") or "enabled"
        return "enabled"
    except Exception:
        return "unknown"


# ── OpenSSF Scorecard ──────────────────────────────────────────────────────────
def _openssf_scorecard(gh_path: str) -> dict | None:
    """
    Fetch OpenSSF Security Scorecard for a GitHub repo (no token needed).
    Returns dict with overall score + per-check breakdown, or None.
    """
    if not gh_path:
        return None
    try:
        r = requests.get(
            f"https://api.securityscorecards.dev/projects/github.com/{gh_path}",
            timeout=10)
        if r.status_code != 200:
            return None
        d = r.json()
        return {
            "score":  round(float(d.get("score", 0)), 1),
            "date":   (d.get("date", "") or "")[:10],
            "checks": [
                {
                    "name":  c.get("name", ""),
                    "score": c.get("score", -1),
                    "reason": c.get("reason", ""),
                }
                for c in d.get("checks", [])
            ],
        }
    except Exception:
        return None


# ── GitHub user public orgs ────────────────────────────────────────────────────
def _gh_user_orgs(login: str, token=None) -> list[str]:
    """Return list of public org logins the user belongs to."""
    data = _gh_get(f"https://api.github.com/users/{login}/orgs", token)
    if isinstance(data, list):
        return [o.get("login", "") for o in data if o.get("login")]
    return []


# ── Last public activity ───────────────────────────────────────────────────────
def _gh_last_event(login: str, token=None) -> str:
    """Return date string of the user's most recent public GitHub event."""
    data = _gh_get(
        f"https://api.github.com/users/{login}/events/public?per_page=5",
        token)
    if isinstance(data, list) and data:
        ts = (data[0].get("created_at") or "")[:10]
        return ts or "—"
    return "—"


# ── Commit signature rate ──────────────────────────────────────────────────────
def _commit_sig_rate(gh_path: str, login: str, token=None) -> dict:
    """
    Sample the author's last 10 commits to this repo and check GPG signing.
    Returns signed count, total checked, and a risk label.
    """
    data = _gh_get(
        f"https://api.github.com/repos/{gh_path}/commits"
        f"?author={login}&per_page=10",
        token)
    if not isinstance(data, list) or not data:
        return {"signed": 0, "total": 0, "label": "—"}
    total  = len(data)
    signed = sum(
        1 for c in data
        if (c.get("commit", {}).get("verification") or {}).get("verified")
    )
    pct = int(signed / total * 100)
    if pct == 100:
        label = f"🟢 100% signed ({signed}/{total})"
    elif pct >= 50:
        label = f"🟡 {pct}% signed ({signed}/{total})"
    elif signed == 0:
        label = f"🔴 0% signed (0/{total})"
    else:
        label = f"🔴 {pct}% signed ({signed}/{total})"
    return {"signed": signed, "total": total, "pct": pct, "label": label}


# ── Maintained packages count ──────────────────────────────────────────────────
def _npm_package_count(username: str) -> int | None:
    """Return number of npm packages the user owns/maintains."""
    try:
        r = requests.get(
            f"https://registry.npmjs.org/-/v1/search?text=maintainer:{username}&size=1",
            timeout=6)
        if r.status_code == 200:
            return r.json().get("total", None)
    except Exception:
        pass
    return None


# ── Full contributor intelligence ──────────────────────────────────────────────
def gh_contributors_intel(gh_path: str, token=None, n: int = 5,
                           reg_name: str = "") -> list:
    """
    Deep security-researcher profile of a repo's top-n contributors.

    Per contributor fetches:
      GitHub profile · social accounts (LinkedIn) · public orgs ·
      last event date · commit signature rate · npm 2FA · account age risk ·
      email domain classification · npm package count
    """
    if not gh_path:
        return []

    raw = _gh_get(
        f"https://api.github.com/repos/{gh_path}/contributors?per_page={n}&anon=0",
        token)
    if not raw or not isinstance(raw, list):
        return []

    # Repo owner org — used to check if contributor is an official org member
    repo_org = gh_path.split("/")[0].lower()

    result = []
    for c in raw[:n]:
        login = c.get("login", "")
        if not login:
            continue

        # 1. Full GitHub profile
        profile = _gh_get(f"https://api.github.com/users/{login}", token)
        if not profile or not isinstance(profile, dict) or "_rate_limited" in profile:
            continue

        # 2. Social accounts → real LinkedIn / Twitter URL
        socials  = _gh_get(f"https://api.github.com/users/{login}/social_accounts", token)
        linkedin = twitter = None
        if isinstance(socials, list):
            for s in socials:
                prov = (s.get("provider") or "").lower()
                url  = (s.get("url") or "").strip()
                if prov == "linkedin" and url:
                    linkedin = url
                elif prov in ("twitter", "x") and url:
                    twitter  = url
        if not twitter and profile.get("twitter_username"):
            twitter = f"https://x.com/{profile['twitter_username']}"

        # 3. Public orgs + org membership check
        user_orgs     = _gh_user_orgs(login, token)
        is_org_member = repo_org in [o.lower() for o in user_orgs]

        # 4. Last public activity
        last_active = _gh_last_event(login, token)

        # 5. Account age + risk
        age_info = _account_age(profile.get("created_at", ""))

        # 6. Email domain classification
        email       = (profile.get("email") or "").strip()
        email_class = _classify_email(email)

        # 7. Commit signature rate for this repo
        sig_info = _commit_sig_rate(gh_path, login, token)

        # 8. npm 2FA (always check — many devs publish on npm regardless of registry)
        npm_2fa_status = _npm_2fa(login)

        # 9. npm package count
        npm_pkgs = _npm_package_count(login)

        result.append({
            # Identity
            "login":         login,
            "name":          (profile.get("name") or login).strip(),
            "avatar_url":    profile.get("avatar_url", ""),
            "github_url":    f"https://github.com/{login}",
            "bio":           (profile.get("bio") or "").strip(),
            "company":       (profile.get("company") or "").strip().lstrip("@"),
            "location":      (profile.get("location") or "").strip(),
            "email":         email,
            "blog":          (profile.get("blog") or "").strip(),
            # Social
            "linkedin_url":  linkedin,
            "twitter_url":   twitter,
            # Activity
            "contributions": c.get("contributions", 0),
            "followers":     profile.get("followers", 0),
            "following":     profile.get("following", 0),
            "public_repos":  profile.get("public_repos", 0),
            "public_gists":  profile.get("public_gists", 0),
            "last_active":   last_active,
            # Org membership
            "user_orgs":      user_orgs,
            "is_org_member":  is_org_member,
            "repo_org":       repo_org,
            # Security signals
            "account_age":    age_info,
            "email_class":    email_class,
            "sig_info":       sig_info,
            "npm_2fa":        npm_2fa_status,
            "npm_pkgs":       npm_pkgs,
            "created_at":     (profile.get("created_at") or "")[:10],
            "hireable":       profile.get("hireable"),
            "site_admin":     profile.get("site_admin", False),
        })

    return result


def gh_repo_info(repo_path: str, token=None):
    """
    Fetch full metadata for one GitHub repository.
    repo_path = 'owner/repo'  e.g. 'twbs/bootstrap'
    Returns the raw GitHub API dict, or None.
    """
    if not repo_path:
        return None
    d = _gh_get(f"https://api.github.com/repos/{repo_path}", token)
    return d if (d and "full_name" in d) else None

# ── Adapters ───────────────────────────────────────────────────────────────────

class PyPIAdapter(BaseAdapter):
    @staticmethod
    def _pypi_source_url(info: dict, pkg_name: str) -> str:
        """
        Always return the PyPI package's own page as the Source link.

        Why: when a user searches PyPI, they expect to land on PyPI — not on
        whatever GitHub repo a maintainer happened to put in the Homepage field
        (which can be misleading, abandoned, or unrelated to the actual published
        package). The PyPI page is the authoritative source — it shows the real
        version, maintainer, download stats, AND the GitHub link if available.
        """
        return f"https://pypi.org/project/{pkg_name}/"

    @staticmethod
    def _pypi_license(info: dict) -> str:
        """
        Extract the most authoritative license string from a PyPI package.
        Order of trust:
          1. license_expression (PEP 639 SPDX — most modern, most accurate)
          2. license            (legacy free-text field)
          3. classifiers — parse "License :: OSI Approved :: MIT License" etc.
        Returns "—" only when no source contains any license signal.
        """
        # 1. PEP 639 SPDX expression (modern, accurate)
        le = (info.get("license_expression") or "").strip()
        if le:
            return le
        # 2. Legacy license field
        lic = (info.get("license") or "").strip()
        if lic and lic.lower() not in ("unknown", "none", "n/a"):
            # Trim very long license texts to just the first line
            return lic.split("\n")[0][:60]
        # 3. Walk classifiers for license trove markers
        # Example: "License :: OSI Approved :: Apache Software License"
        spdx_map = {
            "mit license":                     "MIT",
            "apache software license":         "Apache-2.0",
            "apache license":                  "Apache-2.0",
            "bsd license":                     "BSD",
            "gnu general public license v3":   "GPL-3.0",
            "gnu general public license v2":   "GPL-2.0",
            "gnu lesser general public license":"LGPL",
            "mozilla public license":          "MPL-2.0",
            "isc license":                     "ISC",
            "the unlicense":                   "Unlicense",
            "public domain":                   "Public Domain",
            "creative commons":                "CC",
        }
        for c in (info.get("classifiers") or []):
            if not c.lower().startswith("license ::"):
                continue
            cl = c.lower()
            for needle, spdx in spdx_map.items():
                if needle in cl:
                    return spdx
            # Fallback: take the last segment of the classifier as-is
            last_seg = c.split("::")[-1].strip()
            if last_seg and last_seg.lower() != "other/proprietary license":
                return last_seg[:30]
        return "—"

    def fetch(self, pkg, **kw):
        r = requests.get(f"https://pypi.org/pypi/{pkg}/json", timeout=TIMEOUT)
        if r.status_code != 200: return None
        payload  = r.json()
        d        = payload.get("info", {})
        v        = d.get("version", "N/A")
        # Last upload date for latest version
        releases = payload.get("releases", {})
        last_updated = "—"
        if v in releases and releases[v]:
            last_updated = releases[v][-1].get("upload_time", "—")
        dl = 0
        try:
            rd = requests.get(
                f"https://pypistats.org/api/packages/{pkg.lower()}/recent", timeout=5)
            if rd.status_code == 200: dl = rd.json().get("data",{}).get("last_month",0)
        except: pass
        name = d.get("maintainer") or d.get("author") or "—"
        m    = _m_auto(name)
        c    = check_vuln(pkg, "PyPI")
        # P1: extract author/maintainer email domain for hijack monitoring
        _raw_email = d.get("author_email", "") or d.get("maintainer_email", "") or ""
        _m_email   = re.search(r'[\w.+-]+@[\w.-]+\.\w+', _raw_email)
        _pypi_email_dom = _email_domain(_m_email.group(0) if _m_email else "")
        # Extract the REAL GitHub org from project_urls for country lookup
        _gh = ""
        for v_ in (d.get("project_urls") or {}).values():
            _gh = _gh_owner_from_url(v_)
            if _gh: break
        if not _gh:
            _gh = _gh_owner_from_url(d.get("home_page", ""))
        return _row(pkg, "PyPI", v, d.get("summary",""),
                    self._pypi_license(d),
                    dl, m, c,
                    self._pypi_source_url(d, pkg),
                    last_updated=last_updated,
                    gh_owner=_gh,
                    maintainer_email_domain=_pypi_email_dom)

    def search(self, q, **kw):
        slug = q.strip().replace(" ","-").lower()
        r    = requests.get(f"https://pypi.org/pypi/{slug}/json", timeout=TIMEOUT)
        if r.status_code != 200: return []
        payload = r.json()
        d       = payload.get("info", {})
        v       = d.get("version", "N/A")
        releases = payload.get("releases", {})
        last_updated = "—"
        if v in releases and releases[v]:
            last_updated = releases[v][-1].get("upload_time", "—")
        name = d.get("maintainer") or d.get("author") or "—"
        return [_row(slug, "PyPI", v, d.get("summary",""),
                     self._pypi_license(d), 0,
                     _m_auto(name), "—",
                     self._pypi_source_url(d, slug),
                     last_updated=last_updated)]


class NPMAdapter(BaseAdapter):
    @staticmethod
    def _npm_maintainer(pkg, d):
        """Return precise primary-maintainer label from npm registry data."""
        mlist = d.get("maintainers", [])
        a     = d.get("author", {})
        aname = a.get("name","") if isinstance(a, dict) else (a or "")
        if pkg.startswith("@"):
            org = pkg.split("/")[0][1:]
            return _m_org(org)
        if mlist:
            # Primary maintainer = first entry in maintainers array (npm orders by
            # publish rights seniority for most packages; gives jasonsayyan for axios)
            first = (mlist[0].get("name","") if isinstance(mlist[0], dict)
                     else str(mlist[0]))
            if len(mlist) > 1:
                return f"User · {first} +{len(mlist)-1}"
            return _m_user(first)
        if aname:
            return _m_user(aname)
        return "—"

    def fetch(self, pkg, **kw):
        r = requests.get(f"https://registry.npmjs.org/{pkg}", timeout=TIMEOUT)
        if r.status_code != 200: return None
        d    = r.json()
        v    = d.get("dist-tags",{}).get("latest","N/A")
        repo = d.get("repository",{})
        # Last modified from npm time map
        time_map     = d.get("time", {})
        last_updated = time_map.get("modified","") or time_map.get(v,"") or "—"
        dl = 0
        try:
            rd = requests.get(
                f"https://api.npmjs.org/downloads/point/last-month/{pkg}", timeout=5)
            if rd.status_code == 200: dl = rd.json().get("downloads",0)
        except: pass

        # ── .js suffix accuracy fix ──────────────────────────────────────────
        # "next.js" on npm is a tiny v1 package; the real framework is "next".
        # "vue.js" → "vue", "express.js" → "express", etc.
        # If query ends with ".js" also probe the bare name and prefer it when
        # it has significantly more downloads (5× threshold).
        if pkg.lower().endswith(".js") and len(pkg) > 3:
            base = pkg[:-3]                     # "next.js" → "next"
            try:
                r2 = requests.get(f"https://registry.npmjs.org/{base}", timeout=TIMEOUT)
                if r2.status_code == 200:
                    dl2 = 0
                    try:
                        rd2 = requests.get(
                            f"https://api.npmjs.org/downloads/point/last-month/{base}",
                            timeout=5)
                        if rd2.status_code == 200:
                            dl2 = rd2.json().get("downloads", 0)
                    except: pass
                    if dl2 > dl * 5:            # bare name is clearly more popular
                        d2   = r2.json()
                        v2   = d2.get("dist-tags", {}).get("latest", "N/A")
                        repo2 = d2.get("repository", {})
                        tm2  = d2.get("time", {})
                        lu2  = tm2.get("modified", "") or tm2.get(v2, "") or "—"
                        m2   = self._npm_maintainer(base, d2)
                        c2   = check_vuln(base, "npm")
                        return _row(
                            base, "NPM", v2,
                            d2.get("description", ""), d2.get("license", ""),
                            dl2, m2, c2,
                            _clean_repo_url(repo2),
                            last_updated=lu2)
            except Exception:
                pass
        # ────────────────────────────────────────────────────────────────────

        m = self._npm_maintainer(pkg, d)
        c = check_vuln(pkg,"npm")
        # P1: extract primary maintainer email domain for hijack monitoring
        _mlist = d.get("maintainers") or []
        _primary_email = (_mlist[0].get("email", "") if _mlist and isinstance(_mlist[0], dict) else "")
        _npm_email_dom = _email_domain(_primary_email)
        # Source button → GitHub repo if available, otherwise npm page.
        # Country lookup → use the REAL GitHub org from the repo URL.
        _gh_owner = _gh_owner_from_url(repo)
        _display_repo = _clean_repo_url(repo) or f"https://www.npmjs.com/package/{pkg}"
        return _row(pkg, "NPM", v, d.get("description",""), d.get("license",""),
                    dl, m, c,
                    _display_repo,
                    last_updated=last_updated,
                    gh_owner=_gh_owner,
                    maintainer_email_domain=_npm_email_dom)

    def search(self, q, **kw):
        r = requests.get(
            f"https://registry.npmjs.org/-/v1/search?text={requests.utils.quote(q)}&size={SEARCH_LIMIT}",
            timeout=TIMEOUT)
        if r.status_code != 200: return []
        out = []
        for obj in r.json().get("objects",[]):
            p    = obj.get("package",{})
            name = p.get("name","?")
            a    = p.get("author",{}) or {}
            aname= a.get("name","") if isinstance(a,dict) else ""
            mlist= p.get("maintainers",[]) or []
            if name.startswith("@"):
                m = _m_org(name.split("/")[0][1:])
            elif mlist:
                first = (mlist[0].get("username","") or mlist[0].get("name","")
                         if isinstance(mlist[0], dict) else str(mlist[0]))
                m = (f"User · {first} +{len(mlist)-1}" if len(mlist) > 1
                     else _m_user(first))
            elif aname:
                m = _m_user(aname)
            else:
                m = "—"
            last_updated = (obj.get("package",{}).get("date","") or
                            p.get("date","") or "—")
            out.append(_row(name, "NPM", p.get("version","N/A"),
                            p.get("description",""), p.get("license",""), 0,
                            m, "—", p.get("links",{}).get("npm","N/A"),
                            last_updated=last_updated))
        return out


class RubyGemsAdapter(BaseAdapter):
    def fetch(self, pkg, **kw):
        r = requests.get(
            f"https://rubygems.org/api/v1/gems/{pkg.lower()}.json", timeout=TIMEOUT)
        if r.status_code != 200: return None
        d    = r.json()
        authors = d.get("authors","—") or "—"
        m    = _m_auto(authors)
        c    = check_vuln(pkg.lower(),"RubyGems")
        last_updated = d.get("version_created_at","") or d.get("created_at","") or "—"
        # Country lookup → real GitHub org from source_code_uri / homepage
        _gh = (_gh_owner_from_url(d.get("source_code_uri","")) or
               _gh_owner_from_url(d.get("homepage_uri","")))
        # Source button → always the RubyGems page for this gem
        return _row(pkg.lower(), "RubyGems", d.get("version","N/A"),
                    d.get("info",""),
                    ", ".join(d.get("licenses") or []) if d.get("licenses") else "—",
                    d.get("downloads",0), m, c,
                    f"https://rubygems.org/gems/{pkg.lower()}",
                    last_updated=last_updated,
                    gh_owner=_gh)

    def search(self, q, **kw):
        r = requests.get(
            f"https://rubygems.org/api/v1/search.json?query={requests.utils.quote(q)}",
            timeout=TIMEOUT)
        if r.status_code != 200: return []
        return [_row(g.get("name","?"), "RubyGems", g.get("version","N/A"),
                     g.get("info",""),
                     ", ".join(g.get("licenses") or []) if g.get("licenses") else "—",
                     g.get("downloads",0),
                     _m_auto(g.get("authors","—")), "—",
                     f"https://rubygems.org/gems/{g.get('name','')}",
                     last_updated=g.get("version_created_at","") or "—")
                for g in r.json()[:SEARCH_LIMIT]]


class CratesAdapter(BaseAdapter):
    def fetch(self, pkg, **kw):
        r = requests.get(f"https://crates.io/api/v1/crates/{pkg}",
                         headers={"User-Agent":"RegistryIntel/2.0"}, timeout=TIMEOUT)
        if r.status_code != 200: return None
        data     = r.json()
        cr       = data.get("crate",{})
        versions = data.get("versions",[])

        # crates.io quirk: when every published version has been yanked, the API
        # reports max_version="0.0.0" as a placeholder. The real latest version
        # still lives in `versions[]` — surface it with a "(yanked)" suffix so
        # the user knows what the package actually contains.
        v = cr.get("max_stable_version") or cr.get("max_version", "N/A")
        if v in ("0.0.0", None, "N/A") and versions:
            real_latest = versions[0].get("num", v)
            yanked      = versions[0].get("yanked", False)
            v = f"{real_latest} (yanked)" if yanked else real_latest

        lic      = versions[0].get("license","—") if versions else "—"
        # Try owner endpoint for maintainer info
        m = "—"
        try:
            ou = requests.get(f"https://crates.io/api/v1/crates/{pkg}/owner_team",
                              headers={"User-Agent":"RegistryIntel/2.0"}, timeout=4)
            if ou.status_code == 200 and ou.json().get("teams"):
                tname = ou.json()["teams"][0].get("name","—")
                m = _m_org(tname)
            else:
                uu = requests.get(f"https://crates.io/api/v1/crates/{pkg}/owner_user",
                                  headers={"User-Agent":"RegistryIntel/2.0"}, timeout=4)
                if uu.status_code == 200:
                    users = uu.json().get("users",[])
                    if len(users) > 1:
                        m = f"Org · {users[0].get('login','—')} +{len(users)-1}"
                    elif users:
                        m = _m_user(users[0].get("login","—"))
        except: pass
        c            = check_vuln(pkg,"crates.io")
        last_updated = cr.get("updated_at","") or "—"
        # Country lookup → real GitHub org from repository / homepage
        _gh = (_gh_owner_from_url(cr.get("repository","")) or
               _gh_owner_from_url(cr.get("homepage","")))
        # Source button → always the crates.io page for this crate
        return _row(pkg, "Crates.io", v,
                    cr.get("description",""), lic,
                    cr.get("downloads",0), m, c,
                    f"https://crates.io/crates/{pkg}",
                    last_updated=last_updated,
                    gh_owner=_gh)

    def search(self, q, **kw):
        r = requests.get(
            f"https://crates.io/api/v1/crates?q={requests.utils.quote(q)}&per_page={SEARCH_LIMIT}",
            headers={"User-Agent":"RegistryIntel/2.0"}, timeout=TIMEOUT)
        if r.status_code != 200: return []
        return [_row(c.get("name","?"), "Crates.io",
                     c.get("max_stable_version") or c.get("max_version","N/A"),
                     c.get("description",""), "—",
                     c.get("downloads",0), "—", "—",
                     (c.get("repository") or c.get("homepage") or
                      f"https://crates.io/crates/{c.get('name','')}"),
                     last_updated=c.get("updated_at","") or "—")
                for c in r.json().get("crates",[])]


class PackagistAdapter(BaseAdapter):
    def fetch(self, pkg, **kw):
        r = requests.get(
            f"https://packagist.org/search.json?q={pkg}&per_page=1", timeout=TIMEOUT)
        if r.status_code != 200: return None
        res  = r.json().get("results",[])
        if not res: return None
        full = res[0].get("name","")
        if not _exact_match(pkg, full): return None
        rd = requests.get(f"https://packagist.org/packages/{full}.json", timeout=TIMEOUT)
        if rd.status_code != 200: return None
        pk      = rd.json().get("package",{})
        all_ver = pk.get("versions",{})
        stables = [v for v in all_ver if "dev-" not in v.lower()]
        v       = stables[0] if stables else "N/A"
        dl      = pk.get("downloads",{}).get("total",0) if isinstance(pk.get("downloads"),dict) else 0
        raw_lic = pk.get("license","—")
        lic     = ", ".join(raw_lic) if isinstance(raw_lic,list) else str(raw_lic or "—")
        mlist   = pk.get("maintainers",[])
        vendor  = full.split("/")[0]
        if len(mlist) > 1:
            m = f"Org · {vendor}"
        elif mlist:
            m = _m_user(mlist[0].get("name", vendor))
        else:
            m = _m_org(vendor)
        # Last release date
        last_updated = "—"
        if stables and stables[0] in all_ver:
            last_updated = all_ver[stables[0]].get("time","") or "—"
        c = check_vuln(full,"Packagist")
        # Country lookup → real GitHub org from repository URL
        _gh = _gh_owner_from_url(pk.get("repository",""))
        # Library shows just the package name (clean). Vendor stays in Maintainer.
        # Source button → always the Packagist page for this package
        pkg_name = full.split("/")[-1] if "/" in full else full
        return _row(pkg_name, "Packagist", v,
                    pk.get("description",""), lic, dl, m, c,
                    f"https://packagist.org/packages/{full}",
                    last_updated=last_updated,
                    gh_owner=_gh)

    def search(self, q, **kw):
        r = requests.get(
            f"https://packagist.org/search.json?q={requests.utils.quote(q)}&per_page={SEARCH_LIMIT}",
            timeout=TIMEOUT)
        if r.status_code != 200: return []
        return [_row(p.get("name","?").split("/")[-1], "Packagist", "N/A",
                     p.get("description",""), "—", 0,
                     _m_org(p.get("name","?").split("/")[0]), "—",
                     f"https://packagist.org/packages/{p.get('name','')}",
                     last_updated="—")
                for p in r.json().get("results",[])]


class MavenAdapter(BaseAdapter):
    @staticmethod
    def _maven_find(queries, artifact_id):
        """
        Run a list of Solr queries in order; return the first doc whose
        artifactId exactly matches `artifact_id`.  Takes up to 5 candidates
        per query so one noisy result doesn't block the real hit.
        """
        for q in queries:
            try:
                r = requests.get(
                    f"https://search.maven.org/solrsearch/select?q={q}&rows=5&wt=json",
                    timeout=TIMEOUT)
                if r.status_code != 200:
                    continue
                docs = r.json().get("response", {}).get("docs", [])
                # Prefer an exact artifactId hit
                exact = [d for d in docs
                         if d.get("a", "").lower() == artifact_id.lower()]
                if exact:
                    return exact[0]
                # Fall back to any doc if no exact match in this query round
                if docs and not exact:
                    # only use it if it's the last query (don't give up early)
                    pass
            except Exception:
                continue
        return None

    @staticmethod
    def _maven_text_search(pkg):
        """
        Free-text Maven search fallback used when exact Solr queries return nothing.
        Covers cases like "springboot" (no exact artifact) → Maven's relevance
        ranking surfaces org.springframework.boot:spring-boot-starter as the top hit.
        Also tries the hyphenated variant (springboot → spring-boot) so that
        Maven's indexed text matches compound artifact IDs.
        """
        variants = [pkg]
        # Build a hyphenated guess by inserting a dash at every lowercase→lowercase
        # run boundary that looks like a compound word (simple best-effort).
        import re as _re
        hyph = _re.sub(r'([a-z])([A-Z])', r'\1-\2', pkg).lower()
        if hyph != pkg.lower():
            variants.append(hyph)
        # Also try the plain lower-case with a dash in the middle for equal-halves split
        p = pkg.lower()
        if len(p) >= 6 and "-" not in p:
            mid = len(p) // 2
            variants.append(p[:mid] + "-" + p[mid:])

        import re as _re2
        # Normalised query for relevance filtering (strip dots/hyphens/underscores)
        pkg_norm = _re2.sub(r'[\.\-_]', '', pkg.lower())

        for term in variants:
            try:
                r = requests.get(
                    f"https://search.maven.org/solrsearch/select"
                    f"?q={requests.utils.quote(term)}&rows=10&wt=json",
                    timeout=TIMEOUT)
                if r.status_code != 200:
                    continue
                docs = r.json().get("response", {}).get("docs", [])
                if not docs:
                    continue
                # ── Relevance filter ─────────────────────────────────────────
                # Only keep docs whose artifactId is a close match to the query
                # so that e.g. "kotlin-styled-next-js" never surfaces for "nextjs".
                def _art_norm(d):
                    return _re2.sub(r'[\.\-_]', '', d.get("a", "").lower())

                relevant = [d for d in docs if _art_norm(d).startswith(pkg_norm)]
                if not relevant:
                    # Looser pass: artifactId *contains* the normalised query
                    relevant = [d for d in docs if pkg_norm in _art_norm(d)]
                if not relevant:
                    # Last resort: only accept if the query name appears somewhere
                    # in the artifactId or groupId — never return a totally unrelated hit.
                    relevant = [d for d in docs
                                if _name_match(pkg, d.get("a","")) or
                                   _name_match(pkg, d.get("g",""))]
                if not relevant:
                    continue   # try next variant before giving up
                # Pick the most mature artifact
                return max(relevant, key=lambda d: d.get("versionCount", 0))
            except Exception:
                continue
        return None

    def fetch(self, pkg, **kw):
        if ":" in pkg:
            g_id, a_id = pkg.split(":", 1)
            # Single precise query — user supplied full coordinates
            queries     = [f"g:{g_id}+AND+a:{a_id}"]
            artifact_id = a_id
        else:
            # Plain name (e.g. "junit", "log4j", "guava", "springboot")
            # Strategy 1: g:name AND a:name  → catches junit:junit, log4j:log4j
            # Strategy 2: a:name             → catches any group with that artifactId
            queries     = [f"g:{pkg}+AND+a:{pkg}", f"a:{pkg}"]
            artifact_id = pkg

        d = self._maven_find(queries, artifact_id)

        # Strategy 3 (fallback): free-text search — handles "springboot" → spring-boot-starter
        if not d and ":" not in pkg:
            d = self._maven_text_search(pkg)

        if not d:
            return None

        full = f"{d.get('g')}:{d.get('a')}"
        g    = d.get("g", "")
        a_id = d.get("a", "")
        m    = _m_org(g)
        c    = check_vuln(full, "Maven")
        desc = f"{g}  ·  {a_id}"
        ts   = d.get("timestamp", 0)
        last_updated = (datetime.datetime.utcfromtimestamp(ts / 1000).strftime("%Y-%m-%d")
                        if ts else "—")

        # The Solr Search API's `latestVersion` AND `timestamp` are GENUINELY
        # STALE — Solr doesn't re-index when new versions are released. The
        # authoritative source is Maven Central's own maven-metadata.xml file,
        # which always reflects the actual repo state.
        # e.g. com.google.guava:guava → Solr says 33.4.8-jre (Apr 2025),
        #      metadata.xml says 33.6.0-jre with lastUpdated of today
        latest_ver = d.get("latestVersion", "N/A")
        gh_owner   = ""   # for country lookup — extracted from POM <scm>
        try:
            g_path = g.replace(".", "/")
            meta_r = requests.get(
                f"https://repo1.maven.org/maven2/{g_path}/{a_id}/maven-metadata.xml",
                timeout=TIMEOUT
            )
            if meta_r.status_code == 200:
                txt = meta_r.text
                # Prefer <release> (stable), fall back to <latest>
                m_rel = re.search(r"<release>([^<]+)</release>", txt)
                m_lat = re.search(r"<latest>([^<]+)</latest>",   txt)
                if m_rel:
                    latest_ver = m_rel.group(1).strip()
                elif m_lat:
                    latest_ver = m_lat.group(1).strip()
                # <lastUpdated>20260515111108</lastUpdated>  → YYYY-MM-DD
                m_upd = re.search(r"<lastUpdated>(\d{8})\d*</lastUpdated>", txt)
                if m_upd:
                    raw = m_upd.group(1)
                    last_updated = f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
        except Exception:
            pass

        # Fetch the POM file — it contains <scm><url> pointing to the upstream
        # GitHub repo. For wrapper packages like org.webjars.npm:react this
        # gives us the REAL upstream (facebook/react → USA), not the wrapper org.
        try:
            g_path = g.replace(".", "/")
            pom_r = requests.get(
                f"https://repo1.maven.org/maven2/{g_path}/{a_id}/{latest_ver}/"
                f"{a_id}-{latest_ver}.pom",
                timeout=8
            )
            if pom_r.status_code == 200:
                pom = pom_r.text
                # <scm><url>...</url></scm> OR <scm><connection>...</connection>
                for tag in ("url", "connection", "developerConnection"):
                    for m_scm in re.finditer(
                            rf"<scm>.*?<{tag}>([^<]+)</{tag}>", pom, flags=re.DOTALL):
                        owner = _gh_owner_from_url(m_scm.group(1))
                        if owner:
                            gh_owner = owner
                            break
                    if gh_owner:
                        break
                # Fallback: scan the whole POM for any github.com URL
                if not gh_owner:
                    gh_owner = _gh_owner_from_url(pom)
        except Exception:
            pass

        # Library column shows just the artifact name (clean) — full coordinates
        # are still preserved in Maintainer ("Org · {g}") and Description ("{g} · {a}")
        return _row(a_id, "Maven Central", latest_ver,
                    desc, "Apache-2.0", 0, m, c,
                    f"https://mvnrepository.com/artifact/{g}/{a_id}",
                    last_updated=last_updated,
                    gh_owner=gh_owner)

    def search(self, q, **kw):
        r = requests.get(
            f"https://search.maven.org/solrsearch/select?q={requests.utils.quote(q)}&rows={SEARCH_LIMIT}&wt=json",
            timeout=TIMEOUT)
        if r.status_code != 200: return []
        out = []
        for d in r.json().get("response",{}).get("docs",[]):
            ts   = d.get("timestamp", 0)
            lud  = (datetime.datetime.utcfromtimestamp(ts/1000).strftime("%Y-%m-%d")
                    if ts else "—")
            out.append(_row(d.get("a","?"), "Maven Central",
                            d.get("latestVersion","N/A"),
                            f"{d.get('g','')}  ·  {d.get('a','')}", "Apache-2.0", 0,
                            _m_org(d.get("g","")), "—",
                            f"https://mvnrepository.com/artifact/{d.get('g')}/{d.get('a')}",
                            last_updated=lud))
        return out


class NuGetAdapter(BaseAdapter):
    @staticmethod
    def _nuget_published_date(pid: str, version: str) -> str:
        """
        NuGet's search API (`azuresearch-usnc.nuget.org/query`) does NOT return
        a `published` date — it's always null. The authoritative source is the
        Registration API which has `published` per catalog entry.

        Endpoint: https://api.nuget.org/v3/registration5-semver1/{id_lower}/index.json
        We pick the catalogEntry whose version matches the latest.
        """
        try:
            r = requests.get(
                f"https://api.nuget.org/v3/registration5-semver1/"
                f"{pid.lower()}/index.json",
                timeout=8)
            if r.status_code != 200:
                return "—"
            pages = r.json().get("items", []) or []
            # The last page contains the newest version
            for page in reversed(pages):
                inner = page.get("items", [])
                # Inline data preferred; some pages link out to a separate page URL
                if not inner and page.get("@id"):
                    rr = requests.get(page["@id"], timeout=6)
                    if rr.status_code == 200:
                        inner = rr.json().get("items", [])
                # Find the matching version (or take the last/newest in this page)
                for entry in reversed(inner):
                    ce = entry.get("catalogEntry", {}) or {}
                    if ce.get("version") == version:
                        return (ce.get("published") or "—")
                if inner:
                    return (inner[-1].get("catalogEntry", {}).get("published") or "—")
        except Exception:
            pass
        return "—"

    def fetch(self, pkg, **kw):
        r = requests.get(
            f"https://azuresearch-usnc.nuget.org/query?q={pkg}&take=1", timeout=TIMEOUT)
        if r.status_code != 200: return None
        data = r.json().get("data",[])
        if not data: return None
        d = data[0]
        if not _exact_match(pkg, d.get("id","")): return None
        authors  = d.get("authors",[]) or []
        if isinstance(authors, list):
            if len(authors) > 1:
                m = f"Org · {authors[0]} +{len(authors)-1}"
            elif authors:
                m = _m_auto(authors[0])
            else:
                m = "—"
        else:
            m = _m_auto(str(authors))
        # License extraction:
        # 1. licenseExpression (SPDX) — newest NuGet format, most accurate
        # 2. licenseUrl — older URL-based; _lic() now parses common patterns
        # 3. GitHub fallback — if NuGet has projectUrl pointing to GitHub,
        #    fetch the repo's authoritative SPDX license from the GitHub API
        lic_raw = d.get("licenseExpression","") or d.get("licenseUrl","") or "—"
        lic     = _lic(lic_raw)
        c       = check_vuln(d.get("id",pkg),"NuGet")
        pid     = d.get("id", pkg)
        ver     = d.get("version", "N/A")
        # Country lookup → real GitHub org from projectUrl
        _gh = _gh_owner_from_url(d.get("projectUrl",""))
        # GitHub license fallback when NuGet's data is mangled / missing
        if lic in ("—", "") and _gh:
            try:
                _repo_part = (d.get("projectUrl","") or "").rstrip("/").split("/")[-1]
                _glr = requests.get(
                    f"https://api.github.com/repos/{_gh}/{_repo_part}",
                    headers={"User-Agent":"RegistryIntelligencePlatform/1.0",
                             "Accept":"application/vnd.github+json"},
                    timeout=6)
                if _glr.status_code == 200:
                    _glic = (_glr.json().get("license") or {}).get("spdx_id", "")
                    if _glic and _glic not in ("NOASSERTION", "", None):
                        lic = _glic
            except Exception:
                pass
        # Search API returns published=null — use the Registration API instead
        last_updated = d.get("published") or self._nuget_published_date(pid, ver)
        # Source button → always the NuGet page for this package
        return _row(pid, "NuGet", d.get("version","N/A"),
                    d.get("description",""), lic,
                    d.get("totalDownloads",0), m, c,
                    f"https://www.nuget.org/packages/{pid}",
                    last_updated=last_updated,
                    gh_owner=_gh)

    def search(self, q, **kw):
        r = requests.get(
            f"https://azuresearch-usnc.nuget.org/query?q={requests.utils.quote(q)}&take={SEARCH_LIMIT}",
            timeout=TIMEOUT)
        if r.status_code != 200: return []
        return [_row(d.get("id","?"), "NuGet", d.get("version","N/A"),
                     d.get("description",""), "—",
                     d.get("totalDownloads",0), "—", "—",
                     f"https://www.nuget.org/packages/{d.get('id','')}",
                     last_updated=(d.get("published")
                                   or self._nuget_published_date(
                                          d.get("id",""),
                                          d.get("version",""))))
                for d in r.json().get("data",[])]


class GoModulesAdapter(BaseAdapter):
    def fetch(self, pkg, **kw):
        if "/" not in pkg: return None
        r = requests.get(f"https://proxy.golang.org/{pkg}/@latest", timeout=TIMEOUT)
        if r.status_code != 200: return None
        proxy_data   = r.json()
        v            = proxy_data.get("Version","N/A")
        last_updated = proxy_data.get("Time","") or "—"
        lic = "—"
        try:
            enc     = requests.utils.quote(pkg, safe="")
            ver_enc = requests.utils.quote(v, safe="")
            dr      = requests.get(
                f"https://api.deps.dev/v3alpha/systems/go/packages/{enc}/versions/{ver_enc}",
                timeout=5)
            if dr.status_code == 200:
                lics = dr.json().get("licenses",[])
                lic  = ", ".join(lics) if lics else "—"
        except: pass
        parts = pkg.split("/")
        owner = parts[1] if len(parts) >= 2 else "—"
        m     = _m_user(owner)
        c     = check_vuln(pkg,"Go")
        # For Go modules with path "github.com/owner/repo", owner is the real
        # GitHub org → ideal for country lookup
        _gh = owner if (len(parts) >= 3 and parts[0].lower() == "github.com") else ""
        return _row(pkg, "Go Modules", v, "—", lic, 0, m, c,
                    f"https://pkg.go.dev/{pkg}",
                    last_updated=last_updated,
                    gh_owner=_gh)


class HomebrewAdapter(BaseAdapter):
    @staticmethod
    def _formula_last_commit(kind: str, name: str, token: str = None) -> str:
        """
        Homebrew's formulae.brew.sh API doesn't expose a last-updated date,
        but the homebrew-core / homebrew-cask repos on GitHub do. Look up
        the most recent commit touching the formula file.
        """
        path = "Formula" if kind == "formula" else "Cask"
        repo = "homebrew-core" if kind == "formula" else "homebrew-cask"
        # Recent Homebrew core layout: Formula/{letter}/{name}.rb (sharded)
        # Try sharded path first, then flat path as fallback.
        candidates = [
            f"{path}/{name[0]}/{name}.rb",
            f"{path}/{name}.rb",
        ]
        headers = {"User-Agent": "RegistryIntelligencePlatform/1.0",
                   "Accept":     "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        for cpath in candidates:
            try:
                r = requests.get(
                    f"https://api.github.com/repos/Homebrew/{repo}/commits"
                    f"?path={requests.utils.quote(cpath)}&per_page=1",
                    headers=headers, timeout=6)
                if r.status_code == 200:
                    commits = r.json()
                    if commits:
                        return ((commits[0].get("commit") or {})
                                .get("committer", {})
                                .get("date", "") or "—")
            except Exception:
                continue
        return "—"

    def fetch(self, pkg, **kw):
        name = pkg.lower()
        for kind in ["formula","cask"]:
            r = requests.get(
                f"https://formulae.brew.sh/api/{kind}/{name}.json", timeout=TIMEOUT)
            if r.status_code == 200:
                d = r.json()
                v = (d.get("versions") or {}).get("stable") or d.get("version","N/A")
                # Last updated → last commit touching the formula file on GitHub
                lu = self._formula_last_commit(kind, name, kw.get("token"))
                # Source button → always the Homebrew formulae page
                return _row(name, "Homebrew", v,
                            d.get("desc",""), "—", 0,
                            "Community · Homebrew", "—",
                            f"https://formulae.brew.sh/{kind}/{name}",
                            last_updated=lu)
        return None


class DockerHubAdapter(BaseAdapter):
    TTL = 3600
    def fetch(self, pkg, **kw):
        slug  = pkg.lower()
        ns,nm = slug.split("/",1) if "/" in slug else ("library",slug)
        r = requests.get(
            f"https://hub.docker.com/v2/repositories/{ns}/{nm}/", timeout=TIMEOUT)
        if r.status_code != 200: return None
        d         = r.json()
        tag_count = d.get("tag_count",0)
        ver_label = f"{tag_count} tags" if tag_count else "see tags"
        if d.get("is_official"):
            m = "Org · Docker Official"
        elif ns == "library":
            m = "Org · Docker"
        else:
            m = _m_org(ns)
        last_updated = d.get("last_updated","") or "—"
        # Docker Hub namespace often matches GitHub org (nginx, redis, mysql)
        # Library shows just the image name; namespace stays in Maintainer
        return _row(nm, "Docker Hub", ver_label,
                    _trunc(d.get("full_description") or d.get("description",""),72),
                    "—", d.get("pull_count",0), m, "—",
                    f"https://hub.docker.com/r/{ns}/{nm}",
                    last_updated=last_updated,
                    gh_owner=ns if ns != "library" else nm)

    def search(self, q, **kw):
        r = requests.get(
            f"https://hub.docker.com/v2/search/repositories/?query={requests.utils.quote(q)}&page_size={SEARCH_LIMIT}",
            timeout=TIMEOUT)
        if r.status_code != 200: return []
        out = []
        for res in r.json().get("results",[]):
            ow = res.get("repo_owner") or "library"
            nm = res.get("repo_name","?")
            m  = "Org · Docker Official" if res.get("is_official") else _m_org(ow)
            out.append(_row(nm, "Docker Hub", "see tags",
                            _trunc(res.get("short_description",""),72),
                            "—", res.get("pull_count",0), m, "—",
                            f"https://hub.docker.com/r/{ow}/{nm}",
                            last_updated=res.get("last_updated","") or "—"))
        return out


class HuggingFaceAdapter(BaseAdapter):
    def fetch(self, pkg, **kw):
        r = requests.get(f"https://huggingface.co/api/models/{pkg}", timeout=TIMEOUT)
        if r.status_code == 200:
            d        = r.json(); mid = d.get("id",pkg)
            pipeline = d.get("pipeline_tag","")
            card     = d.get("cardData") or {}
            desc     = card.get("description","") or (
                       f"Task: {pipeline}" if pipeline else
                       " | ".join(d.get("tags",[])[:3]))
            lic      = card.get("license","—") or "—"
            author   = d.get("author","") or mid.split("/")[0]
            m        = _m_org(author) if "/" in mid else _m_user(author)
            lm       = d.get("lastModified","") or "—"
            model_name = mid.split("/")[-1] if "/" in mid else mid
            # HF org name often matches a GitHub org (microsoft, google, openai)
            return _row(model_name, "Hugging Face", lm[:10],
                        desc, lic, d.get("downloads",0), m, "—",
                        f"https://huggingface.co/{mid}",
                        last_updated=lm,
                        gh_owner=author)
        r2 = requests.get(
            f"https://huggingface.co/api/models?search={pkg}&limit=1&sort=downloads",
            timeout=TIMEOUT)
        if r2.status_code == 200:
            res = r2.json()
            if res:
                d   = res[0]; mid = d.get("id",pkg)
                if not _exact_match(pkg, mid): return None
                pipeline = d.get("pipeline_tag","")
                desc     = f"Task: {pipeline}" if pipeline else " | ".join(d.get("tags",[])[:3])
                author   = d.get("author","") or mid.split("/")[0]
                m        = _m_org(author) if "/" in mid else _m_user(author)
                lm       = d.get("lastModified","") or "—"
                model_name = mid.split("/")[-1] if "/" in mid else mid
                return _row(model_name, "Hugging Face", lm[:10],
                            desc, "—", d.get("downloads",0), m, "—",
                            f"https://huggingface.co/{mid}",
                            last_updated=lm,
                            gh_owner=author)
        return None

    def search(self, q, **kw):
        r = requests.get(
            f"https://huggingface.co/api/models?search={requests.utils.quote(q)}&limit={SEARCH_LIMIT}&sort=downloads",
            timeout=TIMEOUT)
        if r.status_code != 200: return []
        rows = []
        for d in r.json():
            pipeline = d.get("pipeline_tag","")
            desc     = f"Task: {pipeline}" if pipeline else " | ".join(d.get("tags",[])[:3])
            mid      = d.get("id","?")
            author   = d.get("author","") or (mid.split("/")[0] if "/" in mid else "")
            m        = _m_org(author) if "/" in mid else _m_user(author)
            lm       = d.get("lastModified","") or "—"
            model_name = mid.split("/")[-1] if "/" in mid else mid
            rows.append(_row(model_name, "Hugging Face", lm[:10],
                             desc, "—", d.get("downloads",0), m, "—",
                             f"https://huggingface.co/{mid}",
                             last_updated=lm))
        return rows


class WordPressAdapter(BaseAdapter):
    def fetch(self, pkg, **kw):
        r = requests.get(
            f"https://api.wordpress.org/plugins/info/1.2/"
            f"?action=plugin_information&request[slug]={pkg.lower()}", timeout=TIMEOUT)
        if r.status_code != 200: return None
        d = r.json()
        if not isinstance(d,dict) or "error" in d: return None
        author = d.get("author","—")
        # Strip HTML tags from author field
        import re
        author = re.sub(r"<[^>]+>","",author).strip()
        # Source button → always the WordPress.org plugin page
        return _row(pkg.lower(), "WordPress Plugins", d.get("version","N/A"),
                    d.get("short_description",""), "GPL-2.0",
                    d.get("active_installs",0),
                    _m_user(author), "—",
                    f"https://wordpress.org/plugins/{pkg.lower()}/",
                    last_updated=d.get("last_updated","") or "—")

    def search(self, q, **kw):
        r = requests.get(
            f"https://api.wordpress.org/plugins/info/1.2/?action=query_plugins"
            f"&request[search]={requests.utils.quote(q)}&request[per_page]={SEARCH_LIMIT}",
            timeout=TIMEOUT)
        if r.status_code != 200: return []
        import re
        return [_row(p.get("slug","?"), "WordPress Plugins", p.get("version","N/A"),
                     p.get("short_description",""), "GPL-2.0",
                     p.get("active_installs",0),
                     _m_user(re.sub(r"<[^>]+>","",p.get("author","—")).strip()),
                     "—",
                     f"https://wordpress.org/plugins/{p.get('slug','')}/",
                     last_updated=p.get("last_updated","") or "—")
                for p in r.json().get("plugins",[])]


class TerraformAdapter(BaseAdapter):
    def fetch(self, pkg, **kw):
        r = requests.get(
            f"https://registry.terraform.io/v1/modules?q={pkg}&limit=1", timeout=TIMEOUT)
        if r.status_code != 200: return None
        mods = r.json().get("modules",[])
        if not mods: return None
        mo = mods[0]
        if not _exact_match(pkg, mo.get("name","")): return None
        # ID format: namespace/name/provider — show just the module name in Library
        namespace = mo.get("id","").split("/")[0] if "/" in mo.get("id","") else "—"
        return _row(mo.get("name", pkg), "Terraform Registry", mo.get("version","N/A"),
                    mo.get("description","—"), "MPL-2.0",
                    mo.get("downloads",0), _m_org(namespace), "—",
                    f"https://registry.terraform.io/modules/{mo.get('id','')}",
                    last_updated=mo.get("published_at","") or "—",
                    gh_owner=namespace)

    def search(self, q, **kw):
        r = requests.get(
            f"https://registry.terraform.io/v1/modules?q={requests.utils.quote(q)}&limit={SEARCH_LIMIT}",
            timeout=TIMEOUT)
        if r.status_code != 200: return []
        return [_row(mo.get("name","?"), "Terraform Registry", mo.get("version","N/A"),
                     mo.get("description","—"), "MPL-2.0",
                     mo.get("downloads",0),
                     _m_org(mo.get("id","?").split("/")[0] if "/" in mo.get("id","?") else "—"),
                     "—",
                     f"https://registry.terraform.io/modules/{mo.get('id','')}",
                     last_updated=mo.get("published_at","") or "—")
                for mo in r.json().get("modules",[])]


class AnsibleGalaxyAdapter(BaseAdapter):
    def fetch(self, pkg, **kw):
        if "." not in pkg: return None
        r = requests.get(
            f"https://galaxy.ansible.com/api/v1/roles/?name={pkg}&page_size=1&ordering=-download_count",
            timeout=TIMEOUT)
        if r.status_code != 200: return None
        res = r.json().get("results",[])
        if not res: return None
        d  = res[0]
        if not _exact_match(pkg, d.get("name","")): return None
        ns = (d.get("summary_fields") or {}).get("namespace",{}).get("name","—")
        # Library shows just the role name; namespace stays in Maintainer
        # Source button → always the Ansible Galaxy page
        return _row(d.get("name", pkg), "Ansible Galaxy",
                    d.get("version","N/A"), d.get("description",""), "—",
                    d.get("download_count",0),
                    _m_user(ns), "—",
                    f"https://galaxy.ansible.com/{ns}/{d.get('name','')}",
                    last_updated=d.get("modified","") or "—",
                    gh_owner=ns)

    def search(self, q, **kw):
        r = requests.get(
            f"https://galaxy.ansible.com/api/v3/plugin/ansible/content/published/"
            f"collections/index/?keywords={requests.utils.quote(q)}&limit={SEARCH_LIMIT}",
            timeout=TIMEOUT)
        if r.status_code != 200: return []
        out = []
        for d in r.json().get("data",[]):
            ns = (d.get("namespace") or {}).get("name","?") \
                 if isinstance(d.get("namespace"),dict) else d.get("namespace","?")
            hv = d.get("highest_version") or {}
            out.append(_row(d.get("name","?"), "Ansible Galaxy",
                            hv.get("version","N/A"), d.get("description","—"), "—", 0,
                            _m_user(ns), "—",
                            f"https://galaxy.ansible.com/{ns}/{d.get('name','')}",
                            last_updated=d.get("modified","") or "—"))
        return out


class ChocolateyAdapter(BaseAdapter):
    def fetch(self, pkg, **kw):
        r = requests.get(
            f"https://community.chocolatey.org/api/v2/Packages()?"
            f"$filter=Id eq '{pkg}' and IsLatestVersion eq true&$format=json", timeout=12)
        if r.status_code != 200: return None
        data    = r.json()
        entries = data.get("d",{}).get("results",[]) or data.get("value",[])
        if not entries: return None
        e            = entries[0]
        last_updated = _fmt_date(e.get("Published","") or e.get("LastEdited","") or "—")
        # Source button → always the Chocolatey package page
        return _row(pkg, "Chocolatey", e.get("Version","N/A"),
                    e.get("Description",""), "—",
                    e.get("DownloadCount",0),
                    "Community · Chocolatey", "—",
                    f"https://community.chocolatey.org/packages/{pkg}",
                    last_updated=last_updated)

    def search(self, q, **kw):
        r = requests.get(
            f"https://community.chocolatey.org/api/v2/Search()?"
            f"searchTerm='{requests.utils.quote(q)}'&$top={SEARCH_LIMIT}"
            f"&$filter=IsLatestVersion eq true&$format=json", timeout=12)
        if r.status_code != 200: return []
        data    = r.json()
        entries = data.get("d",{}).get("results",[]) or data.get("value",[])
        return [_row(e.get("Id","?"), "Chocolatey", e.get("Version","N/A"),
                     e.get("Description",""), "—",
                     e.get("DownloadCount",0),
                     "Community · Chocolatey", "—",
                     f"https://community.chocolatey.org/packages/{e.get('Id','')}",
                     last_updated=_fmt_date(e.get("Published","") or e.get("LastEdited","") or "—"))
                for e in entries]


class VSCodeAdapter(BaseAdapter):
    def fetch(self, pkg, **kw):
        if "." not in pkg: return None
        payload = {"filters":[{"criteria":[{"filterType":7,"value":pkg}],
                               "pageSize":1,"pageNumber":1}],"flags":514}
        r = requests.post(
            "https://marketplace.visualstudio.com/_apis/public/gallery/"
            "extensionquery?api-version=7.1-preview.1",
            json=payload,
            headers={"Accept":"application/json;api-version=7.1-preview.1",
                     "Content-Type":"application/json"}, timeout=TIMEOUT)
        if r.status_code != 200: return None
        res = r.json().get("results",[])
        if not res or not res[0].get("extensions"): return None
        ext = res[0]["extensions"][0]
        pub = ext.get("publisher",{}); ver = (ext.get("versions") or [{}])[0]
        fid = f"{pub.get('publisherName')}.{ext.get('extensionName')}"
        if fid.lower() != pkg.lower(): return None
        src = next((p.get("value") for p in (ver.get("properties") or [])
                    if p.get("key")=="Microsoft.VisualStudio.Services.Links.Source"),"N/A")
        inst = next((int(s.get("value",0)) for s in (ext.get("statistics") or [])
                     if s.get("statisticName")=="install"),0)
        pub_display  = pub.get("displayName") or pub.get("publisherName","—")
        last_updated = ver.get("lastUpdated","") or "—"
        # Library shows just the extension name; publisher stays in Maintainer
        # Source button → always the VS Code Marketplace page
        return _row(ext.get("extensionName", fid), "VS Code Marketplace",
                    ver.get("version","N/A"),
                    ext.get("shortDescription",""), "—", inst,
                    _m_auto(pub_display), "—",
                    f"https://marketplace.visualstudio.com/items?itemName={fid}",
                    last_updated=last_updated)

    def search(self, q, **kw):
        payload = {"filters":[{"criteria":[{"filterType":10,"value":q}],
                               "pageSize":SEARCH_LIMIT,"pageNumber":1}],"flags":514}
        r = requests.post(
            "https://marketplace.visualstudio.com/_apis/public/gallery/"
            "extensionquery?api-version=7.1-preview.1",
            json=payload,
            headers={"Accept":"application/json;api-version=7.1-preview.1",
                     "Content-Type":"application/json"}, timeout=TIMEOUT)
        if r.status_code != 200: return []
        res = r.json().get("results",[])
        if not res: return []
        out = []
        for ext in res[0].get("extensions",[]):
            pub  = ext.get("publisher",{}); ver = (ext.get("versions") or [{}])[0]
            inst = next((int(s.get("value",0)) for s in (ext.get("statistics") or [])
                         if s.get("statisticName")=="install"),0)
            pub_display = pub.get("displayName") or pub.get("publisherName","—")
            _fid = f"{pub.get('publisherName')}.{ext.get('extensionName')}"
            out.append(_row(ext.get("extensionName", _fid),
                            "VS Code Marketplace", ver.get("version","N/A"),
                            ext.get("shortDescription",""), "—", inst,
                            _m_auto(pub_display), "—",
                            f"https://marketplace.visualstudio.com/items?itemName={_fid}",
                            last_updated=ver.get("lastUpdated","") or "—"))
        return out


# ── Tier 2 (optional keys) ─────────────────────────────────────────────────────

class GHCRAdapter(BaseAdapter):
    def fetch(self, pkg, token=None, **kw):
        if not token or "/" not in pkg: return None
        owner,p = pkg.split("/",1)
        h = {"Authorization":f"Bearer {token}"}
        for ent in ["orgs","users"]:
            r = requests.get(
                f"https://api.github.com/{ent}/{owner}/packages/container/{p}/versions",
                headers=h, timeout=TIMEOUT)
            if r.status_code == 200:
                versions_data = r.json()
                v = versions_data[0].get("name","N/A") if versions_data else "N/A"
                # GitHub Packages API returns updated_at + created_at per version
                lu = (versions_data[0].get("updated_at") or
                      versions_data[0].get("created_at") or "—") if versions_data else "—"
                m = _m_org(owner) if ent == "orgs" else _m_user(owner)
                # Library shows just the image name; owner stays in Maintainer.
                # GHCR owner is already a GitHub org/user — perfect for country.
                return _row(p, "GHCR", v,
                            "GitHub Container Registry", "—", 0, m, "—",
                            f"https://ghcr.io/{pkg}",
                            last_updated=lu,
                            gh_owner=owner)
        return None


class KaggleAdapter(BaseAdapter):
    def fetch(self, pkg, kaggle_username=None, kaggle_key=None, **kw):
        if not kaggle_username or not kaggle_key: return None
        r = requests.get(
            f"https://www.kaggle.com/api/v1/datasets/list?search={pkg}&page=1&pageSize=1",
            auth=(kaggle_username,kaggle_key), timeout=TIMEOUT)
        if r.status_code != 200: return None
        res = r.json()
        if not res: return None
        d   = res[0]; ref = d.get("ref",pkg)
        owner = ref.split("/")[0] if "/" in ref else "—"
        dataset_name = ref.split("/")[-1] if "/" in ref else ref
        lud = str(d.get("lastUpdated","")) or "—"
        # Library shows just the dataset name; owner stays in Maintainer
        return _row(dataset_name, "Kaggle", lud[:10],
                    d.get("subtitle",""), "—", d.get("downloadCount",0),
                    _m_user(owner), "—", f"https://kaggle.com/datasets/{ref}",
                    last_updated=lud)

    def search(self, q, kaggle_username=None, kaggle_key=None, **kw):
        if not kaggle_username or not kaggle_key: return []
        r = requests.get(
            f"https://www.kaggle.com/api/v1/datasets/list?search={requests.utils.quote(q)}&page=1&pageSize={SEARCH_LIMIT}",
            auth=(kaggle_username,kaggle_key), timeout=TIMEOUT)
        if r.status_code != 200: return []
        return [_row(d.get("ref","?").split("/")[-1], "Kaggle",
                     str(d.get("lastUpdated",""))[:10] or "N/A",
                     d.get("subtitle",""), "—", d.get("downloadCount",0),
                     _m_user(d.get("ref","?").split("/")[0] if "/" in d.get("ref","?") else "—"),
                     "—", f"https://kaggle.com/datasets/{d.get('ref','')}",
                     last_updated=str(d.get("lastUpdated","")) or "—")
                for d in r.json()]


class NexusModsAdapter(BaseAdapter):
    def fetch(self, pkg, nexus_key=None, **kw):
        if not nexus_key or "/" not in pkg: return None
        game,mod_id = pkg.split("/",1)
        r = requests.get(
            f"https://api.nexusmods.com/v1/games/{game}/mods/{mod_id}.json",
            headers={"apikey":nexus_key}, timeout=TIMEOUT)
        if r.status_code != 200: return None
        d = r.json()
        # Library shows just the mod name (Nexus Mods already returns clean name)
        return _row(d.get("name", mod_id), "Nexus Mods", d.get("version","N/A"),
                    d.get("summary",""), "—", d.get("mod_downloads",0),
                    _m_user(d.get("user",{}).get("name","—")), "—",
                    d.get("nexusmods_url","N/A"),
                    last_updated=d.get("updated_timestamp","") or "—")


# ── Linux distros via Repology (APT/Debian, APT/Ubuntu, YUM/Fedora, etc.) ──────
# Repology aggregates packages from 300+ repositories in one API call.
_REPOLOGY_REPOS = {
    # repo key        → (display Registry name, distro label)
    "debian_13":      ("APT/Debian",  "Debian 13 (Trixie)"),
    "debian_12":      ("APT/Debian",  "Debian 12 (Bookworm)"),
    "ubuntu_24_04":   ("APT/Ubuntu",  "Ubuntu 24.04 LTS"),
    "ubuntu_22_04":   ("APT/Ubuntu",  "Ubuntu 22.04 LTS"),
    "fedora_41":      ("YUM/Fedora",  "Fedora 41"),
    "fedora_40":      ("YUM/Fedora",  "Fedora 40"),
    "epel_9":         ("YUM/RHEL",    "RHEL 9 / EPEL"),
    "centos_stream_9":("YUM/CentOS",  "CentOS Stream 9"),
    "alpine_3_21":    ("APK/Alpine",  "Alpine 3.21"),
    "alpine_3_20":    ("APK/Alpine",  "Alpine 3.20"),
    "archlinux":      ("Pacman/Arch", "Arch Linux"),
    "opensuse_tumbleweed":("RPM/openSUSE","openSUSE Tumbleweed"),
}

class LinuxDistribAdapter(BaseAdapter):
    """
    Covers APT (Debian/Ubuntu), YUM/DNF (Fedora/RHEL/CentOS), Alpine, Arch, openSUSE
    via Repology API — one call, all distributions.
    """
    TTL = 86400

    @staticmethod
    def _debian_upload_date(pkg: str, version: str) -> str:
        """
        Look up the upload date for a Debian package version via snapshot.debian.org.
        Repology itself doesn't expose dates, but Debian's snapshot archive does.
        Returns ISO date (YYYY-MM-DD) or "—".
        """
        try:
            r = requests.get(
                f"https://snapshot.debian.org/mr/package/{requests.utils.quote(pkg)}/"
                f"{requests.utils.quote(version)}/srcfiles?fileinfo=1",
                timeout=8,
                headers={"User-Agent": "RegistryIntelligencePlatform/1.0"})
            if r.status_code != 200:
                return "—"
            data = r.json().get("fileinfo", {}) or {}
            earliest = None
            for _hash, infos in data.items():
                for info in infos:
                    name       = info.get("name", "")
                    first_seen = info.get("first_seen", "")
                    if not name.endswith(".dsc") or not first_seen:
                        continue
                    if len(first_seen) >= 8 and first_seen[:8].isdigit():
                        iso = f"{first_seen[0:4]}-{first_seen[4:6]}-{first_seen[6:8]}"
                        if earliest is None or iso < earliest:
                            earliest = iso
            return earliest or "—"
        except Exception:
            return "—"

    @staticmethod
    def _arch_last_update(pkg: str) -> str:
        """Arch's official packages API exposes `last_update` per package."""
        try:
            r = requests.get(
                f"https://archlinux.org/packages/search/json/?name={requests.utils.quote(pkg)}",
                timeout=8,
                headers={"User-Agent": "RegistryIntelligencePlatform/1.0"})
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    return (results[0].get("last_update") or "—")
        except Exception:
            pass
        return "—"

    @staticmethod
    def _fedora_last_push(pkg: str) -> str:
        """Bodhi (Fedora's update system) tracks date_pushed per package update."""
        try:
            r = requests.get(
                f"https://bodhi.fedoraproject.org/updates/"
                f"?packages={requests.utils.quote(pkg)}&rows_per_page=1",
                timeout=8,
                headers={"User-Agent": "RegistryIntelligencePlatform/1.0",
                         "Accept": "application/json"})
            if r.status_code == 200:
                updates = r.json().get("updates", [])
                if updates:
                    return (updates[0].get("date_pushed") or
                            updates[0].get("date_submitted") or "—")
        except Exception:
            pass
        return "—"

    def _repology(self, pkg: str) -> list:
        try:
            r = requests.get(
                f"https://repology.org/api/v1/project/{requests.utils.quote(pkg.lower())}",
                timeout=TIMEOUT,
                headers={"User-Agent": "RegistryIntelligencePlatform/1.0"})
            if r.status_code != 200:
                return []
            pkg_l = pkg.lower()
            rows, seen_reg = [], set()
            for entry in r.json():
                repo = entry.get("repo", "")
                if repo not in _REPOLOGY_REPOS:
                    continue
                # Only keep the canonical source package — skip sub-packages
                # like nginx-debug, nginx-doc, libssl-dev etc.
                srcname = entry.get("srcname", "").lower()
                binname = entry.get("binname", "").lower()
                visname = entry.get("visiblename", "").lower()
                # Accept entry if srcname matches AND binname==srcname (main pkg)
                # or visiblename matches (some repos use visiblename as key)
                is_main = (srcname == pkg_l and binname == srcname) or visname == pkg_l
                if not is_main:
                    continue
                reg_name, distro_label = _REPOLOGY_REPOS[repo]
                if reg_name in seen_reg:
                    continue          # one entry per registry type (newest suite)
                seen_reg.add(reg_name)
                version   = entry.get("version", "N/A") or "N/A"
                origver   = entry.get("origversion", "") or version
                maint_raw = ", ".join(entry.get("maintainers", [])[:2]) or "—"
                lic_raw   = ", ".join(entry.get("licenses",   [])[:2]) or "—"
                summary   = entry.get("summary", "—") or "—"

                # Each distro has its own authoritative date source:
                # • Debian / Ubuntu   → snapshot.debian.org `.dsc` first_seen
                # • Arch              → archlinux.org packages API `last_update`
                # • Fedora / RHEL / CentOS → bodhi.fedoraproject.org `date_pushed`
                last_updated = "—"
                if reg_name in ("APT/Debian", "APT/Ubuntu"):
                    last_updated = self._debian_upload_date(pkg.lower(), origver)
                elif reg_name == "Pacman/Arch":
                    last_updated = self._arch_last_update(pkg.lower())
                elif reg_name in ("YUM/Fedora", "YUM/RHEL", "YUM/CentOS"):
                    last_updated = self._fedora_last_push(pkg.lower())

                rows.append(_row(
                    pkg, reg_name, version, summary, lic_raw, 0,
                    _m_auto(maint_raw), "—",
                    f"https://repology.org/project/{pkg}/versions",
                    last_updated=last_updated))
            return rows
        except Exception:
            return []

    def fetch(self, pkg, **kw):
        results = self._repology(pkg)
        return results[0] if results else None

    def search(self, q, **kw):
        return self._repology(q)


# ── Winget (Windows Package Manager) ──────────────────────────────────────────
class WingetAdapter(BaseAdapter):
    """Windows Package Manager via the unofficial-but-stable winget.run community API."""
    TTL = 86400

    def _parse(self, p: dict) -> dict:
        # Actual winget.run v2 schema:
        # { "Id": "Mozilla.Firefox", "Versions": ["125.0.1",...],
        #   "Latest": {"Name":"Mozilla Firefox","Publisher":"Mozilla",
        #              "Description":"...","License":"...","Homepage":"...","Tags":[...]},
        #   "UpdatedAt": "2024-04-22T..." }
        pid    = p.get("Id") or p.get("PackageIdentifier") or p.get("id","?")
        latest = p.get("Latest") or {}
        name   = latest.get("Name") or p.get("Name") or pid
        pub    = latest.get("Publisher") or p.get("Publisher") or ""
        # Version: first item of Versions list (most recent)
        versions = p.get("Versions") or []
        ver    = versions[0] if versions else latest.get("PackageVersion") or "N/A"
        desc   = (latest.get("Description") or p.get("Description") or
                  ", ".join(latest.get("Tags") or []) or "—")
        lic    = latest.get("License") or "—"
        updated  = (p.get("UpdatedAt") or p.get("updatedAt") or "—")[:10]
        m   = _m_org(pub) if pub else "—"
        # Source button → always the winget.run page for this package
        url = (f"https://winget.run/pkg/{pub}/{pid}".replace(" ", "")
               if pub else "https://winget.run/")
        return _row(name, "Winget", ver, desc, lic, 0, m, "—", url, last_updated=updated)

    @staticmethod
    def _winget_score(query: str, raw: dict) -> float:
        """
        Score a raw winget API result dict against the user query.

        Security-researcher standard — NO fuzzy/SequenceMatcher guessing.
        Only deterministic rules that cannot produce false positives:

          Rule 1 — Exact match (after stripping punctuation/case): score 1.0
          Rule 2 — One token fully contains the other (both ≥ 4 chars): score 0.92
          Rule 3 — Full package ID (Publisher.Package) exact match: score 1.0
          Anything else: score 0.0  (reject — never show uncertain data)

        Surfaces checked: display Name, full package Id, Id suffix after last dot.
        Example: "GoAuthing" query vs "z4yx.GoAuthing"
          → id_suffix = "GoAuthing" → stripped = "goauthing" = query → 1.0 ✓
        Example: "GoAuthing" query vs "PaperCutSoftware.NG"
          → id_suffix = "NG" → too short (< 4 chars) for containment check → 0.0 ✓
        """
        q   = re.sub(r"[^a-z0-9]", "", query.lower()).strip()
        if not q:
            return 0.0

        pid    = (raw.get("Id") or raw.get("PackageIdentifier") or
                  raw.get("id") or "").lower()
        latest = raw.get("Latest") or {}
        name   = (latest.get("Name") or raw.get("Name") or pid).lower()
        # The meaningful part after the last dot: "GoAuthing" from "z4yx.GoAuthing"
        id_suffix = pid.split(".")[-1] if "." in pid else pid

        # Also check the full raw query against the full package ID (handles
        # inputs already in "Publisher.Package" format like "z4yx.GoAuthing")
        if re.sub(r"[^a-z0-9.]", "", query.lower()) == pid:
            return 1.0

        # ── DISPLAY NAME GATE ────────────────────────────────────────────────
        # Reject results where the display name doesn't start with the query.
        # Example: query "react" vs name "Win11React" — name doesn't START
        # with "react" (it starts with "Win11"), so this is NOT the package
        # the user wants. The id_suffix may equal "react" but Win11React is
        # a Windows skin, not the React framework.
        #
        # Vendor.Product names like "Mozilla Firefox" / "Microsoft Edge" are
        # still discoverable via the publisher.id route (typing "Mozilla.Firefox"
        # or "Firefox" alone — Firefox matches as the display name itself).
        name_orig = latest.get("Name") or raw.get("Name") or pid
        # First word of the display name (split on whitespace/punctuation/CamelCase)
        first_token = re.split(r'[\s\-_.:]|(?<=[a-z0-9])(?=[A-Z])', name_orig.strip())[0]
        first_token_s = re.sub(r"[^a-z0-9]", "", first_token.lower())
        name_s = re.sub(r"[^a-z0-9]", "", name)
        # Accept only if the display name (or its first token) STARTS with the query
        if name_s and name_s != q and not name_s.startswith(q):
            # Fall back to first-token check: "Firefox" in "Mozilla Firefox"
            # would be caught later via id_suffix — but here we ensure the
            # leading word is at least the query itself.
            if first_token_s != q and not first_token_s.startswith(q):
                # Reject — name has unrelated text before the query word
                return 0.0

        for surface in [name, pid, id_suffix]:
            s = re.sub(r"[^a-z0-9]", "", surface)
            if not s:
                continue
            # Rule 1 — exact match (case-insensitive, punctuation-stripped)
            if q == s:
                return 1.0
            # Rule 2 — PREFIX or SUFFIX match (not arbitrary substring).
            # This catches "react" matching "react-dom" / "reactjs" but
            # blocks "react" matching "Win11React".
            # Both sides must be ≥ 4 chars to avoid noise from short tokens.
            if len(q) >= 4 and len(s) >= 4:
                if q == s or s.startswith(q) or s.endswith(q) or \
                   q.startswith(s) or q.endswith(s):
                    return 0.92
        # No deterministic rule matched → unknown → return 0 (safe default)
        return 0.0

    def _best_match(self, pkg, candidates):
        """
        Return the single best-matching parsed result from a list of raw API dicts.
        Requires score ≥ 0.80 (exact or containment only — see _winget_score).
        Returns None if no candidate meets the bar; never returns uncertain data.
        """
        best_raw, best_score = None, 0.0
        for raw in candidates:
            if not raw:
                continue
            score = self._winget_score(pkg, raw)
            if score > best_score:
                best_score, best_raw = score, raw
        if best_score < 0.80 or best_raw is None:
            return None
        return self._parse(best_raw)

    def fetch(self, pkg, **kw):
        headers = {"User-Agent": "RegistryIntelligencePlatform/1.0"}
        pkg = pkg.strip()

        # ── Stage 1: Exact ID endpoint ────────────────────────────────────
        # Handles inputs already in "Publisher.Package" format (most reliable).
        # Also tried for bare names in case they happen to be valid IDs.
        id_candidates = [pkg]
        # camelCase → "Publisher.PackageName" style: "GoAuthing" stays as-is
        # but also try splitting camelCase: "Go-Authing", "Go Authing"
        spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", pkg)
        hyphen = re.sub(r"([a-z])([A-Z])", r"\1-\2", pkg).lower()
        if spaced != pkg: id_candidates.append(spaced)
        if hyphen != pkg.lower(): id_candidates.append(hyphen)

        for id_val in id_candidates:
            try:
                r = requests.get(
                    f"https://api.winget.run/v2/packages/{requests.utils.quote(id_val)}",
                    timeout=TIMEOUT, headers=headers)
                if r.status_code == 200:
                    d = r.json()
                    if isinstance(d, dict) and ("Id" in d or "PackageIdentifier" in d):
                        # Verify the result actually matches — never blindly accept
                        if self._winget_score(pkg, d) >= 0.80:
                            return self._parse(d)
            except Exception:
                pass

        # ── Stage 2: Search API — 25 results per variant ─────────────────
        # More candidates = more chance of finding the real package.
        all_candidates: list = []
        search_variants = list(dict.fromkeys([pkg, spaced, hyphen]))  # dedup, preserve order
        for variant in search_variants:
            try:
                r = requests.get(
                    f"https://api.winget.run/v2/packages"
                    f"?query={requests.utils.quote(variant)}&limit=25",
                    timeout=TIMEOUT, headers=headers)
                if r.status_code == 200:
                    d = r.json()
                    pkgs = (d if isinstance(d, list)
                            else d.get("Packages") or d.get("packages") or [])
                    if isinstance(pkgs, list):
                        all_candidates.extend(pkgs)
            except Exception:
                continue

        if all_candidates:
            result = self._best_match(pkg, all_candidates)
            if result:
                return result

        # ── Stage 3: GitHub fallback ──────────────────────────────────────
        # winget.run only indexes ~70 % of packages. The official source is
        # microsoft/winget-pkgs on GitHub. The fallback uses GitHub repo search
        # (unauthenticated) to discover publisher→package, then reads the manifest
        # directly. A token unlocks code-search as a final safety net.
        return self._github_manifest_fetch(pkg, kw.get("token"))

    def _github_manifest_fetch(self, pkg: str, token: str = None) -> dict | None:
        """
        Search the official microsoft/winget-pkgs GitHub repo for a package manifest.

        Strategy (no token required for steps 1-3):
          1. GitHub repo search — finds the repo owner for the package → publisher hint
          2. winget.run exact-ID lookup using publisher.package
          3. Raw manifest fetch from microsoft/winget-pkgs using the known path
          4. (Token only) GitHub code search as final fallback
        """
        gh_headers = {"Accept": "application/vnd.github+json",
                      "User-Agent": "RegistryIntelligencePlatform/1.0"}
        if token:
            gh_headers["Authorization"] = f"Bearer {token}"
        wr_headers = {"User-Agent": "RegistryIntelligencePlatform/1.0"}
        pkg_lower  = pkg.lower()

        def _fetch_manifest(publisher: str, pkg_name: str) -> dict | None:
            """
            Fetch the winget manifest for publisher/pkg_name from microsoft/winget-pkgs.

            Returns:
              - Full _row() dict on success
              - Minimal _row() dict if manifest YAML is unreachable but version is known
              - None if the package definitively does not exist (404) or rate-limited
                (caller's Step 4 guaranteed-fallback handles the rate-limit case)
            """
            letter       = publisher[0].lower()
            pkg_tree_url = (
                f"https://github.com/microsoft/winget-pkgs/tree/master"
                f"/manifests/{letter}/{publisher}/{pkg_name}"
            )
            contents_url = (
                f"https://api.github.com/repos/microsoft/winget-pkgs/contents"
                f"/manifests/{letter}/{publisher}/{pkg_name}"
            )
            try:
                cr = requests.get(contents_url, headers=gh_headers, timeout=TIMEOUT)
                if cr.status_code == 404:
                    # Definitively not in winget-pkgs
                    return None
                if cr.status_code != 200:
                    # Rate-limited or transient error — signal caller with None
                    # so it falls back to the GitHub repo data we already have
                    return None
                entries     = cr.json()
                versions    = sorted(
                    [e["name"] for e in entries if e.get("type") == "dir"],
                    reverse=True
                )
                version_dir = versions[0] if versions else None
            except Exception:
                return None

            if not version_dir:
                return _row(pkg_name, "Winget", "—", "—", "—", 0,
                            _m_user(publisher), "—", pkg_tree_url)

            pkg_id       = f"{publisher}.{pkg_name}"
            manifest_url = (
                f"https://raw.githubusercontent.com/microsoft/winget-pkgs/master"
                f"/manifests/{letter}/{publisher}/{pkg_name}"
                f"/{version_dir}/{pkg_id}.locale.en-US.yaml"
            )
            # raw.githubusercontent.com has no auth requirement and very high limits
            try:
                mr = requests.get(manifest_url, timeout=TIMEOUT)
                if mr.status_code != 200:
                    # Version dir known but YAML unreachable → return partial data
                    return _row(pkg_name, "Winget", version_dir, "—", "—", 0,
                                _m_user(publisher), "—", pkg_tree_url)

                manifest = mr.text
                def _yval(key):
                    m = re.search(rf"^{key}:\s*(.+)$", manifest, re.MULTILINE)
                    return m.group(1).strip() if m else ""

                name        = _yval("PackageName")      or pkg_name
                version     = _yval("PackageVersion")   or version_dir
                description = _yval("ShortDescription") or "—"
                homepage    = _yval("PackageUrl")        or ""
                license_    = _yval("License")           or "—"
                publisher_n = _yval("Publisher")         or publisher
                maintainer  = _m_auto(publisher_n)

                # Source button → always the winget-pkgs manifest tree page
                # (not the homepage, which could be any random vendor site)
                return _row(name, "Winget", version, description, license_,
                            0, maintainer, "—",
                            f"https://winget.run/pkg/{publisher_n}/{pkg_name}".replace(" ", ""))
            except Exception:
                return _row(pkg_name, "Winget", version_dir, "—", "—", 0,
                            _m_user(publisher), "—", pkg_tree_url)

        # ── Step 1: GitHub REPO search — name-exact, unauthenticated ────────
        # "+in:name" restricts matches to repos whose NAME equals the query,
        # eliminating repos that merely mention the package in description/readme.
        # We do TWO passes over the results:
        #   Pass A — try each repo as a winget publisher; return immediately on
        #            confirmed match (winget.run ID found OR manifest in winget-pkgs)
        #   Pass B — if nothing confirmed, return the highest-starred exact-name
        #            repo as a "best-effort" result so the user sees SOMETHING
        #            rather than "No matches found". This is clearly labelled
        #            with version "—" to show the data is incomplete.
        best_fallback_row  = None   # Pass B candidate
        try:
            repo_url = (
                f"https://api.github.com/search/repositories"
                f"?q={requests.utils.quote(pkg)}+in:name&per_page=10&sort=stars"
            )
            rr = requests.get(repo_url, headers=gh_headers, timeout=TIMEOUT)
            if rr.status_code == 200:
                repo_items = rr.json().get("items", [])

                # ── Pass A: look for confirmed winget package ──────────────
                for repo in repo_items:
                    owner         = repo.get("owner", {}).get("login", "")
                    repo_name     = repo.get("name", "")
                    repo_url_html = repo.get("html_url", "")
                    repo_desc     = (repo.get("description") or "").strip() or "—"

                    if repo_name.lower() != pkg_lower:
                        continue

                    # Save first exact-name repo as Pass B fallback.
                    # Extract every available field from the GitHub API response so
                    # the user sees real data rather than a row of "—" dashes.
                    if best_fallback_row is None:
                        _gh_license   = ((repo.get("license") or {}).get("spdx_id") or "—")
                        _gh_pushed    = repo.get("pushed_at") or "—"   # ISO-8601 → _fmt_date
                        _gh_stars     = repo.get("stargazers_count") or 0
                        _gh_topics    = ", ".join(repo.get("topics") or [])
                        _gh_lang      = repo.get("language") or ""
                        # Enrich description with language / topics if repo gave none
                        if repo_desc == "—":
                            if _gh_lang:
                                repo_desc = f"{_gh_lang} project"
                            elif _gh_topics:
                                repo_desc = _gh_topics[:72]
                        # ── Fetch latest version (release tag, then tag fallback) ──
                        # The repos endpoint doesn't include version info, so we make
                        # a follow-up call. Most popular projects publish releases;
                        # for those without, we fall back to the latest tag.
                        _gh_version = "—"
                        try:
                            _rel = requests.get(
                                f"https://api.github.com/repos/{owner}/{repo_name}/releases/latest",
                                headers=gh_headers, timeout=6)
                            if _rel.status_code == 200:
                                _gh_version = (_rel.json().get("tag_name") or
                                               _rel.json().get("name") or "—")
                            elif _rel.status_code == 404:
                                # No releases — try tags as fallback
                                _tag = requests.get(
                                    f"https://api.github.com/repos/{owner}/{repo_name}/tags?per_page=1",
                                    headers=gh_headers, timeout=6)
                                if _tag.status_code == 200:
                                    _tags = _tag.json()
                                    if _tags:
                                        _gh_version = _tags[0].get("name", "—")
                        except Exception:
                            pass
                        # Clean common version prefix "v"
                        if _gh_version and _gh_version.lower().startswith("v") \
                                and len(_gh_version) > 1 and _gh_version[1].isdigit():
                            _gh_version = _gh_version[1:]
                        best_fallback_row = _row(
                            repo_name, "GitHub", _gh_version or "—",
                            repo_desc, _gh_license, _gh_stars,
                            _m_user(owner), "—",
                            repo_url_html,
                            last_updated=_gh_pushed
                        )

                    # Try exact winget.run ID: "{owner}.{package}"
                    # MUST verify the returned package actually matches the query —
                    # winget.run can return a different package from the same publisher
                    # (e.g. "Microsoft.GoAuthing" → returns Microsoft OpenJDK).
                    wid = f"{owner}.{repo_name}"
                    try:
                        wr = requests.get(
                            f"https://api.winget.run/v2/packages/{requests.utils.quote(wid)}",
                            headers=wr_headers, timeout=TIMEOUT
                        )
                        if wr.status_code == 200:
                            d = wr.json()
                            if isinstance(d, dict) and ("Id" in d or "PackageIdentifier" in d):
                                if self._winget_score(pkg, d) >= 0.80:
                                    return self._parse(d)   # confirmed + verified ✓
                    except Exception:
                        pass

                    # Try manifest path in microsoft/winget-pkgs
                    result = _fetch_manifest(owner, repo_name)
                    if result:
                        # Patch last-updated from GitHub push date if the manifest
                        # YAML didn't supply it — no extra API call needed.
                        if result.get("Last Updated") in ("—", None, ""):
                            _pushed = repo.get("pushed_at") or ""
                            if _pushed:
                                result["Last Updated"] = _fmt_date(_pushed)
                        return result               # confirmed via winget-pkgs ✓

                # ── Pass B: guaranteed fallback (first exact-name GitHub repo) ─
                # We found a real GitHub repo whose name exactly matches the query
                # but couldn't reach the winget manifest (rate limit, not submitted
                # to winget, etc.). Return the GitHub repo data so the user gets
                # the correct maintainer and link, not "No matches found".
                if best_fallback_row is not None:
                    return best_fallback_row
        except Exception:
            pass

        # ── Step 4 (token only): GitHub CODE search for manifest path ─────────
        if not token:
            return None
        try:
            search_url = (
                f"https://api.github.com/search/code"
                f"?q={requests.utils.quote(pkg)}+in:path"
                f"+path:manifests+repo:microsoft/winget-pkgs"
                f"&per_page=5"
            )
            sr = requests.get(search_url, headers=gh_headers, timeout=TIMEOUT)
            if sr.status_code != 200:
                return None

            items = sr.json().get("items", [])
            if not items:
                return None

            best_path = None
            for item in items:
                path  = item.get("path", "")
                parts = path.split("/")
                if len(parts) >= 5 and parts[3].lower() == pkg_lower:
                    best_path = path
                    break
                if len(parts) >= 5 and pkg_lower in parts[3].lower():
                    best_path = best_path or path

            if not best_path:
                return None

            parts     = best_path.split("/")
            publisher = parts[2]
            pkg_name  = parts[3]
            return _fetch_manifest(publisher, pkg_name)
        except Exception:
            return None

    def search(self, q, **kw):
        try:
            r = requests.get(
                f"https://api.winget.run/v2/packages?query={requests.utils.quote(q)}&limit={SEARCH_LIMIT}",
                timeout=TIMEOUT,
                headers={"User-Agent":"RegistryIntelligencePlatform/1.0"})
            if r.status_code != 200:
                return []
            d = r.json()
            pkgs = (d if isinstance(d, list) else
                    d.get("Packages") or d.get("packages") or [])
            return [self._parse(p) for p in pkgs[:SEARCH_LIMIT] if p]
        except Exception:
            return []


# ── Chrome Web Store ───────────────────────────────────────────────────────────
class ChromeWebStoreAdapter(BaseAdapter):
    """
    Chrome Web Store — uses the store's internal detail endpoint.
    Fetch by extension ID; search falls back to the CWS search page JSON.
    """
    TTL = 86400
    _DETAIL = ("https://chrome.google.com/webstore/ajax/item"
               "?hl=en-US&gl=US&pv=20210820"
               "&mce=atf,nav,pid,rtr,rlb,svp,wtd,rae,hcr,bm,mos,sc,iap"
               "&action=detail&id={id}")
    _SEARCH = ("https://chrome.google.com/webstore/ajax/item"
               "?hl=en-US&gl=US&pv=20210820"
               "&mce=atf,nav,pid,rtr,rlb,svp,wtd,rae,hcr,bm,mos,sc,iap"
               "&action=search&count=5&q={q}")

    def _parse_response(self, raw: str) -> list:
        """CWS returns )]}'\n then JSON — strip the XSSI prefix."""
        import re as _re
        text = re.sub(r"^\)\]\}'\\?\n?", "", raw.strip(), flags=re.MULTILINE)
        try:
            data = json.loads(text)
        except Exception:
            return []
        # data[0][1] is typically a list of extension entries
        items = []
        try:
            for item in (data[0][1] or []):
                try:
                    ext_id   = item[0]
                    name     = item[1]
                    desc     = item[6] or "—"
                    author   = item[8] or "—"
                    version  = item[7] or "N/A"
                    rating   = str(round(float(item[12] or 0), 1)) if item[12] else "—"
                    users    = int(item[23] or 0) if item[23] else 0
                    icon_url = item[3] or ""
                    store_url= f"https://chromewebstore.google.com/detail/{ext_id}"
                    items.append(_row(
                        name, "Chrome Web Store", version,
                        f"{desc} (Rating: {rating}/5)", "—",
                        users, _m_auto(author), "—", store_url, last_updated="—"))
                except (IndexError, TypeError):
                    continue
        except (IndexError, TypeError):
            pass
        return items

    def fetch(self, pkg, **kw):
        # pkg is treated as extension ID if it looks like one (32 char alphanum)
        import re as _re
        if re.match(r'^[a-z]{32}$', pkg.lower()):
            try:
                r = requests.get(self._DETAIL.format(id=pkg), timeout=TIMEOUT,
                                 headers={"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; "
                                          "Win64; x64) AppleWebKit/537.36")})
                if r.status_code == 200:
                    items = self._parse_response(r.text)
                    return items[0] if items else None
            except Exception:
                pass
        return None

    def search(self, q, **kw):
        try:
            r = requests.get(
                self._SEARCH.format(q=requests.utils.quote(q)),
                timeout=TIMEOUT,
                headers={"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; "
                         "Win64; x64) AppleWebKit/537.36")})
            if r.status_code == 200:
                return self._parse_response(r.text)[:SEARCH_LIMIT]
        except Exception:
            pass
        return []


# ── JFrog Artifactory ──────────────────────────────────────────────────────────
class ArtifactoryAdapter(BaseAdapter):
    """
    JFrog Artifactory — uses the Artifactory REST API.
    Requires: instance URL (e.g. https://mycompany.jfrog.io/artifactory)
    Optional: API key or username:password for authenticated repos.
    """
    TTL = 3600

    def __init__(self, url: str, api_key: str = ""):
        self.base   = url.rstrip("/")
        self.api_key= api_key
        self._hdrs  = {"X-JFrog-Art-Api": api_key} if api_key else {}

    def _search(self, pkg: str) -> list:
        try:
            r = requests.get(
                f"{self.base}/api/search/artifact",
                params={"name": pkg, "repos": ""},
                headers=self._hdrs, timeout=TIMEOUT)
            if r.status_code != 200:
                return []
            results = []
            for item in r.json().get("results", [])[:SEARCH_LIMIT]:
                uri   = item.get("uri","")
                fname = uri.split("/")[-1] if uri else pkg
                # Fetch item properties for version/size/dates
                ver, dl, lu = "N/A", 0, "—"
                try:
                    rp = requests.get(uri, headers=self._hdrs, timeout=5)
                    if rp.status_code == 200:
                        info = rp.json()
                        ver  = info.get("checksums",{}).get("sha1","N/A")[:8]
                        dl   = info.get("size", 0)
                        # Artifactory exposes lastUpdated + lastModified
                        lu   = (info.get("lastUpdated") or
                                info.get("lastModified") or "—")
                except Exception:
                    pass
                results.append(_row(
                    fname, "Artifactory", ver, "—", "—", dl,
                    "—", "—", uri, last_updated=lu))
            return results
        except Exception:
            return []

    def fetch(self, pkg, **kw):
        r = self._search(pkg)
        return r[0] if r else None

    def search(self, q, **kw):
        return self._search(q)


# ── Sonatype Nexus Repository ──────────────────────────────────────────────────
class NexusRepositoryAdapter(BaseAdapter):
    """
    Sonatype Nexus Repository OSS / Pro.
    Requires: instance URL (e.g. https://nexus.mycompany.com)
    Optional: username:password for authenticated repos.
    """
    TTL = 3600

    def __init__(self, url: str, credentials: str = ""):
        self.base = url.rstrip("/")
        self.auth = None
        if credentials and ":" in credentials:
            u, p = credentials.split(":", 1)
            self.auth = (u, p)

    def _search(self, q: str) -> list:
        try:
            r = requests.get(
                f"{self.base}/service/rest/v1/search",
                params={"name": q, "sort": "version", "direction": "desc"},
                auth=self.auth, timeout=TIMEOUT)
            if r.status_code != 200:
                return []
            results = []
            for item in r.json().get("items", [])[:SEARCH_LIMIT]:
                name    = item.get("name","?")
                version = item.get("version","N/A")
                repo    = item.get("repository","")
                fmt     = item.get("format","")
                assets  = item.get("assets",[])
                dl_url  = assets[0].get("downloadUrl","N/A") if assets else "N/A"
                # Nexus asset has lastModified / blobCreated timestamps
                lu = "—"
                if assets:
                    lu = (assets[0].get("lastModified") or
                          assets[0].get("blobCreated")  or "—")
                m = _m_auto(item.get("group","") or "—")
                results.append(_row(
                    name, "Nexus Repository", version,
                    f"Format: {fmt} · Repo: {repo}", "—", 0,
                    m, "—", dl_url, last_updated=lu))
            return results
        except Exception:
            return []

    def fetch(self, pkg, **kw):
        r = self._search(pkg)
        return r[0] if r else None

    def search(self, q, **kw):
        return self._search(q)


# ── AWS ECR Public Gallery ─────────────────────────────────────────────────────
class ECRPublicAdapter(BaseAdapter):
    """
    Amazon ECR Public Gallery — public container images, no AWS credentials needed
    for searching the public gallery (uses anonymous access token from Cognito).
    """
    TTL = 3600
    _AUTH_URL = ("https://public.ecr.aws/token/?service=public.ecr.aws"
                 "&scope=repository:*:pull")
    _API       = "https://api.us-east-1.gallery.ecr.aws"

    def _token(self) -> str:
        """Get anonymous pull token for public ECR gallery."""
        try:
            r = requests.get(self._AUTH_URL, timeout=8)
            if r.status_code == 200:
                return r.json().get("token","")
        except Exception:
            pass
        return ""

    def _hdrs(self) -> dict:
        tok = self._token()
        return {"Authorization": f"Bearer {tok}"} if tok else {}

    def _parse(self, repo: dict) -> dict:
        alias  = repo.get("registryAliasName","")
        name   = repo.get("repositoryName","?")
        desc   = repo.get("repositoryDescription","—") or "—"
        stars  = repo.get("starCount",0) or 0
        pulls  = repo.get("downloadCount",0) or 0
        logo   = repo.get("logoImageBlob","")
        url    = f"https://gallery.ecr.aws/{alias}/{name}" if alias else f"https://gallery.ecr.aws/{name}"
        m      = _m_org(alias) if alias else "—"
        # Library shows just the repo name; alias stays in Maintainer
        return _row(name, "ECR Public", "latest",
                    desc, "—", pulls, m, "—", url, last_updated="—")

    def fetch(self, pkg, **kw):
        # pkg can be "alias/repo" or just "repo"
        try:
            parts = pkg.split("/",1)
            alias = parts[0] if len(parts)==2 else ""
            repo  = parts[-1]
            ep    = f"{self._API}/repositoryCatalogData/{alias}/{repo}" if alias else \
                    f"{self._API}/repositoryCatalogData/{repo}"
            r = requests.get(ep, headers=self._hdrs(), timeout=TIMEOUT)
            if r.status_code == 200:
                return self._parse(r.json())
        except Exception:
            pass
        return None

    def search(self, q, **kw):
        try:
            r = requests.post(
                f"{self._API}/searchRepositories",
                json={"searchTerm": q},
                headers={**self._hdrs(), "Content-Type":"application/json"},
                timeout=TIMEOUT)
            if r.status_code == 200:
                repos = r.json().get("repositoryCatalogSearchResultList",[])
                return [self._parse(repo) for repo in repos[:SEARCH_LIMIT]]
        except Exception:
            pass
        return []


class GitHubRepoAdapter(BaseAdapter):
    """Show the top-matching GitHub repository for a package name."""

    def _latest_release_tag(self, full_name: str, headers: dict) -> str:
        """Return the latest release tag, or '' if none exist."""
        try:
            r = requests.get(
                f"https://api.github.com/repos/{full_name}/releases/latest",
                headers=headers, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json().get("tag_name", "")
        except Exception:
            pass
        return ""

    def fetch(self, pkg: str, **kw) -> "dict | None":
        token = kw.get("token", "")
        headers = {"Accept": "application/vnd.github+json",
                   "User-Agent": "RegistryIntelligencePlatform/1.0"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        # Try exact owner/repo first if user passed a full path like "axios/axios"
        if "/" in pkg:
            r = requests.get(f"https://api.github.com/repos/{pkg}",
                             headers=headers, timeout=TIMEOUT)
            if r.status_code == 200:
                repo = r.json()
                tag  = self._latest_release_tag(pkg, headers)
                return self._row_from(repo, tag)
            return None

        # Search for repos — prefer exact name match, else highest-starred
        # Retry once on rate-limit (403/429): parallel adapter threads can
        # collectively hit GitHub Search's 30 req/min limit.
        for _attempt in range(2):
            try:
                r = requests.get(
                    f"https://api.github.com/search/repositories"
                    f"?q={requests.utils.quote(pkg)}+in:name&sort=stars&per_page=10",
                    headers=headers, timeout=TIMEOUT)
                if r.status_code == 200:
                    items = r.json().get("items", [])
                    if not items:
                        return None
                    exact = next((i for i in items if i["name"].lower() == pkg.lower()), None)
                    repo  = exact or items[0]
                    tag   = self._latest_release_tag(repo.get("full_name", ""), headers)
                    return self._row_from(repo, tag)
                if r.status_code in (403, 429) and _attempt == 0:
                    import time as _time; _time.sleep(2)
                    continue
                return None
            except Exception:
                return None
        return None

    def _row_from(self, repo: dict, release_tag: str = "") -> dict:
        owner     = repo.get("owner", {})
        owner_login = owner.get("login", "")
        owner_type  = owner.get("type", "User")
        maintainer  = _m_org(owner_login) if owner_type == "Organization" else _m_user(owner_login)
        license_val = (repo.get("license") or {}).get("spdx_id") or "—"
        if license_val in ("NOASSERTION", "OTHER", ""):
            license_val = "—"
        last_updated = (repo.get("updated_at") or "—")[:10]
        stars        = repo.get("stargazers_count", 0)
        version      = release_tag or repo.get("default_branch", "N/A")
        return _row(
            repo.get("name", ""),
            "GitHub",
            version,
            repo.get("description") or "—",
            license_val,
            stars,
            maintainer,
            "—",
            repo.get("html_url", ""),
            last_updated=last_updated,
            gh_owner=owner_login,
        )

    def search(self, q: str, **kw):
        token = kw.get("token", "")
        headers = {"Accept": "application/vnd.github+json",
                   "User-Agent": "RegistryIntelligencePlatform/1.0"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            r = requests.get(
                f"https://api.github.com/search/repositories"
                f"?q={requests.utils.quote(q)}+in:name&sort=stars&per_page={SEARCH_LIMIT}",
                headers=headers, timeout=TIMEOUT)
            if r.status_code != 200:
                return []
            return [self._row_from(i, self._latest_release_tag(i.get("full_name",""), headers))
                    for i in r.json().get("items", [])]
        except Exception:
            return []


# ── Scan engine ────────────────────────────────────────────────────────────────
TIER1 = [
    PyPIAdapter(), NPMAdapter(), RubyGemsAdapter(), CratesAdapter(), PackagistAdapter(),
    MavenAdapter(), NuGetAdapter(), GoModulesAdapter(), HomebrewAdapter(),
    DockerHubAdapter(), HuggingFaceAdapter(), WordPressAdapter(),
    TerraformAdapter(), AnsibleGalaxyAdapter(), ChocolateyAdapter(), VSCodeAdapter(),
    # New registries
    LinuxDistribAdapter(), WingetAdapter(), ChromeWebStoreAdapter(), ECRPublicAdapter(),
    GitHubRepoAdapter(),
]

def run_audit(query, github_token=None, kaggle_username=None, kaggle_key=None,
              nexus_key=None, artifactory_url=None, artifactory_key=None,
              nexus_repo_url=None, nexus_repo_creds=None):
    search_mode = _is_search(query)
    adapters    = TIER1[:]
    if github_token:                      adapters.append(GHCRAdapter())
    if kaggle_username and kaggle_key:    adapters.append(KaggleAdapter())
    if nexus_key:                         adapters.append(NexusModsAdapter())
    if artifactory_url:                   adapters.append(ArtifactoryAdapter(artifactory_url, artifactory_key or ""))
    if nexus_repo_url:                    adapters.append(NexusRepositoryAdapter(nexus_repo_url, nexus_repo_creds or ""))

    kw = {"token":github_token,"kaggle_username":kaggle_username,
          "kaggle_key":kaggle_key,"nexus_key":nexus_key}

    results, errors = [], []

    def _run(adapter):
        name = adapter.__class__.__name__
        pfx  = "s" if search_mode else "e"
        key  = f"{pfx}:{name}:{query}"
        hit  = cache_get(key, adapter.TTL)
        if hit is not None:
            cached = hit if isinstance(hit, list) else [hit]
            if search_mode:
                cached = _filter_search(cached, query)
            else:
                # Non-search mode: validate cached name against query.
                # If stale/wrong result is cached (e.g. "Dax Studio" for "suside"),
                # delete it and fall through to re-fetch via adapter.fetch().
                cached = [r for r in cached
                          if _name_match(query, r.get("Library",""))]
                if not cached:
                    cache_delete(key)   # purge bad entry; re-fetch below
                    hit = None          # fall through to adapter.fetch()
            if hit is not None:
                return cached, None
        try:
            data = adapter.search(query,**kw) if search_mode else \
                   ([r] if (r := adapter.fetch(query,**kw)) else [])
            if search_mode:
                data = _filter_search(data, query)
            if data: cache_set(key, data)
            return data, None
        except Exception as e:
            # Network-level failures (DNS, timeout, SSL, proxy) are silently
            # skipped — they mean the user's machine can't reach that registry,
            # not a bug.  Only real programming errors get surfaced.
            _ename = type(e).__name__
            _emsg  = str(e)
            _network_types = {
                "ConnectionError", "Timeout", "ReadTimeout",
                "ConnectTimeout", "SSLError", "ProxyError",
                "ChunkedEncodingError", "ContentDecodingError",
            }
            if (_ename in _network_types
                    or "NameResolutionError" in _emsg
                    or "Failed to resolve"   in _emsg
                    or "Max retries exceeded" in _emsg
                    or "timed out"           in _emsg.lower()):
                return [], None      # silently treat as "no result"
            return [], f"{name}: {_ename}: {_emsg}"

    with ThreadPoolExecutor(max_workers=16) as ex:
        for fut in as_completed([ex.submit(_run,a) for a in adapters]):
            data, err = fut.result()
            results.extend(data)
            if err: errors.append(err)

    return results, errors, search_mode


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding:0.5rem 0 1rem">
      <div style="color:#06b6d4;font-size:1rem;font-weight:800;letter-spacing:-0.3px">
        🛡️ Registry Intel
      </div>
      <div style="color:#2e6080;font-size:0.7rem;margin-top:0.2rem">
        v2.0 · Security Research Edition
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="sb-label">Live Registries</div>', unsafe_allow_html=True)
    live = [
        ("PyPI","Python"),("NPM","JavaScript"),("RubyGems","Ruby"),
        ("Crates.io","Rust"),("Packagist","PHP"),("Maven Central","Java / JVM"),
        ("NuGet",".NET"),("Go Modules","Go"),("Homebrew","macOS"),
        ("Docker Hub","Containers"),("Hugging Face","ML Models"),
        ("WordPress","WP Plugins"),("Terraform","IaC"),
        ("Ansible Galaxy","Ansible"),("Chocolatey","Windows"),
        ("VS Code","IDE extensions"),
        ("APT/Debian","Debian Linux"),("APT/Ubuntu","Ubuntu Linux"),
        ("YUM/Fedora","Fedora / DNF"),("YUM/RHEL","RHEL / EPEL"),
        ("YUM/CentOS","CentOS Stream"),("APK/Alpine","Alpine Linux"),
        ("Pacman/Arch","Arch Linux"),("RPM/openSUSE","openSUSE"),
        ("Winget","Windows pkgs"),("Chrome Web Store","Browser ext."),
        ("ECR Public","AWS containers"),
    ]
    for name, desc in live:
        st.markdown(
            f'<div class="reg-row">'
            f'<span class="rdot on"></span>'
            f'<span class="reg-name">{name}</span>'
            f'<span class="reg-desc">· {desc}</span>'
            f'</div>', unsafe_allow_html=True)

    st.markdown('<div class="sb-label">Opt-in · Credentials Required</div>', unsafe_allow_html=True)
    for name, desc in [("GHCR","GitHub containers"),("Kaggle","Datasets"),
                        ("Nexus Mods","Game mods"),
                        ("JFrog Artifactory","Private artifacts"),
                        ("Sonatype Nexus","Private artifacts"),
                        ("GAR / ACR","Cloud registries")]:
        st.markdown(
            f'<div class="reg-row">'
            f'<span class="rdot key"></span>'
            f'<span class="reg-name">{name}</span>'
            f'<span class="reg-desc">· {desc}</span>'
            f'</div>', unsafe_allow_html=True)

    st.markdown('<div class="sb-label">No Public API</div>', unsafe_allow_html=True)
    for name in ["Steam Workshop","GitHub Packages (private)"]:
        st.markdown(
            f'<div class="reg-row">'
            f'<span class="rdot off"></span>'
            f'<span style="color:#243850;font-size:0.77rem">{name}</span>'
            f'</div>', unsafe_allow_html=True)

    st.markdown('<div class="sb-label">API Keys & Credentials</div>', unsafe_allow_html=True)
    st.caption("Leave blank to skip that registry.")
    _gh_secret    = st.secrets.get("GITHUB_TOKEN", "") if hasattr(st, "secrets") else ""
    github_token  = st.text_input("GitHub Token → GHCR",   type="password",
                                  placeholder="ghp_…  (auto-loaded from secrets.toml if blank)",
                                  value=_gh_secret)
    kaggle_raw    = st.text_input("Kaggle → username:key", type="password", placeholder="user:key")
    nexus_key     = st.text_input("Nexus Mods API Key",    type="password", placeholder="Your key")

    st.markdown('<div class="sb-label">JFrog Artifactory</div>', unsafe_allow_html=True)
    artifactory_url = st.text_input("Instance URL", placeholder="https://company.jfrog.io/artifactory",
                                    key="art_url")
    artifactory_key = st.text_input("API Key (optional)", type="password",
                                    placeholder="AKCp...", key="art_key")

    st.markdown('<div class="sb-label">Sonatype Nexus Repository</div>', unsafe_allow_html=True)
    nexus_repo_url   = st.text_input("Instance URL", placeholder="https://nexus.company.com",
                                     key="nxs_url")
    nexus_repo_creds = st.text_input("user:password (optional)", type="password",
                                     placeholder="admin:password", key="nxs_creds")

    # ── Custom Rules / Blocklist (CSV or JSON) ────────────────────────────────
    # Users upload their own pattern-based rules that deduct from each package's
    # Risk Score. Matching is shown inline in a new "Custom Flags" column.
    st.markdown('<div class="sb-label">Custom Rules / Blocklist</div>',
                unsafe_allow_html=True)
    st.caption("Upload CSV/JSON. Matches deduct from Risk Score (UTF-8 only).")

    _uploaded_rules = st.file_uploader(
        "Rules file", type=["csv","json"],
        key="custom_rules_upload", label_visibility="collapsed",
        help="Columns: rule_id, name, field, match_type, pattern, severity, [emoji]"
    )
    # Reload only when the filename actually changes (Streamlit reruns happen
    # on every interaction — without this guard we'd re-parse on each rerun)
    if (_uploaded_rules is not None
            and st.session_state.get("custom_rules_filename") != _uploaded_rules.name):
        _new_rules, _new_warns = _load_custom_rules(_uploaded_rules)
        st.session_state["custom_rules"]          = _new_rules
        st.session_state["custom_rules_filename"] = _uploaded_rules.name
        st.session_state["custom_rules_warnings"] = _new_warns

    _loaded_rules = st.session_state.get("custom_rules", [])
    if _loaded_rules:
        st.success(
            f"✓ {len(_loaded_rules)} rule{'s' if len(_loaded_rules) > 1 else ''} "
            f"loaded from `{st.session_state.get('custom_rules_filename','file')}`"
        )
        with st.expander("Preview loaded rules", expanded=False):
            _preview = [
                {"ID": r["rule_id"], "Name": r["name"], "Field": r["field"],
                 "Match": r["match_type"], "Pattern": r["pattern"],
                 "Severity": r["severity"]}
                for r in _loaded_rules
            ]
            st.dataframe(_preview, use_container_width=True, hide_index=True)
        for _w in st.session_state.get("custom_rules_warnings", []):
            st.warning(_w)
        if st.button("Clear rules", key="clear_custom_rules",
                     use_container_width=True):
            for _k in ("custom_rules","custom_rules_filename",
                       "custom_rules_warnings","custom_rules_upload"):
                st.session_state.pop(_k, None)
            st.rerun()

    # ── GitHub Actions Monitor ────────────────────────────────────────────────
    st.markdown('<div class="sb-label">GitHub Actions Monitor</div>', unsafe_allow_html=True)

    _GH_REPO     = "hunter78602/Library-Scanner-Pro"
    _GH_WORKFLOW = "monitor.yml"

    # ── 1. Next Scheduled Run ─────────────────────────────────────────────────
    def _next_scheduled_run_utc():
        _now = datetime.datetime.utcnow()
        for _h in [0, 6, 12, 18]:
            _candidate = _now.replace(hour=_h, minute=0, second=0, microsecond=0)
            if _candidate > _now:
                return _candidate
        return (_now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    _next_utc  = _next_scheduled_run_utc()
    _now_utc   = datetime.datetime.utcnow()
    _ist_delta = datetime.timedelta(hours=5, minutes=30)
    _next_ist  = _next_utc + _ist_delta
    _diff_secs = int((_next_utc - _now_utc).total_seconds())
    _hrs_left  = _diff_secs // 3600
    _mins_left = (_diff_secs % 3600) // 60

    _md(f"""
    <div style="background:#070d1b;border:1px solid #12243d;border-radius:10px;
                padding:0.75rem 1rem;margin-bottom:0.5rem">
      <div style="color:#4a7090;font-size:0.63rem;text-transform:uppercase;
                  letter-spacing:1px">Next Scheduled Run</div>
      <div style="color:#06b6d4;font-size:0.95rem;font-weight:700;margin-top:0.2rem">
        {_next_ist.strftime("%I:%M %p IST")}
      </div>
      <div style="color:#4a6580;font-size:0.72rem;margin-top:0.1rem">
        in {_hrs_left}h {_mins_left}m &nbsp;·&nbsp; 00:00 / 06:00 / 12:00 / 18:00 UTC
      </div>
    </div>
    """)

    # ── 2. Last Run Status ────────────────────────────────────────────────────
    @st.cache_data(ttl=300, show_spinner=False)
    def _fetch_last_workflow_run(token: str = ""):
        try:
            _hdrs = {"Accept": "application/vnd.github+json"}
            if token:
                _hdrs["Authorization"] = f"Bearer {token}"
            _r = requests.get(
                f"https://api.github.com/repos/{_GH_REPO}/actions/workflows/{_GH_WORKFLOW}/runs",
                params={"per_page": 1},
                headers=_hdrs, timeout=8
            )
            if _r.status_code == 200:
                _runs = _r.json().get("workflow_runs", [])
                return _runs[0] if _runs else None
        except Exception:
            pass
        return None

    _last_run = _fetch_last_workflow_run(github_token or "")
    if _last_run:
        _conclusion  = _last_run.get("conclusion") or _last_run.get("status", "unknown")
        _run_number  = _last_run.get("run_number", "?")
        _updated_at  = (_last_run.get("updated_at", "") or "")[:16].replace("T", " ")
        _dur_str     = ""
        try:
            _ts = datetime.datetime.fromisoformat(
                (_last_run.get("run_started_at") or "").replace("Z", "+00:00"))
            _te = datetime.datetime.fromisoformat(
                (_last_run.get("updated_at") or "").replace("Z", "+00:00"))
            _dur = int((_te - _ts).total_seconds())
            _dur_str = f"{_dur // 60}m {_dur % 60}s"
        except Exception:
            pass
        _sc = {"success": "#10b981", "failure": "#ef4444",
               "cancelled": "#f59e0b"}.get(_conclusion, "#94a3b8")
        _se = {"success": "✅", "failure": "❌",
               "cancelled": "⚠️"}.get(_conclusion, "⏳")
        _md(f"""
        <div style="background:#070d1b;border:1px solid #12243d;border-radius:10px;
                    padding:0.75rem 1rem;margin-bottom:0.5rem">
          <div style="color:#4a7090;font-size:0.63rem;text-transform:uppercase;
                      letter-spacing:1px">Last Run &nbsp;·&nbsp; #{_run_number}</div>
          <div style="color:{_sc};font-size:0.88rem;font-weight:700;margin-top:0.2rem">
            {_se} {_conclusion.upper()}
          </div>
          <div style="color:#4a6580;font-size:0.72rem;margin-top:0.1rem">
            {_updated_at} UTC{' &nbsp;·&nbsp; ' + _dur_str if _dur_str else ''}
          </div>
        </div>
        """)
    else:
        st.caption("Add GitHub Token above to see last run status.")

    # ── 3. Manual Trigger Button ──────────────────────────────────────────────
    if github_token:
        if st.button("▶ Run Monitor Now", use_container_width=True,
                     key="_manual_trigger", type="primary"):
            try:
                _tr = requests.post(
                    f"https://api.github.com/repos/{_GH_REPO}/actions/workflows"
                    f"/{_GH_WORKFLOW}/dispatches",
                    json={"ref": "main"},
                    headers={"Authorization": f"Bearer {github_token}",
                             "Accept": "application/vnd.github+json"},
                    timeout=10
                )
                if _tr.status_code == 204:
                    st.success("Workflow triggered!", icon="🚀")
                    st.cache_data.clear()
                else:
                    st.error(f"Failed — HTTP {_tr.status_code}", icon="❌")
            except Exception as _te:
                st.error(f"Error: {_te}", icon="❌")
    else:
        st.caption("Add GitHub Token above to enable manual trigger.")

kaggle_username, kaggle_key_val = "", ""
if kaggle_raw and ":" in kaggle_raw:
    kaggle_username, kaggle_key_val = kaggle_raw.split(":",1)

# ── Hero ───────────────────────────────────────────────────────────────────────
# Dynamic registry count: TIER1 base + any optional adapters active this session
_hero_reg_count = len(TIER1)
if github_token:                       _hero_reg_count += 1
if kaggle_username and kaggle_key_val: _hero_reg_count += 1
if nexus_key:                          _hero_reg_count += 1
if artifactory_url:                    _hero_reg_count += 1
if nexus_repo_url:                     _hero_reg_count += 1

st.markdown(f"""
<div class="hero">
  <div class="hero-inner">
    <div class="hero-top">
      <div class="hero-left">
        <div class="hero-eyebrow">Security Research Platform</div>
        <h1 class="hero-title">Registry <em>Intelligence</em> Platform</h1>
        <p class="hero-sub">
          Real-time CVE auditing &amp; package intelligence across {_hero_reg_count} live registries.
          Pinpoint vulnerable dependencies and unmaintained packages before they reach production.
        </p>
      </div>
      <div class="hero-right">
        <div class="live-badge"><span class="live-dot"></span> Live data · No stale index</div>
        <div style="color:#2e6080;font-size:0.72rem;margin-top:0.3rem">OSV.dev CVE integration</div>
        <div style="color:#2e6080;font-size:0.72rem">Maintainer type detection</div>
      </div>
    </div>
    <hr class="hero-divider">
    <div class="hero-stats">
      <div><div class="hstat-val">27</div><div class="hstat-lbl">Active Registries</div></div>
      <div><div class="hstat-val">8</div><div class="hstat-lbl">CVE Ecosystems</div></div>
      <div><div class="hstat-val">Org / User</div><div class="hstat-lbl">Maintainer Detection</div></div>
      <div><div class="hstat-val">24hr</div><div class="hstat-lbl">Cache TTL</div></div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Scan form ──────────────────────────────────────────────────────────────────
with st.form("scan_form"):
    q = st.text_area(
        "Query",
        placeholder=(
            "Exact  →  rails   |   lodash   |   com.google.guava:guava   |   github.com/gin-gonic/gin\n"
            "Search →  Google Guava   |   image recognition   |   machine learning"
        ),
        height=88, label_visibility="collapsed")
    c1, c2, c3 = st.columns([4, 1.5, 1.5])
    with c1: scan_btn         = st.form_submit_button("🔍  Run Security Scan",    use_container_width=True)
    with c2: clear_btn        = st.form_submit_button("🗑  Clear Cache",          use_container_width=True)
    with c3: clear_country_btn = st.form_submit_button("🗺  Clear Country Cache", use_container_width=True)

if clear_btn:
    cache_clear()
    st.session_state.pop("scan_data",     None)
    st.session_state.pop("scan_errors",   None)
    st.session_state.pop("scan_query",    None)
    st.session_state.pop("profile_cache", None)
    st.session_state.pop("country_df",    None)
    _GH_SEARCH_CACHE.clear()
    # Also wipe all persistent JSON profile cache files
    try:
        for _f in _JSON_CACHE_DIR.glob("*.json"):
            _f.unlink()
    except Exception:
        pass
    st.success("Cache cleared — next scan fetches live data.")

if clear_country_btn:
    country_cache_clear()
    st.session_state.pop("country_df", None)
    _fetch_github_country.clear()
    _country_via_repo_search.clear()
    st.success("Country cache cleared — re-open Supply Chain tab to re-resolve all countries with the latest logic.")

# ── Run scan (persists results so dropdown reruns still show data) ──────────────
if scan_btn and q.strip():
    targets  = [t.strip() for t in q.replace("\n",",").split(",") if t.strip()]
    _tmp_data, _tmp_errs = [], []

    # Compute live adapter count — TIER1 base + any token-gated registries active now
    _n_adapters = len(TIER1)
    if github_token:                            _n_adapters += 1  # GHCR
    if kaggle_username and kaggle_key_val:      _n_adapters += 1  # Kaggle
    if nexus_key:                               _n_adapters += 1  # Nexus Mods
    if artifactory_url:                         _n_adapters += 1  # JFrog Artifactory
    if nexus_repo_url:                          _n_adapters += 1  # Sonatype Nexus
    _q_label = "1 query" if len(targets) == 1 else f"{len(targets)} queries"

    with st.status(
        f"Scanning {_q_label} across {_n_adapters} registries…", expanded=True):
        # Show queue first so user sees all queries that will run in parallel
        for t in targets:
            mode = "Search" if _is_search(t) else "Exact"
            st.write(f"`{mode}` → `{t}`")

        # ── Parallel outer loop ────────────────────────────────────────────
        # Each library still has its own inner 16-thread adapter pool, so this
        # outer pool stays conservative (4 concurrent libraries) to avoid
        # hammering rate-limited registries (npm, GitHub) with 16×4=64 parallel
        # requests per registry. 4× concurrency on 30 libraries = ~5× speedup.
        def _scan_one(t):
            return run_audit(
                t,
                github_token     = github_token     or None,
                kaggle_username  = kaggle_username  or None,
                kaggle_key       = kaggle_key_val   or None,
                nexus_key        = nexus_key        or None,
                artifactory_url  = artifactory_url  or None,
                artifactory_key  = artifactory_key  or None,
                nexus_repo_url   = nexus_repo_url   or None,
                nexus_repo_creds = nexus_repo_creds or None,
            )

        _outer_workers = min(4, len(targets)) or 1
        with ThreadPoolExecutor(max_workers=_outer_workers) as _ex:
            for fut in as_completed([_ex.submit(_scan_one, t) for t in targets]):
                try:
                    hits, errs, _ = fut.result()
                    _tmp_data.extend(hits); _tmp_errs.extend(errs)
                except Exception as _e:
                    _tmp_errs.append(("scan", f"{type(_e).__name__}: {_e}"))

    # Store in session_state then rerun so the results block always renders
    st.session_state["scan_data"]   = _tmp_data
    st.session_state["scan_errors"] = _tmp_errs
    st.session_state["scan_query"]  = q
    st.session_state.pop("profile_cache", None)   # new scan → invalidate profile cache
    st.session_state.pop("country_df",    None)   # new scan → re-fetch country data
    _GH_SEARCH_CACHE.clear()                       # new scan → re-search GitHub for all pkgs
    st.rerun()

elif scan_btn:
    st.warning("Enter a package name or search term above.")

# ── Results (rendered from session_state — survives every dropdown rerun) ───────
if "scan_data" in st.session_state:
    all_data   = st.session_state["scan_data"]
    all_errors = st.session_state.get("scan_errors", [])

    if all_data:
        df = pd.DataFrame(all_data).drop_duplicates(subset=["Library","Registry"])

        # Sort by raw download count so the most popular/widely-used package
        # (e.g. npm axios with 100M+ dl) always appears at the top
        if "_dl_raw" in df.columns:
            df = df.sort_values("_dl_raw", ascending=False)
        else:
            df = df.sort_values(["Registry","Library"])
        df = df.reset_index(drop=True)

        # Drop internal sort key
        if "_dl_raw" in df.columns:
            df = df.drop(columns=["_dl_raw"])

        if "Status" in df.columns and "Maintainer" not in df.columns:
            df.rename(columns={"Status": "Maintainer"}, inplace=True)
        _COLS = ["Library","Registry","Version","Maintainer",
                 "CVEs","License","Downloads","Last Updated","Description","Repo"]
        # Hidden columns kept on df for internal use (country lookup) but
        # never displayed. Must be preserved through the column-subset step.
        _HIDDEN_COLS = ["_gh_owner"]
        for _c in _COLS:
            if _c not in df.columns:
                df[_c] = "—"
        df = df[_COLS + [c for c in _HIDDEN_COLS if c in df.columns]]

        total = len(df)
        regs  = df["Registry"].nunique()
        orgs  = df["Maintainer"].str.startswith("Org").sum()
        users = df["Maintainer"].str.startswith("User").sum()
        vuln_rows = df[df["CVEs"].apply(_has_cve)]
        vuln      = len(vuln_rows)
        secure    = df["CVEs"].eq("None").sum()

        # ── KPI strip (always visible above tabs) ─────────────────────────────
        st.markdown("---")
        k1,k2,k3,k4 = st.columns(4)
        k1.metric("Packages Found",  total)
        k2.metric("Registries Hit",  regs)
        k3.metric("Org Maintained",  int(orgs))
        k4.metric("User Maintained", int(users))
        st.markdown("")

        # ── Tabs ──────────────────────────────────────────────────────────────
        tab_scan, tab_geo, tab_profile = st.tabs(
            ["📦  Scan Results", "🌍  Supply Chain Risk", "👤  Maintainer Profile"]
        )

        # ════════════════════════════════════════════════════════════════════
        # TAB 1 — Scan Results
        # ════════════════════════════════════════════════════════════════════
        with tab_scan:
            # ── Vulnerability Detail card REMOVED per user request ────────────
            # The CVE data is still computed (vuln, vuln_rows, secure) and stays
            # in the main results table's "CVEs" column + the Risk Dashboard's
            # CVE count + the Vulnerability Report CSV export. Just the
            # top-of-page red-card listing is hidden.
            pass

            _sq = [t.strip() for t in
                   st.session_state.get("scan_query","").replace("\n",",").split(",")
                   if t.strip()]
            if any(_is_search(t) for t in _sq):
                st.info("**Search mode** — showing the best match per registry. "
                        "Re-scan with the exact ID for full CVE data.", icon="ℹ️")
            elif df["CVEs"].eq("—").all():
                st.info("CVE auditing covers PyPI, NPM, RubyGems, Crates.io, "
                        "Packagist, Maven, NuGet and Go.", icon="ℹ️")

            st.markdown(
                f'<div class="sec-label">Results &nbsp;·&nbsp;'
                f'<span style="color:#06b6d4;font-family:\'JetBrains Mono\',monospace">'
                f' {total} packages across {regs} registries</span></div>',
                unsafe_allow_html=True)

            # ── Abandoned Package Detection ───────────────────────────────
            # Add Status column based on Last Updated date.
            # Drop internal-only columns from the display copy (they stay on
            # `df` so country enrichment can still use _gh_owner).
            disp_df = df.copy()
            for _hidden in ("_gh_owner",):
                if _hidden in disp_df.columns:
                    disp_df = disp_df.drop(columns=[_hidden])
            disp_df.insert(
                disp_df.columns.get_loc("Last Updated"),
                "Status",
                disp_df["Last Updated"].apply(_pkg_status)
            )

            # ── Phase 2 Risk Suite — compute all 6 new checks ────────────────
            disp_df["License Risk"] = disp_df["License"].apply(_license_risk)
            disp_df["Single Maintainer"] = disp_df.apply(
                lambda r: _single_maintainer_risk(r.get("Maintainer",""),
                                                  r.get("Downloads","")),
                axis=1
            )
            # ── Custom Rules / Blocklist (Phase 2 user-uploaded blocklist) ───
            # If rules have been uploaded via sidebar, compute the Custom Flags
            # column (which rules each package matched) BEFORE Risk Score so
            # the penalty is reflected in the band.
            _active_rules = st.session_state.get("custom_rules", [])
            if _active_rules:
                disp_df["Custom Flags"] = disp_df.apply(
                    lambda r: _custom_flags_display(_custom_rule_match(r, _active_rules)),
                    axis=1
                )

            # Risk Score (composite 0-100) — Country tier will improve it once
            # the user clicks "Load Maintainer Countries" (rerun adds Country col).
            # Custom rules (if any) deduct from the score via the `rules` param.
            disp_df["Risk Score"]   = disp_df.apply(
                lambda r: _risk_score(r, _active_rules), axis=1
            )
            disp_df["Risk"]         = disp_df["Risk Score"].apply(_risk_band)

            # ── Risk Dashboard — summary metrics at the top ──────────────────
            st.markdown(
                '<div class="sec-label">🛡️ Risk Dashboard</div>',
                unsafe_allow_html=True
            )
            _dc1, _dc2, _dc3, _dc4 = st.columns(4)
            _low  = (disp_df["Risk Score"] >= 80).sum()
            _med  = ((disp_df["Risk Score"] >= 60) & (disp_df["Risk Score"] < 80)).sum()
            _high = ((disp_df["Risk Score"] >= 40) & (disp_df["Risk Score"] < 60)).sum()
            _crit = (disp_df["Risk Score"] < 40).sum()
            _dc1.metric("Low Risk",      f"{_low}",   f"{_low/len(disp_df)*100:.0f}%")
            _dc2.metric("Medium Risk",   f"{_med}",   f"{_med/len(disp_df)*100:.0f}%")
            _dc3.metric("High Risk",     f"{_high}",  f"{_high/len(disp_df)*100:.0f}%")
            _dc4.metric("Critical Risk", f"{_crit}",  f"{_crit/len(disp_df)*100:.0f}%")

            # Secondary metric row — license + maintainer signals
            _dc5, _dc6, _dc7 = st.columns(3)
            _safe_lic    = (disp_df["License Risk"] == "✅ Safe").sum()
            _no_lic      = (disp_df["License Risk"] == "❌ Missing").sum()
            _bus_factor  = (disp_df["Single Maintainer"].str.contains("Bus Factor", na=False)).sum()
            _dc5.metric("✅ Safe Licenses", f"{_safe_lic}")
            _dc6.metric("❌ Missing License", f"{_no_lic}")
            _dc7.metric("⚠️ Bus Factor", f"{_bus_factor}",
                        help="Single maintainer + 1M+ downloads — left-pad style risk")

            # Tertiary row — custom-rule metrics (only when rules are loaded)
            if _active_rules:
                _dc9, _dc10 = st.columns(2)
                _flagged = (disp_df["Custom Flags"].astype(str).str.len() > 0).sum()
                _crit_flagged = sum(
                    1 for _, _r in disp_df.iterrows()
                    if any(m["severity"] == "critical"
                           for m in _custom_rule_match(_r, _active_rules))
                )
                _dc9.metric("🎯 Rules Triggered", f"{int(_flagged)}",
                            help="Packages matching at least one custom rule")
                _dc10.metric("🚨 Critical Rule Hits", f"{int(_crit_flagged)}",
                             help="Packages matching at least one critical-severity rule")

            # Top 5 riskiest packages
            if _crit > 0 or _high > 0:
                _riskiest = disp_df.nsmallest(5, "Risk Score")[
                    ["Library","Registry","Risk","Status","License Risk"]
                ].copy()
                with st.expander(f"🔥 Top {len(_riskiest)} riskiest packages", expanded=False):
                    st.dataframe(_riskiest, use_container_width=True, hide_index=True)

            st.markdown("---")

            # Count by status
            _abandoned = (disp_df["Status"] == "🚨 Abandoned").sum()
            _aging     = (disp_df["Status"] == "⚠️ Aging").sum()
            _active    = (disp_df["Status"] == "✅ Active").sum()
            _unknown   = (disp_df["Status"] == "❓ Unknown").sum()

            # Show warning banners
            if _abandoned > 0:
                st.error(
                    f"🚨 **{_abandoned} abandoned package{'s' if _abandoned > 1 else ''}** "
                    f"found — no updates in 2+ years. Consider finding alternatives.",
                    icon="🚨"
                )
            if _aging > 0:
                st.warning(
                    f"⚠️ **{_aging} aging package{'s' if _aging > 1 else ''}** "
                    f"found — last updated between 6 months and 2 years ago.",
                    icon="⚠️"
                )

            # Status filter
            _status_options = ["All", "✅ Active", "⚠️ Aging", "🚨 Abandoned", "❓ Unknown"]
            _status_counts  = {
                "All":           len(disp_df),
                "✅ Active":     _active,
                "⚠️ Aging":      _aging,
                "🚨 Abandoned":  _abandoned,
                "❓ Unknown":    _unknown,
            }
            _sf1, _sf2 = st.columns([2, 3])
            _status_filter = _sf1.selectbox(
                "Filter by package status",
                options=_status_options,
                format_func=lambda x: f"{x}  ({_status_counts[x]})",
                index=0,
                key="status_filter"
            )
            if _status_filter != "All":
                disp_df = disp_df[disp_df["Status"] == _status_filter]

            # Drop the raw numeric Risk Score from the displayed view
            # (the formatted "Risk" column already shows the band + number)
            _display_df = disp_df.drop(columns=["Risk Score"], errors="ignore")

            st.dataframe(_display_df, use_container_width=True, hide_index=True,
                height=min(56+38*len(_display_df), 640),
                column_config={
                    "Risk":         st.column_config.TextColumn("Risk",         width="small"),
                    "Status":       st.column_config.TextColumn("Status",       width="small"),
                    "Library":      st.column_config.TextColumn("Package",      width="medium"),
                    "Registry":     st.column_config.TextColumn("Registry",     width="medium"),
                    "Version":      st.column_config.TextColumn("Version",      width="small"),
                    "Maintainer":   st.column_config.TextColumn("Maintainer",   width="medium"),
                    "Single Maintainer": st.column_config.TextColumn("Bus Risk", width="small"),
                    "CVEs":         st.column_config.TextColumn("CVE IDs",      width="medium"),
                    "License":      st.column_config.TextColumn("License",      width="small"),
                    "License Risk": st.column_config.TextColumn("Lic Risk",     width="small"),
                    "Custom Flags": st.column_config.TextColumn("Custom Flags", width="medium"),
                    "Downloads":    st.column_config.TextColumn("Downloads",    width="small"),
                    "Last Updated": st.column_config.TextColumn("Last Updated", width="small"),
                    "Description":  st.column_config.TextColumn("Description",  width="large"),
                    "Repo":         st.column_config.LinkColumn("Source",
                                        display_text="Open ↗", width="small"),
                })

            # ── Country Intelligence Check ────────────────────────────────
            st.markdown("---")
            with st.expander("🌍 Maintainer Country Intelligence", expanded=False):
                st.caption(
                    "Fetch each maintainer's GitHub profile location and filter "
                    "results by country. Useful for supply-chain compliance, "
                    "geographic trust policies, or regional audits."
                )
                _cc1, _cc2 = st.columns([1, 2])
                _load_btn = _cc1.button(
                    "🌐 Load Maintainer Countries",
                    use_container_width=True,
                    help="Queries GitHub API for each unique maintainer username. "
                         "Results are cached for 2 hours."
                )
                if _load_btn or "country_df" in st.session_state:
                    if _load_btn:
                        with st.spinner("Fetching maintainer locations from GitHub…"):
                            st.session_state["country_df"] = _enrich_countries(
                                df, github_token or ""
                            )
                        st.success("Countries loaded!", icon="🌍")

                    cdf = st.session_state.get("country_df")
                    if cdf is not None and "Country" in cdf.columns:
                        # ── Rate-limit warning ────────────────────────────────
                        _rate_limited = (cdf["Country"] == "⚠️ Rate Limited").any()
                        if _rate_limited:
                            st.error(
                                "**GitHub API rate limit reached** — unauthenticated requests "
                                "are capped at 60/hour. Add a **GitHub Token** in the sidebar "
                                "to raise the limit to 5,000/hour and get accurate results.",
                                icon="🚫"
                            )
                        # ── Country filter multiselect ────────────────────────
                        all_countries = sorted(
                            [c for c in cdf["Country"].unique()
                             if c and c != "⚠️ Rate Limited"],
                            key=lambda x: (x == "Unknown", x == "🌐 Remote / Global", x)
                        )
                        country_display = {c: _fmt_country(c) for c in all_countries}

                        selected = _cc2.multiselect(
                            "Filter by Country",
                            options=all_countries,
                            format_func=lambda c: country_display[c],
                            placeholder="Select countries to include…",
                            help="Leave empty to show all countries."
                        )

                        # ── Unknown toggle ────────────────────────────────────
                        _unk_count = int((cdf["Country"] == "Unknown").sum())
                        _inc_unknown = st.toggle(
                            f"Always include ❓ Unknown ({_unk_count} packages — "
                            f"no traceable location)",
                            value=True,
                            help="Unknown means the maintainer's GitHub profile has no "
                                 "location set. These are worth inspecting — a package "
                                 "with no traceable maintainer origin is a supply-chain risk."
                        )

                        # Apply country filter + Unknown toggle
                        if selected:
                            mask = cdf["Country"].isin(selected)
                            if _inc_unknown:
                                mask = mask | (cdf["Country"] == "Unknown")
                            filtered_cdf = cdf[mask]
                        else:
                            filtered_cdf = cdf  # no filter → show all

                        # ── Country breakdown pill bar ────────────────────────
                        country_counts = cdf["Country"].value_counts()
                        pills_html = " ".join(
                            f'<span style="background:{"#1a0a0a" if c == "Unknown" else "#0a1e36"};'
                            f'border:1px solid {"#3d1212" if c == "Unknown" else "#12243d"};'
                            f'border-radius:12px;padding:0.2rem 0.65rem;font-size:0.72rem;'
                            f'color:#94a3b8;white-space:nowrap">'
                            f'{_flag(c)} {c} <strong style="color:{"#f87171" if c == "Unknown" else "#06b6d4"}">{n}</strong>'
                            f'</span>'
                            for c, n in country_counts.items()
                        )
                        st.markdown(
                            f'<div style="display:flex;flex-wrap:wrap;gap:0.4rem;'
                            f'margin-bottom:0.8rem">{pills_html}</div>',
                            unsafe_allow_html=True
                        )

                        # ── Unknown-only warning ──────────────────────────────
                        if _unk_count > 0:
                            st.warning(
                                f"**{_unk_count} package{'s' if _unk_count > 1 else ''}** "
                                f"{'have' if _unk_count > 1 else 'has'} no traceable maintainer "
                                f"location. Review these manually — an untraceable origin is a "
                                f"supply-chain risk signal.",
                                icon="⚠️"
                            )

                        # ── Filtered table label ──────────────────────────────
                        if selected:
                            _label_countries = ", ".join(_fmt_country(c) for c in selected)
                            _label_unk = " + ❓ Unknown" if _inc_unknown and _unk_count else ""
                            st.markdown(
                                f'<div class="sec-label">Filtered Results &nbsp;·&nbsp;'
                                f'<span style="color:#06b6d4">'
                                f'{len(filtered_cdf)} packages — '
                                f'{_label_countries}{_label_unk}'
                                f'</span></div>',
                                unsafe_allow_html=True
                            )
                        else:
                            st.markdown(
                                f'<div class="sec-label">All Results with Countries'
                                f'&nbsp;·&nbsp;<span style="color:#94a3b8">'
                                f'{len(filtered_cdf)} packages</span></div>',
                                unsafe_allow_html=True
                            )

                        # Dataframe: add a "Flag" image column using flagcdn.com.
                        # Country column stays as plain text ("India", "Russia" etc.)
                        # so no Regional-Indicator emoji rendering issues.
                        # The ImageColumn renders the actual flag PNG inline.
                        disp_cdf = filtered_cdf.copy()
                        disp_cdf.insert(
                            disp_cdf.columns.get_loc("Country"),
                            "Flag",
                            disp_cdf["Country"].apply(_country_flag_url)
                        )

                        _col_cfg = {
                            "Flag":      st.column_config.ImageColumn("",          width="small"),
                            "Library":   st.column_config.TextColumn("Package",    width="medium"),
                            "Registry":  st.column_config.TextColumn("Registry",   width="small"),
                            "Version":   st.column_config.TextColumn("Version",    width="small"),
                            "Maintainer":st.column_config.TextColumn("Maintainer", width="medium"),
                            "Country":   st.column_config.TextColumn("Country",    width="medium"),
                            "CVEs":      st.column_config.TextColumn("CVEs",       width="medium"),
                            "License":   st.column_config.TextColumn("License",    width="small"),
                            "Repo":      st.column_config.LinkColumn(
                                             "Source", display_text="Open ↗", width="small"),
                        }
                        st.dataframe(
                            disp_cdf, use_container_width=True, hide_index=True,
                            height=min(56 + 38 * len(disp_cdf), 540),
                            column_config=_col_cfg
                        )

                        # ── Export filtered results ───────────────────────────
                        _fe1, _fe2 = st.columns(2)
                        _fe1.download_button(
                            "⬇ Export Filtered CSV",
                            filtered_cdf.to_csv(index=False),
                            "maintainers_by_country.csv", "text/csv",
                            use_container_width=True
                        )
                        _fe2.download_button(
                            "⬇ Export Filtered JSON",
                            _clean_for_json_export(filtered_cdf),
                            "maintainers_by_country.json", "application/json",
                            use_container_width=True
                        )

            # ── Standard exports ──────────────────────────────────────────────
            # Build a single enriched frame that merges package data with
            # country intelligence (if already resolved in Tab 2).
            st.markdown("---")

            # Merge country data when available — keyed on Library + Registry
            _export_base = disp_df.copy()
            _geo_cached  = st.session_state.get("country_df")
            if _geo_cached is not None and "Country" in _geo_cached.columns:
                _country_cols = [c for c in ["Library", "Registry", "Country", "Country Tier"]
                                 if c in _geo_cached.columns]
                _country_merge = _geo_cached[_country_cols].drop_duplicates(
                    subset=["Library", "Registry"], keep="first"
                )
                # Drop pre-existing country cols to avoid _x/_y suffixes
                for _cc in ("Country", "Country Tier"):
                    if _cc in _export_base.columns:
                        _export_base = _export_base.drop(columns=[_cc])
                _export_base = _export_base.merge(
                    _country_merge, on=["Library", "Registry"], how="left"
                )
                for _cc in ("Country", "Country Tier"):
                    if _cc in _export_base.columns:
                        _export_base[_cc] = _export_base[_cc].fillna("Unknown")
                # Derive Country Tier from Country (_enrich_countries only adds Country)
                if "Country" in _export_base.columns:
                    _export_base["Country Tier"] = _export_base["Country"].apply(_country_tier)
                # Recompute Risk Score now that Country Tier is available
                _export_base["Risk Score"] = _export_base.apply(
                    lambda r: _risk_score(r, _active_rules), axis=1
                )
                _export_base["Risk"] = _export_base["Risk Score"].apply(_risk_band)

            # ── CSV export: fixed logical column order ──────────────────────
            _csv_col_order = [
                # Identity
                "Library", "Registry", "Version",
                # Activity
                "Status", "Last Updated", "Downloads",
                # Maintainer
                "Maintainer", "Single Maintainer",
                # Country intelligence
                "Country", "Country Tier",
                # Code quality
                "License", "License Risk", "CVEs",
                # Risk
                "Risk", "Risk Score",
                # Other
                "Repo", "Custom Flags",
            ]
            _csv_cols = [c for c in _csv_col_order if c in _export_base.columns]
            # Append any remaining columns not in the ordered list
            _csv_cols += [c for c in _export_base.columns if c not in _csv_cols]
            _csv_export = _export_base[_csv_cols]

            # ── JSON export: structured sections ───────────────────────────
            _strip_emoji_fn = lambda v: re.sub(r'^[^\x00-\x7F\s]+\s*', '', str(v)).strip() \
                                        if isinstance(v, str) else v
            _json_records = []
            for _, _r in _export_base.iterrows():
                _country_val = _r.get("Country", "Unknown") or "Unknown"
                _tier_val    = _r.get("Country Tier", "") or ""
                _tier_clean  = re.sub(r'^[^\x00-\x7F\s]+\s*', '', str(_tier_val)).strip()
                _rec = {
                    "package_info": {
                        "library":   str(_r.get("Library",   "") or ""),
                        "registry":  str(_r.get("Registry",  "") or ""),
                        "version":   str(_r.get("Version",   "") or ""),
                        "repo":      str(_r.get("Repo",      "") or ""),
                        "license":   str(_r.get("License",   "") or ""),
                        "downloads": _r.get("Downloads", None),
                        "last_updated": str(_r.get("Last Updated", "") or ""),
                        "status":    _strip_emoji_fn(_r.get("Status", "")),
                    },
                    "maintainer": {
                        "name":           str(_r.get("Maintainer",       "") or ""),
                        "single_flag":    _strip_emoji_fn(_r.get("Single Maintainer", "")),
                    },
                    "country_intelligence": {
                        "country":    str(_country_val),
                        "tier":       _tier_clean if _tier_clean else "Unknown",
                    },
                    "risk_assessment": {
                        "risk_band":     _strip_emoji_fn(_r.get("Risk",         "")),
                        "risk_score":    _r.get("Risk Score", None),
                        "license_risk":  _strip_emoji_fn(_r.get("License Risk", "")),
                        "cves":          str(_r.get("CVEs", "") or ""),
                        "custom_flags":  str(_r.get("Custom Flags", "") or ""),
                    },
                }
                _json_records.append(_rec)
            _json_str = json.dumps(
                {"scan_results": _json_records,
                 "total_packages": len(_json_records)},
                indent=2, ensure_ascii=False
            )

            e1, e2, e3 = st.columns(3)
            e1.download_button("⬇ Export CSV",  _csv_export.to_csv(index=False),
                               "registry_scan.csv", "text/csv",
                               use_container_width=True)
            e2.download_button("⬇ Export JSON", _json_str,
                               "registry_scan.json", "application/json",
                               use_container_width=True)
            if not vuln_rows.empty:
                e3.download_button("🚨 Vulnerability Report",
                                   vuln_rows.to_csv(index=False),
                                   "vulnerabilities.csv", "text/csv",
                                   use_container_width=True)

        # ════════════════════════════════════════════════════════════════════
        # TAB 2 — Supply Chain Risk Analysis (basic version)
        # ════════════════════════════════════════════════════════════════════
        with tab_geo:
            st.markdown(
                '<div class="sec-label">🌍 Supply Chain Risk Analysis</div>',
                unsafe_allow_html=True
            )
            st.caption(
                "Automatic risk assessment based on the geographic origin of each "
                "package's maintainer / upstream organisation. The lookup runs "
                "automatically — country data is resolved via the 5-layer pipeline "
                "(GitHub repo metadata → curated org map → username variants → repo search)."
            )

            # ── AUTO-LOAD country data if not already cached in session ──────
            # When the user opens this tab, transparently run _enrich_countries
            # so they see results without having to manually click a button on
            # another tab first.
            _geo_df = st.session_state.get("country_df")
            if _geo_df is None or "Country" not in (_geo_df.columns if _geo_df is not None else []):
                with st.spinner("Resolving maintainer countries for geopolitical analysis…"):
                    try:
                        st.session_state["country_df"] = _enrich_countries(
                            df, github_token or ""
                        )
                        _geo_df = st.session_state["country_df"]
                    except Exception as _e:
                        st.error(f"Country resolution failed: {type(_e).__name__}: {_e}",
                                 icon="🚨")
                        _geo_df = None

            # Optional: manual refresh button for re-running the lookup
            _refresh_col, _ = st.columns([1, 4])
            if _refresh_col.button("🔄 Refresh country data", use_container_width=True,
                                   help="Re-runs the country resolution from scratch"):
                with st.spinner("Re-fetching maintainer countries…"):
                    st.session_state["country_df"] = _enrich_countries(
                        df, github_token or ""
                    )
                    _geo_df = st.session_state["country_df"]
                    st.success("Countries refreshed!", icon="🌍")

            if _geo_df is None or "Country" not in _geo_df.columns:
                st.info(
                    "Country data could not be loaded. Make sure you have packages "
                    "in your scan results and that your GitHub token (if configured) "
                    "isn't rate-limited.",
                    icon="ℹ️"
                )
            else:
                # Apply Country Tier classification to every row
                _gdf = _geo_df.copy()
                _gdf["Country Tier"] = _gdf["Country"].apply(_country_tier)
                if "Status" not in _gdf.columns:
                    _gdf["Status"] = _gdf["Last Updated"].apply(_pkg_status)

                # ═══════════════════════════════════════════════════════════════
                # NEW SECTION — Per-Library Security Audit
                # Runs all registered checks (_SECURITY_CHECKS) for every library
                # and shows results as a per-row breakdown.
                # ═══════════════════════════════════════════════════════════════
                st.markdown(
                    '<div class="sec-label">🔍 Per-Library Security Audit</div>',
                    unsafe_allow_html=True
                )
                st.caption(
                    f"Each library is evaluated against {len(_SECURITY_CHECKS)} "
                    "security checks. The overall severity is the **worst** "
                    "result across all checks — a single Critical issue is "
                    "never masked by other passing checks."
                )

                # Run all checks for all rows (cached in session for re-renders)
                _token = (github_token or "")
                with st.spinner("Running security checks…"):
                    _audit_rows = []
                    for _, _row in _gdf.iterrows():
                        results  = _run_security_checks(_row, _token)
                        agg      = _aggregate_severity(results)
                        _audit_rows.append({
                            "Library":   _row.get("Library", ""),
                            "Registry":  _row.get("Registry", ""),
                            "Version":   _row.get("Version", "N/A"),
                            "_row_data": _row.to_dict(),   # full row for evidence extraction
                            **{c["name"]: r["label"]
                               for c, r in zip(_SECURITY_CHECKS, results)},
                            "Overall":   _severity_badge(agg),
                            "_results":  results,
                            "_agg_rank": _SEV_RANK.get(agg, 0),
                        })
                    # Build raised queries from all failed checks and persist across reruns
                    st.session_state["raised_queries"] = _build_raised_queries(_audit_rows)

                # ── Summary metrics across all libraries ──────────────────────
                _audit_df_full = pd.DataFrame(_audit_rows)
                _au_crit = (_audit_df_full["_agg_rank"] == 4).sum()
                _au_high = (_audit_df_full["_agg_rank"] == 3).sum()
                _au_med  = (_audit_df_full["_agg_rank"] == 2).sum()
                _au_low  = (_audit_df_full["_agg_rank"] <= 1).sum()
                _au_tot  = len(_audit_df_full)

                # ── Persist scan to PostgreSQL ────────────────────────────────
                save_scan_history(
                    _audit_rows,
                    st.session_state.get("raised_queries", []),
                    {
                        "total":    int(_au_tot),
                        "critical": int(_au_crit),
                        "high":     int(_au_high),
                        "medium":   int(_au_med),
                        "low":      int(_au_low),
                    },
                )

                _ac1, _ac2, _ac3, _ac4 = st.columns(4)
                _ac1.metric("Critical", f"{int(_au_crit)}",
                            f"{_au_crit/_au_tot*100:.0f}%" if _au_tot else "0%")
                _ac2.metric("High",     f"{int(_au_high)}",
                            f"{_au_high/_au_tot*100:.0f}%" if _au_tot else "0%")
                _ac3.metric("Medium",   f"{int(_au_med)}",
                            f"{_au_med/_au_tot*100:.0f}%" if _au_tot else "0%")
                _ac4.metric("Low/Pass", f"{int(_au_low)}",
                            f"{_au_low/_au_tot*100:.0f}%" if _au_tot else "0%")

                # ── Severity filter ───────────────────────────────────────────
                _sev_filter = st.selectbox(
                    "Show packages with severity ≥",
                    options=["All", "Medium and above", "High and above",
                             "Critical only"],
                    index=0, key="audit_sev_filter"
                )
                _min_rank = {"All": 0, "Medium and above": 2,
                             "High and above": 3, "Critical only": 4}[_sev_filter]
                _filtered_audit = _audit_df_full[_audit_df_full["_agg_rank"] >= _min_rank]

                if _filtered_audit.empty:
                    st.success(
                        f"✅ No packages match the '{_sev_filter}' filter — "
                        "your dependencies are clean at this severity level.",
                        icon="✅"
                    )
                else:
                    # ── Per-library compact table ─────────────────────────────
                    _table_cols = (["Library", "Registry"] +
                                   [c["name"] for c in _SECURITY_CHECKS] +
                                   ["Overall"])
                    _display_audit = _filtered_audit[_table_cols].sort_values(
                        by="Overall", ascending=False
                    )
                    st.dataframe(
                        _display_audit, use_container_width=True, hide_index=True,
                        height=min(56 + 38 * len(_display_audit), 540)
                    )

                    # ── Drill-down: expandable detail per library ─────────────
                    st.markdown("##### 🔎 Per-library details")
                    for _, audit_row in _filtered_audit.iterrows():
                        _agg_emoji = _SEV_EMOJI.get(
                            list(_SEV_RANK.keys())[
                                list(_SEV_RANK.values()).index(int(audit_row["_agg_rank"]))
                            ], "⚪")
                        _label = (f"{_agg_emoji}  **{audit_row['Library']}** "
                                  f"· {audit_row['Registry']} → {audit_row['Overall']}")
                        with st.expander(_label, expanded=False):
                            for chk_meta, result in zip(_SECURITY_CHECKS,
                                                        audit_row["_results"]):
                                st.markdown(
                                    f"**{_severity_badge(result['severity'])}** "
                                    f"· **{chk_meta['name']}** — {result['label']}"
                                )
                                st.caption(f"_{result['details']}_")

                # ── Export the audit results ──────────────────────────────────
                _audit_export = _audit_df_full.drop(
                    columns=["_results", "_agg_rank"], errors="ignore"
                )
                _ae1, _ae2 = st.columns(2)
                _ae1.download_button(
                    "⬇ Export Security Audit (CSV)",
                    _audit_export.to_csv(index=False),
                    "security_audit.csv", "text/csv",
                    use_container_width=True, key="dl_audit_csv"
                )
                _ae2.download_button(
                    "⬇ Export Security Audit (JSON)",
                    json.dumps(_build_supply_chain_json(_audit_rows),
                               indent=2, ensure_ascii=False),
                    "security_audit.json", "application/json",
                    use_container_width=True, key="dl_audit_json"
                )

                # ── 🚨 Raised Queries ─────────────────────────────────────────
                st.markdown(
                    '<div class="sec-label">🚨 Raised Queries</div>',
                    unsafe_allow_html=True,
                )
                st.caption(
                    "A query is automatically raised for every package that fails "
                    "one or more security checks. Each query contains the full JSON "
                    "payload of failed check details for audit, triage, or export."
                )

                _rq = st.session_state.get("raised_queries", [])
                if not _rq:
                    st.success(
                        "✅ No queries raised — all security checks passed.",
                        icon="✅",
                    )
                else:
                    st.error(
                        f"**{len(_rq)} package(s)** triggered failed checks "
                        "and have been raised as queries below.",
                        icon="🚨",
                    )

                    for _q in _rq:
                        _qs    = _q["overall_risk"].get("worst_check_severity") or _q["overall_risk"].get("severity", "pass")
                        _qemj  = _SEV_EMOJI.get(_qs, "🟡")
                        _qlbl  = _SEV_LABEL.get(_qs, _qs.title())
                        _nfail = sum(1 for c in _q["checks"] if c["status"] != "pass")
                        _qttl  = (
                            f"{_qemj} **{_q['library']['name']}** "
                            f"· {_q['library']['registry']} "
                            f"— {_qlbl} "
                            f"({_nfail} check(s) failed) "
                            f"· `{_q['query_id']}`"
                        )
                        with st.expander(_qttl, expanded=False):
                            st.code(
                                json.dumps(_q, indent=2, ensure_ascii=False),
                                language="json",
                            )


                st.markdown("---")

                # ── Section 1: Risk Tier Breakdown ────────────────────────────
                _trusted    = (_gdf["Country Tier"] == "Trusted").sum()
                _caution    = (_gdf["Country Tier"] == "Caution").sum()
                _restricted = (_gdf["Country Tier"] == "Restricted").sum()
                _unrated    = (_gdf["Country Tier"] == "❓ Unrated").sum()
                _total      = len(_gdf)

                st.markdown("#### Risk Tier Breakdown")
                _t1, _t2, _t3, _t4 = st.columns(4)
                _t1.metric("Trusted",    f"{_trusted}",
                           f"{_trusted/_total*100:.0f}%" if _total else "0%")
                _t2.metric("Caution",    f"{_caution}",
                           f"{_caution/_total*100:.0f}%" if _total else "0%")
                _t3.metric("Restricted", f"{_restricted}",
                           f"{_restricted/_total*100:.0f}%" if _total else "0%")
                _t4.metric("❓ Unrated",    f"{_unrated}",
                           f"{_unrated/_total*100:.0f}%" if _total else "0%")

                # ── Section 2: Geopolitical Risk Score ────────────────────────
                # Simple formula: 100 - (restricted% × 1.5) - (unrated% × 0.5)
                # Higher score = lower geopolitical risk
                if _total:
                    _geo_score = max(0, int(100
                                  - (_restricted / _total * 100 * 1.5)
                                  - (_unrated    / _total * 100 * 0.5)))
                else:
                    _geo_score = 100
                if _geo_score >= 90:   _geo_band = "Low geopolitical risk"
                elif _geo_score >= 70: _geo_band = "Moderate geopolitical risk"
                elif _geo_score >= 50: _geo_band = "High geopolitical risk"
                else:                  _geo_band = "Critical geopolitical risk"

                st.markdown("#### Overall Geopolitical Risk Score")
                _g1, _g2 = st.columns([1, 2])
                _g1.metric("Score", f"{_geo_score} / 100", _geo_band)
                _g2.progress(_geo_score / 100,
                             text=f"{_geo_band}  ·  {_total} packages analysed")

                st.markdown("---")

                # ── Section 3: High-Risk Packages (Restricted-tier) ───────────
                _restricted_rows = _gdf[_gdf["Country Tier"] == "Restricted"]
                if not _restricted_rows.empty:
                    st.markdown(
                        f"#### 🚨 High-Risk Packages "
                        f"({len(_restricted_rows)} from restricted countries)"
                    )
                    st.error(
                        f"**{len(_restricted_rows)} package{'s' if len(_restricted_rows)>1 else ''}** "
                        "maintained from countries commonly flagged in compliance/sanctions "
                        "contexts (Russia, China, Iran, North Korea, Belarus, Cuba, Syria, "
                        "Venezuela, Myanmar). Review your organisation's policy before use.",
                        icon="🚨"
                    )
                    _rcols = ["Library","Registry","Country","Maintainer","Version","Last Updated"]
                    _rcols = [c for c in _rcols if c in _restricted_rows.columns]
                    st.dataframe(_restricted_rows[_rcols],
                                 use_container_width=True, hide_index=True)
                    st.markdown("---")

                # ── Section 4: Concentration Risk ─────────────────────────────
                _country_counts = (_gdf["Country"].value_counts())
                if not _country_counts.empty:
                    _top_country     = _country_counts.index[0]
                    _top_country_pct = _country_counts.iloc[0] / _total * 100
                    if _top_country_pct >= 40 and _top_country not in ("Unknown",):
                        st.warning(
                            f"**Concentration risk:** {_top_country_pct:.0f}% of your "
                            f"dependencies ({int(_country_counts.iloc[0])}/{_total}) "
                            f"are maintained from **{_top_country}**. Single-country "
                            "concentration is a supply-chain risk.",
                            icon="⚠️"
                        )

                # ── Section 5: Geographic Distribution chart ──────────────────
                st.markdown("#### Geographic Distribution")
                _dist_df = _country_counts.reset_index()
                _dist_df.columns = ["Country", "Packages"]
                # Add tier for color awareness
                _dist_df["Tier"] = _dist_df["Country"].apply(_country_tier)
                st.bar_chart(_dist_df.set_index("Country")["Packages"],
                             height=300, use_container_width=True)

                # ── Section 6: By-Country Drill-Down ──────────────────────────
                st.markdown("#### By-Country Breakdown")
                for _country in _dist_df["Country"]:
                    _country_rows = _gdf[_gdf["Country"] == _country]
                    _tier = _country_tier(_country)
                    with st.expander(
                        f"{_tier}  ·  {_country}  ·  "
                        f"{len(_country_rows)} package{'s' if len(_country_rows) > 1 else ''}",
                        expanded=False
                    ):
                        _cols = ["Library","Registry","Maintainer","Version","Last Updated"]
                        _cols = [c for c in _cols if c in _country_rows.columns]
                        st.dataframe(_country_rows[_cols],
                                     use_container_width=True, hide_index=True)

                # ── Export ────────────────────────────────────────────────────
                st.markdown("---")
                _geo_export = _gdf[[
                    c for c in ["Library","Registry","Maintainer","Country",
                                "Country Tier","Version","Last Updated"]
                    if c in _gdf.columns
                ]].copy()
                _ge1, _ge2 = st.columns(2)
                _ge1.download_button(
                    "⬇ Export Supply Chain Risk (CSV)",
                    _geo_export.to_csv(index=False),
                    "supply_chain_risk.csv", "text/csv",
                    use_container_width=True
                )
                _ge2.download_button(
                    "⬇ Export Supply Chain Risk (JSON)",
                    _clean_for_json_export(_geo_export),
                    "supply_chain_risk.json", "application/json",
                    use_container_width=True
                )

        # ════════════════════════════════════════════════════════════════════
        # TAB 3 — Maintainer Profile
        # ════════════════════════════════════════════════════════════════════
        with tab_profile:

            # ── helper: build one stat pill (no 4-space indent = no markdown code-block) ──
            def _ov_pill(label, value, bg="#0a1e36", lc="#3d5a75",
                         vc="#94a3b8", vs=""):
                return (
                    f'<div style="background:{bg};border:1px solid #12243d;'
                    f'border-radius:9px;padding:0.35rem 0.6rem;min-width:100px">'
                    f'<div style="color:{lc};font-size:0.58rem;text-transform:uppercase;'
                    f'letter-spacing:1px;margin-bottom:0.08rem">{label}</div>'
                    f'<div style="color:{vc};font-size:0.78rem;font-weight:600;{vs}">{value}</div>'
                    f'</div>'
                )

            _REG_ACCENT = {
                "npm":"#cc3534","pypi":"#3572a5","rubygems":"#cc342d",
                "crates":"#dea584","nuget":"#004880","maven":"#b07219",
                "go modules":"#00acd7","homebrew":"#fbb040","docker hub":"#2496ed",
                "winget":"#0078d4","chrome web store":"#4285f4",
                "apt/debian":"#d70751","apt/ubuntu":"#e95420",
                "yum/fedora":"#3c6eb4","yum/rhel":"#ee0000",
            }
            def _reg_accent(reg):
                r = reg.lower()
                for k, v in _REG_ACCENT.items():
                    if k in r:
                        return v
                return "#06b6d4"

            # ══════════════════════════════════════════════════════════════
            # ALL-REGISTRIES OVERVIEW — one card per result row
            # ══════════════════════════════════════════════════════════════
            st.markdown(
                f'<div class="sec-label">📋 All Registries — Package Overview'
                f'<span style="color:#06b6d4;font-size:0.72rem;margin-left:0.6rem;'
                f'font-weight:400">{len(df)} registr{"y" if len(df)==1 else "ies"}</span>'
                f'</div>',
                unsafe_allow_html=True)

            for _ri, (_ridx, _rrow) in enumerate(df.iterrows()):
                _rv_lib  = str(_rrow.get("Library","—"))
                _rv_reg  = str(_rrow.get("Registry","—"))
                _rv_ver  = str(_rrow.get("Version","N/A"))
                _rv_lic  = str(_rrow.get("License","—"))
                _rv_dl   = str(_rrow.get("Downloads","—"))
                _rv_upd  = str(_rrow.get("Last Updated","—"))
                _rv_desc = str(_rrow.get("Description","") or "—")
                _rv_cves = str(_rrow.get("CVEs","") or "—")
                _rv_mnt  = str(_rrow.get("Maintainer","—"))
                _rv_repo = str(_rrow.get("Repo","") or "")
                _rv_ac   = _reg_accent(_rv_reg)

                _rv_cve_has = _rv_cves not in ("—","","None","N/A","nan")
                _rv_cbg = "#7f1d1d" if _rv_cve_has else "#0a1e36"
                _rv_cfc = "#fca5a5" if _rv_cve_has else "#4a6580"
                _rv_clb = _rv_cves if _rv_cve_has else "None detected"

                _rv_repo_link = (
                    f'<a href="{_rv_repo}" target="_blank" '
                    f'style="color:{_rv_ac};text-decoration:none;font-size:0.73rem">'
                    f'{_rv_repo[:55]}{"…" if len(_rv_repo)>55 else ""} ↗</a>'
                    if _rv_repo else
                    '<span style="color:#2e4a60;font-size:0.73rem">—</span>'
                )

                _rv_pills = (
                    _ov_pill("License",      _rv_lic) +
                    _ov_pill("Downloads",    _rv_dl) +
                    _ov_pill("Last Updated", _rv_upd) +
                    _ov_pill("CVEs", _rv_clb, bg=_rv_cbg, lc=_rv_cfc, vc=_rv_cfc,
                             vs="font-size:0.72rem;word-break:break-all;") +
                    _ov_pill("Maintainer", _trunc(_rv_mnt, 28),
                             vs="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;")
                )

                st.markdown(
                    f'<div style="background:#070d1b;border:1px solid #12243d;'
                    f'border-left:4px solid {_rv_ac};border-radius:14px;'
                    f'padding:1rem 1.2rem;margin-bottom:0.75rem">'
                    # header
                    f'<div style="display:flex;align-items:center;gap:0.6rem;'
                    f'margin-bottom:0.6rem;flex-wrap:wrap">'
                    f'<span style="font-size:1.05rem;font-weight:900;color:#f1f5f9">{_rv_lib}</span>'
                    f'<span style="background:{_rv_ac}22;color:{_rv_ac};border:1px solid {_rv_ac}55;'
                    f'border-radius:20px;font-size:0.65rem;font-weight:800;'
                    f'padding:0.12rem 0.55rem;letter-spacing:0.8px">{_rv_reg}</span>'
                    f'<span style="background:#0a1e36;color:#94a3b8;border:1px solid #12243d;'
                    f'border-radius:20px;font-size:0.65rem;padding:0.12rem 0.55rem">v {_rv_ver}</span>'
                    f'</div>'
                    # description
                    f'<div style="color:#6b8aa8;font-size:0.8rem;line-height:1.6;'
                    f'margin-bottom:0.7rem;max-width:700px">'
                    f'{_trunc(_rv_desc.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;"),240)}'
                    f'</div>'
                    # pills
                    f'<div style="display:flex;flex-wrap:wrap;gap:0.4rem;margin-bottom:0.6rem">'
                    f'{_rv_pills}'
                    f'</div>'
                    # repo link
                    f'<div style="border-top:1px solid #0f1e30;padding-top:0.45rem;'
                    f'font-size:0.7rem;color:#2e4a60">Source: {_rv_repo_link}</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )

            # ══════════════════════════════════════════════════════════════
            # EXPORT ALL MAINTAINERS — bulk download for all registries
            # ══════════════════════════════════════════════════════════════
            if len(df) > 1:
                with st.expander(
                    f"⬇ Export All Maintainers  —  {len(df)} registr{'y' if len(df)==1 else 'ies'}",
                    expanded=False
                ):
                    st.markdown(
                        '<div style="color:#4a6580;font-size:0.78rem;margin-bottom:0.8rem">'
                        'Download maintainer data for <strong style="color:#94a3b8">every</strong> '
                        'library found in this scan. CSV contains scan-level data (instant). '
                        'JSON also includes cached GitHub / CVE intelligence for any packages '
                        'you have already individually profiled this session.'
                        '</div>',
                        unsafe_allow_html=True
                    )

                    # ── Build CSV ─────────────────────────────────────────────
                    _csv_rows = []
                    for _, _r in df.iterrows():
                        _csv_rows.append({
                            "Registry":     _r.get("Registry",""),
                            "Library":      _r.get("Library",""),
                            "Version":      _r.get("Version",""),
                            "Maintainer":   _r.get("Maintainer",""),
                            "CVEs":         _r.get("CVEs",""),
                            "License":      _r.get("License",""),
                            "Downloads":    _r.get("Downloads",""),
                            "Last Updated": _r.get("Last Updated",""),
                            "Description":  _r.get("Description",""),
                            "Repo":         _r.get("Repo",""),
                        })
                    _csv_df  = pd.DataFrame(_csv_rows)
                    _csv_str = _csv_df.to_csv(index=False)

                    # ── Build JSON (scan data + any cached GitHub intel) ───────
                    _all_export = []
                    _pcache_all = st.session_state.get("profile_cache", {})
                    for _, _r in df.iterrows():
                        _rlib  = _r.get("Library","")
                        _rreg  = _r.get("Registry","")
                        _rkey  = f"{_rlib}::{_rreg}"
                        _cached = _pcache_all.get(_rkey, {})

                        _repo_i = _cached.get("repo_info") or {}
                        _ci_all = _cached.get("contrib_intel") or []
                        _ossf   = _cached.get("openssf")
                        _raw_m  = _cached.get("raw_maintainers") or {}
                        _mgh    = _cached.get("maint_gh_profiles") or {}

                        _entry = {
                            "library":      _rlib,
                            "registry":     _rreg,
                            "version":      _r.get("Version",""),
                            "license":      _r.get("License",""),
                            "downloads":    _r.get("Downloads",""),
                            "last_updated": _r.get("Last Updated",""),
                            "description":  _r.get("Description",""),
                            "cves_scan":    _r.get("CVEs",""),
                            "repo_url":     _r.get("Repo",""),
                            "maintainer_raw": _r.get("Maintainer",""),
                            "maintainers_detail": [
                                {
                                    "name":           _m.get("name",""),
                                    "email":          _m.get("email",""),
                                    "url":            _m.get("url",""),
                                    "github_profile": _mgh.get(_m.get("name","")) or {},
                                }
                                for _m in _raw_m.get("maintainers",[])
                            ],
                            "original_author": _raw_m.get("author",""),
                            "github_repo": {
                                "path":        _cached.get("gh_path",""),
                                "stars":       _repo_i.get("stargazers_count"),
                                "forks":       _repo_i.get("forks_count"),
                                "open_issues": _repo_i.get("open_issues_count"),
                                "language":    _repo_i.get("language"),
                                "license":     (_repo_i.get("license") or {}).get("name"),
                                "last_push":   (_repo_i.get("pushed_at","") or "")[:10],
                                "topics":      _repo_i.get("topics",[]),
                            } if _repo_i else None,
                            "openssf_scorecard": _ossf,
                            "key_maintainers_github": [
                                {
                                    "rank":           _idx + 1,
                                    "login":          _ci.get("login",""),
                                    "name":           _ci.get("name",""),
                                    "github_url":     _ci.get("github_url",""),
                                    "email":          _ci.get("email",""),
                                    "company":        _ci.get("company",""),
                                    "location":       _ci.get("location",""),
                                    "followers":      _ci.get("followers",0),
                                    "commits_to_repo":_ci.get("contributions",0),
                                    "npm_2fa":        _ci.get("npm_2fa","unknown"),
                                    "gpg_signing":    _ci.get("sig_info",{}),
                                    "account_age_risk":_ci.get("account_age",{}),
                                    "email_domain_classification": _ci.get("email_class",{}),
                                    "linkedin_url":   _ci.get("linkedin_url"),
                                    "twitter_url":    _ci.get("twitter_url"),
                                    "public_orgs":    _ci.get("user_orgs",[]),
                                }
                                for _idx, _ci in enumerate(_ci_all)
                            ],
                        }
                        _all_export.append(_entry)

                    _json_str  = json.dumps(_all_export, indent=2, default=str)
                    _scan_slug = str(df.iloc[0].get("Library","scan")).replace("/","_").replace(":","_")

                    _ec1, _ec2 = st.columns(2)
                    _ec1.download_button(
                        "⬇ CSV — All Maintainers",
                        _csv_str,
                        f"maintainers_all_{_scan_slug}.csv",
                        "text/csv",
                        use_container_width=True,
                        help="Registry · Library · Version · Maintainer · CVEs · License · Downloads — one row per registry",
                    )
                    _ec2.download_button(
                        "⬇ JSON — Enriched Profiles",
                        _json_str,
                        f"maintainers_all_{_scan_slug}.json",
                        "application/json",
                        use_container_width=True,
                        help="Includes GitHub contributors, GPG signing, npm 2FA, OpenSSF scorecard and CVEs for packages already profiled this session",
                    )

                    # Quick preview table
                    st.markdown(
                        '<div style="color:#3d5a75;font-size:0.72rem;margin:0.6rem 0 0.3rem">Preview</div>',
                        unsafe_allow_html=True)
                    _preview_cols = ["Registry","Library","Version","Maintainer","CVEs","License","Downloads"]
                    st.dataframe(
                        _csv_df[_preview_cols],
                        use_container_width=True,
                        hide_index=True,
                        height=min(56 + 38 * len(_csv_df), 320),
                    )

            # ══════════════════════════════════════════════════════════════
            # DEEP DIVE — detailed GitHub / CVE intelligence for one registry
            # ══════════════════════════════════════════════════════════════
            st.markdown("---")
            st.markdown(
                '<div class="sec-label">🔬 Deep Dive — Security Intelligence</div>',
                unsafe_allow_html=True)
            st.markdown(
                '<div style="color:#4a6580;font-size:0.78rem;margin-bottom:0.6rem">'
                'Select a registry entry to load its full GitHub contributor profile, '
                'OpenSSF scorecard, CVE feed, commit history and maintainer analysis.'
                '</div>',
                unsafe_allow_html=True)

            # Selectbox — one entry per registry row
            _dd_options = [
                f"📦  {row['Registry']:20s}  ·  {row['Library']}"
                for _, row in df.iterrows()
            ]
            selected_idx = st.selectbox(
                "Registry entry", range(len(_dd_options)),
                format_func=lambda i: _dd_options[i],
                label_visibility="collapsed")

            sel      = df.iloc[selected_idx]
            reg_name = sel["Registry"]
            pkg_name = sel["Library"]
            repo_url = sel.get("Repo","") or ""
            gh_path  = _repo_url_to_gh(repo_url)
            handle, is_org = _resolve_gh_handle(sel["Maintainer"], repo_url)

            # ── Profile cache: session (instant) → JSON (persistent) → API ─────
            _pkey   = f"{pkg_name}::{reg_name}"
            _pcache = st.session_state.get("profile_cache", {}).get(_pkey)

            # tok must be defined before both cache layers so Section G can use it
            tok = github_token or None

            # Force-refresh button (clears JSON + session cache for this pkg)
            _refresh_key = f"refresh_{_pkey}"
            if st.button("🔄 Refresh data", key=_refresh_key, help="Force re-fetch fresh data from all APIs"):
                _delete_json_cache(pkg_name, reg_name)
                st.session_state.get("profile_cache", {}).pop(_pkey, None)
                _pcache = None

            if _pcache:
                # If old cache entry was saved with rate_limited=True, discard it
                # so the next render retries GitHub instead of permanently showing the error
                if _pcache.get("rate_limited"):
                    st.session_state.get("profile_cache", {}).pop(_pkey, None)
                    _pcache = None

            if _pcache:
                # Layer 1 — session_state: instant, no I/O
                rate_limited      = _pcache["rate_limited"]
                gh_path           = _pcache.get("gh_path", gh_path)
                handle            = _pcache.get("handle",  handle)
                repo_info         = _pcache["repo_info"]
                repo_cmts         = _pcache["repo_cmts"]
                last_commit_date  = _pcache["last_commit_date"]
                owner_prof        = _pcache["owner_prof"]
                is_org            = _pcache.get("is_org", is_org)
                owner_repos       = _pcache["owner_repos"]
                raw_maintainers   = _pcache["raw_maintainers"]
                maint_gh_profiles = _pcache["maint_gh_profiles"]
                contrib_intel     = _pcache.get("contrib_intel", [])
                openssf           = _pcache.get("openssf")
            else:
                # Layer 2 — JSON cache: load once from disk, check TTL per field
                _jc = _load_json_cache(pkg_name, reg_name)

                tok          = github_token or None
                rate_limited = False

                # Initialise all fields (from JSON cache where fresh, else None/default)
                _gh_path_cached,    _gh_path_fresh    = _jcache_get(_jc, "gh_path")
                _handle_cached,     _handle_fresh     = _jcache_get(_jc, "handle")
                _repo_info_cached,  _repo_info_fresh  = _jcache_get(_jc, "repo_info")
                _repo_cmts_cached,  _repo_cmts_fresh  = _jcache_get(_jc, "repo_cmts")
                _lcd_cached,        _lcd_fresh        = _jcache_get(_jc, "last_commit_date")
                _owner_prof_cached, _owner_prof_fresh = _jcache_get(_jc, "owner_prof")
                _owner_repos_cached,_owner_repos_fresh= _jcache_get(_jc, "owner_repos")
                _raw_m_cached,      _raw_m_fresh      = _jcache_get(_jc, "raw_maintainers")
                _mgh_cached,        _mgh_fresh        = _jcache_get(_jc, "maint_gh_profiles")
                _ci_cached,         _ci_fresh         = _jcache_get(_jc, "contrib_intel")
                _ossf_cached,       _ossf_fresh       = _jcache_get(_jc, "openssf")

                # Apply cached values as defaults
                if _gh_path_fresh and _gh_path_cached:
                    gh_path = _gh_path_cached
                if _handle_fresh and _handle_cached:
                    handle  = _handle_cached
                repo_info         = _repo_info_cached  if _repo_info_fresh  else None
                repo_cmts         = _repo_cmts_cached  if _repo_cmts_fresh  else []
                last_commit_date  = _lcd_cached        if _lcd_fresh        else None
                owner_prof        = _owner_prof_cached if _owner_prof_fresh else None
                owner_repos       = _owner_repos_cached if _owner_repos_fresh else []
                raw_maintainers   = _raw_m_cached      if _raw_m_fresh      else {"author":"","maintainers":[]}
                maint_gh_profiles = _mgh_cached        if _mgh_fresh        else {}
                contrib_intel     = _ci_cached         if _ci_fresh         else []
                openssf           = _ossf_cached       if _ossf_fresh       else None

                # Determine what still needs fetching from the API
                _need_api = (not _repo_info_fresh or not _repo_cmts_fresh or
                             not _owner_prof_fresh or not _raw_m_fresh or
                             not _mgh_fresh or not _ci_fresh or
                             not _ossf_fresh or not _gh_path_fresh)

                if _need_api:
                    with st.spinner(f"Fetching fresh data for **{pkg_name}** on **{reg_name}**…"):

                        # No pre-check call — detect rate limit inline from 403 responses
                        # (saves one precious unauthenticated API call)
                        if True:
                            # ── Repo discovery (gh_path) ──────────────────────
                            if not _gh_path_fresh:
                                _found = _gh_search_repo(pkg_name, tok)
                                if _found:
                                    gh_path = _found
                                    handle, is_org = _resolve_gh_handle(
                                        sel["Maintainer"], f"https://github.com/{_found}")
                                    _jcache_set(_jc, "gh_path", gh_path)
                                    _jcache_set(_jc, "handle",  handle)

                            # ── A. Repo info + commits ─────────────────────────
                            if gh_path and not _repo_info_fresh:
                                repo_info = gh_repo_info(gh_path, tok)
                                if isinstance(repo_info, dict) and repo_info.get("_rate_limited"):
                                    rate_limited = True; repo_info = None
                                else:
                                    _jcache_set(_jc, "repo_info", repo_info)
                                    repo_cmts, last_commit_date = gh_repo_commits(gh_path, tok)
                                    _jcache_set(_jc, "repo_cmts",        repo_cmts)
                                    _jcache_set(_jc, "last_commit_date", last_commit_date)
                            elif gh_path and not _repo_cmts_fresh:
                                repo_cmts, last_commit_date = gh_repo_commits(gh_path, tok)
                                _jcache_set(_jc, "repo_cmts",        repo_cmts)
                                _jcache_set(_jc, "last_commit_date", last_commit_date)

                        # ── B. Registry maintainers (no GitHub token needed) ──
                        if not _raw_m_fresh:
                            raw_maintainers = fetch_pkg_maintainers(pkg_name, reg_name)
                            _jcache_set(_jc, "raw_maintainers", raw_maintainers)

                        if not rate_limited:
                            # ── C. Owner/org profile ──────────────────────────
                            if handle and not _owner_prof_fresh:
                                owner_prof = gh_profile(handle, is_org, tok)
                                if isinstance(owner_prof, dict) and owner_prof.get("_rate_limited"):
                                    rate_limited = True; owner_prof = None
                                elif owner_prof:
                                    is_org = (owner_prof.get("_etype") == "orgs")
                                    _jcache_set(_jc, "owner_prof", owner_prof)
                                    # owner_repos = extra call — only fetch with a token
                                    if tok and not _owner_repos_fresh:
                                        owner_repos = gh_repos(handle, is_org, tok)
                                        _jcache_set(_jc, "owner_repos", owner_repos)

                            # ── D. Individual maintainer GitHub profiles ───────
                            # Skip without a token — saves up to 8 API calls
                            if tok and not _mgh_fresh:
                                for m in raw_maintainers["maintainers"][:8]:
                                    uname = m.get("name","").strip()
                                    if not uname: continue
                                    p = _gh_get(f"https://api.github.com/users/{uname}", tok)
                                    if p and "login" in p:
                                        maint_gh_profiles[uname] = p
                                _jcache_set(_jc, "maint_gh_profiles", maint_gh_profiles)

                            # ── E. Contributor security intelligence ───────────
                            # Only auto-fetch if already cached (JSON hit).
                            # First-time load is triggered by a button in the UI
                            # to avoid spending 25 API calls on initial page open.
                            if gh_path and not _ci_fresh and _ci_cached:
                                contrib_intel = gh_contributors_intel(
                                    gh_path, tok, n=5, reg_name=reg_name)
                                _jcache_set(_jc, "contrib_intel", contrib_intel)

                        # ── F. OpenSSF Scorecard (no token needed) ────────────
                        if gh_path and not _ossf_fresh:
                            openssf = _openssf_scorecard(gh_path)
                            _jcache_set(_jc, "openssf", openssf)


                    # Persist updated cache to disk
                    _save_json_cache(pkg_name, reg_name, _jc)

                # Layer 3 — save to session_state for instant recall this session
                # Never cache rate_limited=True — next visit should retry GitHub
                st.session_state.setdefault("profile_cache", {})[_pkey] = {
                    "rate_limited":      False,
                    "gh_path":           gh_path,
                    "handle":            handle,
                    "repo_info":         repo_info,
                    "repo_cmts":         repo_cmts,
                    "last_commit_date":  last_commit_date,
                    "owner_prof":        owner_prof,
                    "is_org":            is_org,
                    "owner_repos":       owner_repos,
                    "raw_maintainers":   raw_maintainers,
                    "maint_gh_profiles": maint_gh_profiles,
                    "contrib_intel":     contrib_intel,
                    "openssf":           openssf,
                }

            all_cmts   = repo_cmts
            lc_display = last_commit_date or (all_cmts[0]["date"] if all_cmts else "—")

            # ══════════════════════════════════════════════════════════════
            # SECTION 0 — Package Overview  (always visible, from scan data)
            # ══════════════════════════════════════════════════════════════
            _ov_name     = sel.get("Library",    "—")
            _ov_reg      = sel.get("Registry",   "—")
            _ov_ver      = sel.get("Version",    "N/A")
            _ov_lic      = sel.get("License",    "—")
            _ov_dl       = sel.get("Downloads",  "—")
            _ov_desc     = sel.get("Description","—") or "—"
            _ov_cves     = sel.get("CVEs",       "—")
            _ov_upd      = sel.get("Last Updated","—")
            _ov_maint    = sel.get("Maintainer", "—")
            _ov_repo     = sel.get("Repo",       "")

            # Derive a registry colour accent
            _ov_reg_colours = {
                "NPM":"#cc3534","PyPI":"#3572a5","RubyGems":"#cc342d",
                "Crates.io":"#dea584","NuGet":"#004880","Maven":"#b07219",
                "Go Modules":"#00acd7","Homebrew":"#fbb040","Docker Hub":"#2496ed",
                "Winget":"#0078d4","Chrome Web Store":"#4285f4",
                "APT/Debian":"#d70751","APT/Ubuntu":"#e95420",
                "YUM/Fedora":"#3c6eb4","YUM/RHEL":"#ee0000",
            }
            _ov_accent = "#06b6d4"
            for _k, _v in _ov_reg_colours.items():
                if _k.lower() in _ov_reg.lower():
                    _ov_accent = _v
                    break

            # CVE badge colour
            _cve_has = _ov_cves not in ("—", "", None, "N/A") and _ov_cves
            _cve_badge_bg  = "#7f1d1d" if _cve_has else "#0a1e36"
            _cve_badge_col = "#fca5a5" if _cve_has else "#4a6580"
            _cve_label     = _ov_cves if _cve_has else "None detected"

            _ov_repo_link = (
                f'<a href="{_ov_repo}" target="_blank" '
                f'style="color:{_ov_accent};text-decoration:none;font-size:0.75rem">'
                f'{_ov_repo[:60]}{"…" if len(_ov_repo)>60 else ""} ↗</a>'
                if _ov_repo else
                '<span style="color:#2e4a60;font-size:0.75rem">—</span>'
            )

            st.markdown('<div class="sec-label">📋 Package Overview</div>',
                        unsafe_allow_html=True)
            # Build stat cards as individual strings (avoids 4-space Markdown code-block bug)
            def _stat_card(label, value, bg="#0a1e36", label_col="#3d5a75",
                           val_col="#94a3b8", extra_val_style=""):
                return (
                    f'<div style="background:{bg};border:1px solid #12243d;'
                    f'border-radius:9px;padding:0.4rem 0.65rem">'
                    f'<div style="color:{label_col};font-size:0.6rem;text-transform:uppercase;'
                    f'letter-spacing:1px;margin-bottom:0.1rem">{label}</div>'
                    f'<div style="color:{val_col};font-size:0.8rem;font-weight:600;{extra_val_style}">{value}</div>'
                    f'</div>'
                )

            _stat_license  = _stat_card("License",      _ov_lic)
            _stat_dl       = _stat_card("Downloads",     _ov_dl)
            _stat_upd      = _stat_card("Last Updated",  _ov_upd)
            _stat_cve      = _stat_card(
                "CVEs", _cve_label,
                bg=_cve_badge_bg, label_col=_cve_badge_col, val_col=_cve_badge_col,
                extra_val_style="font-size:0.75rem;word-break:break-all;"
            )
            _stat_maint    = _stat_card(
                "Maintainer", _trunc(str(_ov_maint), 32),
                extra_val_style="font-size:0.78rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"
            )
            _stats_html = _stat_license + _stat_dl + _stat_upd + _stat_cve + _stat_maint

            st.markdown(
                f'<div style="background:#070d1b;border:1px solid #12243d;'
                f'border-left:4px solid {_ov_accent};'
                f'border-radius:14px;padding:1.2rem 1.4rem;margin-bottom:1rem">'

                # Header: name + registry badge + version
                f'<div style="display:flex;align-items:center;gap:0.75rem;'
                f'margin-bottom:0.9rem;flex-wrap:wrap">'
                f'<span style="font-size:1.15rem;font-weight:900;color:#f1f5f9">{_ov_name}</span>'
                f'<span style="background:{_ov_accent}22;color:{_ov_accent};'
                f'border:1px solid {_ov_accent}55;border-radius:20px;font-size:0.67rem;'
                f'font-weight:800;padding:0.15rem 0.65rem;letter-spacing:0.8px">{_ov_reg}</span>'
                f'<span style="background:#0a1e36;color:#94a3b8;border:1px solid #12243d;'
                f'border-radius:20px;font-size:0.67rem;padding:0.15rem 0.65rem">v {_ov_ver}</span>'
                f'</div>'

                # Description
                f'<div style="color:#6b8aa8;font-size:0.82rem;line-height:1.65;'
                f'margin-bottom:0.9rem;max-width:680px">'
                f'{_trunc(str(_ov_desc).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;"), 280)}'
                f'</div>'

                # Stats grid
                f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));'
                f'gap:0.5rem;margin-bottom:0.9rem">'
                f'{_stats_html}'
                f'</div>'

                # Repo link
                f'<div style="border-top:1px solid #0f1e30;padding-top:0.55rem;'
                f'font-size:0.72rem;color:#2e4a60">Source: {_ov_repo_link}</div>'

                f'</div>',
                unsafe_allow_html=True
            )

            # ══════════════════════════════════════════════════════════════
            # SECTION A — Official GitHub Repository
            # ══════════════════════════════════════════════════════════════
            st.markdown('<div class="sec-label">📁 Official GitHub Repository</div>',
                        unsafe_allow_html=True)

            if rate_limited:
                # Calculate minutes until reset (GitHub resets on the hour)
                _now       = datetime.datetime.now(datetime.timezone.utc)
                _reset_min = 60 - _now.minute
                st.warning(
                    f"**GitHub API rate limit reached** (60 req/hr without a token). "
                    f"Resets in ~{_reset_min} min. "
                    f"Showing cached data where available. "
                    f"Add a GitHub token in the sidebar for unlimited access.",
                    icon="⏱️")
            elif repo_info:
                ri       = repo_info
                r_stars  = _fmt_dl(ri.get("stargazers_count",0))
                r_forks  = _fmt_dl(ri.get("forks_count",0))
                r_issues = _fmt_dl(ri.get("open_issues_count",0))
                r_watch  = _fmt_dl(ri.get("watchers_count",0))
                r_lang   = ri.get("language","") or "—"
                r_lic    = (ri.get("license") or {}).get("name","—") or "—"
                r_pushed = (ri.get("pushed_at","") or "")[:10] or "—"
                r_desc   = ri.get("description","") or "—"
                r_url    = ri.get("html_url","")
                r_topics = ri.get("topics",[]) or []
                r_branch = ri.get("default_branch","main")
                topics_html = " ".join(
                    f'<span style="background:#0a1e36;color:#06b6d4;border:1px solid #12243d;'
                    f'border-radius:20px;font-size:0.68rem;padding:0.15rem 0.6rem;'
                    f'font-weight:600">{t}</span>' for t in r_topics[:8])
                _md(f"""
<div style="background:#070d1b;border:1px solid #12243d;border-radius:14px;
            padding:1.2rem 1.4rem;margin-bottom:1rem">
  <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:1rem">
    <div>
      <a href="{r_url}" target="_blank"
         style="color:#06b6d4;font-size:1.05rem;font-weight:800;text-decoration:none">
        {ri.get('full_name', gh_path)}
      </a>
      <div style="color:#4a6580;font-size:0.8rem;margin-top:0.35rem;line-height:1.6">
        {_trunc(r_desc,120)}
      </div>
      {"<div style='margin-top:0.6rem'>" + topics_html + "</div>" if r_topics else ""}
    </div>
    <a href="{r_url}" target="_blank"
       style="background:linear-gradient(135deg,#035a8e,#06b6d4);color:#fff;
              border-radius:8px;padding:0.45rem 1rem;font-size:0.8rem;
              font-weight:700;text-decoration:none;white-space:nowrap;flex-shrink:0">
      View on GitHub ↗
    </a>
  </div>
  <div style="display:flex;gap:2rem;margin-top:1rem;flex-wrap:wrap">
    <span style="color:#94a3b8;font-size:0.82rem">⭐ <strong style="color:#f1f5f9">{r_stars}</strong> stars</span>
    <span style="color:#94a3b8;font-size:0.82rem">🍴 <strong style="color:#f1f5f9">{r_forks}</strong> forks</span>
    <span style="color:#94a3b8;font-size:0.82rem">🐛 <strong style="color:#f1f5f9">{r_issues}</strong> open issues</span>
    <span style="color:#94a3b8;font-size:0.82rem">👁️ <strong style="color:#f1f5f9">{r_watch}</strong> watchers</span>
    <span style="color:#94a3b8;font-size:0.82rem">🌐 <strong style="color:#f1f5f9">{r_lang}</strong></span>
    <span style="color:#94a3b8;font-size:0.82rem">📄 <strong style="color:#f1f5f9">{r_lic}</strong></span>
    <span style="color:#94a3b8;font-size:0.82rem">🕐 Last push <strong style="color:#f1f5f9">{r_pushed}</strong></span>
    <span style="color:#94a3b8;font-size:0.82rem">🌿 <strong style="color:#f1f5f9">{r_branch}</strong></span>
  </div>
</div>""")

                # Latest commit highlight
                if all_cmts:
                    latest   = all_cmts[0]
                    cmt_link = latest.get("url","")
                    view_btn = (f'<a href="{cmt_link}" target="_blank" style="color:#06b6d4;'
                                f'font-size:0.78rem;text-decoration:none;background:#0a1e36;'
                                f'padding:0.25rem 0.7rem;border-radius:6px;border:1px solid #12243d">'
                                f'View ↗</a>' if cmt_link else "")
                    _md(f"""
<div style="background:rgba(6,182,212,0.05);border:1px solid rgba(6,182,212,0.2);
            border-left:3px solid #06b6d4;border-radius:10px;
            padding:0.8rem 1.1rem;margin-bottom:0.6rem">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.3rem">
    <span style="color:#06b6d4;font-size:0.7rem;font-weight:800;
                 text-transform:uppercase;letter-spacing:1.5px">🔀 Latest Commit</span>
    {view_btn}
  </div>
  <div style="color:#e2e8f0;font-size:0.88rem;font-weight:600">{latest['message']}</div>
  <div style="color:#4a7090;font-size:0.75rem;margin-top:0.3rem">
    <code style="color:#06b6d4;font-size:0.72rem">{latest['sha']}</code>
    &nbsp;·&nbsp; by <strong style="color:#7eb3d4">{latest.get('author','—')}</strong>
    &nbsp;·&nbsp; {latest['date']}
  </div>
</div>""")

                # Commit history expander
                with st.expander(
                        f"📜 Commit History — {gh_path}  ({len(all_cmts)} loaded)",
                        expanded=False):
                    for cmt in all_cmts:
                        clink  = cmt.get("url","")
                        sha_el = (f'<a href="{clink}" target="_blank" style="color:#06b6d4;'
                                  f'font-size:0.72rem;font-family:monospace;text-decoration:none">'
                                  f'{cmt["sha"]}</a>'
                                  if clink else
                                  f'<code style="color:#06b6d4;font-size:0.72rem">{cmt["sha"]}</code>')
                        _md(f"""
<div style="display:flex;gap:0.8rem;align-items:flex-start;
            padding:0.45rem 0;border-bottom:1px solid #0f1e30">
  <div style="flex-shrink:0">{sha_el}</div>
  <div style="flex:1;min-width:0">
    <div style="color:#94a3b8;font-size:0.8rem;
                white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{cmt['message']}</div>
    <div style="color:#2e6080;font-size:0.7rem;margin-top:0.1rem">
      by <strong style="color:#4a7090">{cmt.get('author','—')}</strong>
      &nbsp;·&nbsp; {cmt['date']}
    </div>
  </div>
</div>""")

            elif gh_path:
                st.info(f"Could not fetch repo data for **{gh_path}**. "
                        "Try adding a GitHub token in the sidebar.", icon="ℹ️")
            else:
                st.info("No GitHub repository URL found for this package.", icon="ℹ️")

            # ══════════════════════════════════════════════════════════════
            # SECTION B — Original Author  🍒 cherry on top
            # ══════════════════════════════════════════════════════════════
            st.markdown("")
            st.markdown('<div class="sec-label">✍️ Original Author</div>',
                        unsafe_allow_html=True)

            author_name = raw_maintainers.get("author","").strip()
            if author_name:
                author_gh = maint_gh_profiles.get(author_name)
                if author_gh:
                    ac1, ac2 = st.columns([1,3], gap="large")
                    with ac1:
                        if author_gh.get("avatar_url"):
                            st.image(author_gh["avatar_url"], width=80)
                    with ac2:
                        adisp = author_gh.get("name") or author_name
                        alogin= author_gh.get("login","")
                        abio  = author_gh.get("bio") or author_gh.get("description") or "—"
                        _md(f"""
<div style="background:#070d1b;border:1px solid #12243d;border-left:3px solid #f59e0b;
            border-radius:10px;padding:0.8rem 1rem">
  <div style="color:#fbbf24;font-size:0.68rem;font-weight:800;
              text-transform:uppercase;letter-spacing:1.5px;margin-bottom:0.3rem">
    🍒 Library Author
  </div>
  <div style="color:#f1f5f9;font-size:0.95rem;font-weight:700">{adisp}</div>
  <div style="color:#4a7090;font-size:0.75rem">@{alogin}</div>
  <div style="color:#3d5a75;font-size:0.78rem;margin-top:0.35rem">{_trunc(abio,100)}</div>
  <div style="margin-top:0.5rem;display:flex;gap:1rem;flex-wrap:wrap">
    <span style="color:#4a7090;font-size:0.75rem">
      📦 {_fmt_dl(author_gh.get('public_repos',0))} repos
    </span>
    <span style="color:#4a7090;font-size:0.75rem">
      👥 {_fmt_dl(author_gh.get('followers',0))} followers
    </span>
    {"<span style='color:#4a7090;font-size:0.75rem'>📍 " + author_gh['location'] + "</span>" if author_gh.get('location') else ""}
    {"<span style='color:#4a7090;font-size:0.75rem'>🌐 " + author_gh.get('blog','') + "</span>" if author_gh.get('blog') else ""}
  </div>
  <div style="margin-top:0.5rem">
    <a href="https://github.com/{alogin}" target="_blank"
       style="color:#06b6d4;font-size:0.78rem;text-decoration:none">
      🐙 github.com/{alogin}
    </a>
  </div>
</div>""")
                else:
                    _md(f"""
<div style="background:#070d1b;border:1px solid #12243d;border-left:3px solid #f59e0b;
            border-radius:10px;padding:0.75rem 1rem">
  <span style="color:#fbbf24;font-size:0.68rem;font-weight:800;
               text-transform:uppercase;letter-spacing:1.5px">🍒 Library Author &nbsp;</span>
  <span style="color:#f1f5f9;font-size:0.92rem;font-weight:700">{author_name}</span>
  <span style="color:#2e6080;font-size:0.75rem;margin-left:0.8rem">
    (GitHub profile not found — may use a different username)
  </span>
</div>""")
            else:
                st.markdown("""
<div style="color:#2e6080;font-size:0.82rem;padding:0.5rem 0">
  Author field not available for this registry / package combination.
</div>""", unsafe_allow_html=True)

            # ══════════════════════════════════════════════════════════════
            # SECTION C — All Maintainers with individual GitHub cards
            # ══════════════════════════════════════════════════════════════
            st.markdown("")
            all_m = raw_maintainers.get("maintainers",[])
            st.markdown(
                f'<div class="sec-label">👥 Active Maintainers on {reg_name} '
                f'<span style="color:#06b6d4">({len(all_m)} total)</span></div>',
                unsafe_allow_html=True)

            if all_m:
                # Render 2 cards per row
                for row_start in range(0, len(all_m), 2):
                    cols = st.columns(2, gap="medium")
                    for ci, m in enumerate(all_m[row_start:row_start+2]):
                        uname   = m.get("name","").strip()
                        email   = m.get("email","").strip()
                        mgh     = maint_gh_profiles.get(uname)
                        with cols[ci]:
                            if mgh and "login" in mgh:
                                av   = mgh.get("avatar_url","")
                                disp = mgh.get("name") or uname
                                bio  = mgh.get("bio") or "—"
                                loc  = mgh.get("location","") or ""
                                blog = mgh.get("blog","") or ""
                                repo_c = _fmt_dl(mgh.get("public_repos",0))
                                fol_c  = _fmt_dl(mgh.get("followers",0))
                                login  = mgh.get("login","")
                                av_html = (f'<img src="{av}" style="width:44px;height:44px;'
                                           f'border-radius:50%;border:2px solid #12243d;'
                                           f'margin-right:0.7rem;flex-shrink:0">'
                                           if av else
                                           f'<div style="width:44px;height:44px;border-radius:50%;'
                                           f'background:#0a1e36;border:2px solid #12243d;'
                                           f'margin-right:0.7rem;flex-shrink:0;display:flex;'
                                           f'align-items:center;justify-content:center;'
                                           f'color:#06b6d4;font-weight:700;font-size:1rem">'
                                           f'{uname[:1].upper()}</div>')
                                ln_url = (f"https://www.linkedin.com/company/{login}"
                                          if is_org else
                                          f"https://www.linkedin.com/search/results/people/"
                                          f"?keywords={disp.replace(' ','%20')}")
                                _md(f"""
<div style="background:#070d1b;border:1px solid #12243d;border-radius:12px;
            padding:0.85rem;margin-bottom:0.6rem">
  <div style="display:flex;align-items:center;margin-bottom:0.5rem">
    {av_html}
    <div>
      <div style="color:#f1f5f9;font-size:0.88rem;font-weight:700">{disp}</div>
      <div style="color:#4a7090;font-size:0.72rem">@{login}</div>
    </div>
  </div>
  <div style="color:#3d5a75;font-size:0.75rem;margin-bottom:0.45rem;line-height:1.5">
    {_trunc(bio,80)}
  </div>
  <div style="display:flex;gap:1rem;font-size:0.72rem;color:#2e6080;flex-wrap:wrap">
    <span>📦 {repo_c} repos</span>
    <span>👥 {fol_c} followers</span>
    {"<span>📍 " + loc + "</span>" if loc else ""}
  </div>
  <div style="margin-top:0.5rem;display:flex;gap:0.8rem;flex-wrap:wrap">
    <a href="https://github.com/{login}" target="_blank"
       style="color:#06b6d4;font-size:0.73rem;text-decoration:none">🐙 GitHub</a>
    <a href="{ln_url}" target="_blank"
       style="color:#5a9fd4;font-size:0.73rem;text-decoration:none">🔗 LinkedIn</a>
    {"<a href='" + blog + "' target='_blank' style='color:#5a9fd4;font-size:0.73rem;text-decoration:none'>🌐 Website</a>" if blog else ""}
    {"<span style='color:#2e6080;font-size:0.72rem'>✉️ " + email + "</span>" if email else ""}
  </div>
</div>""")
                            else:
                                # No GitHub profile found — show minimal card
                                _md(f"""
<div style="background:#070d1b;border:1px solid #12243d;border-radius:12px;
            padding:0.85rem;margin-bottom:0.6rem;opacity:0.75">
  <div style="display:flex;align-items:center;gap:0.7rem">
    <div style="width:44px;height:44px;border-radius:50%;background:#0a1e36;
                border:2px solid #12243d;display:flex;align-items:center;
                justify-content:center;color:#06b6d4;font-weight:700;
                font-size:1rem;flex-shrink:0">{uname[:1].upper() if uname else "?"}</div>
    <div>
      <div style="color:#94a3b8;font-size:0.88rem;font-weight:700">{uname or "—"}</div>
      {"<div style='color:#2e6080;font-size:0.72rem'>✉️ " + email + "</div>" if email else ""}
      <div style="color:#243850;font-size:0.7rem;margin-top:0.2rem">
        GitHub profile not found
      </div>
    </div>
  </div>
</div>""")
            else:
                st.info("Maintainer list not available from this registry's API.", icon="ℹ️")

            # ══════════════════════════════════════════════════════════════
            # SECTION D — Owner / Org GitHub Profile
            # ══════════════════════════════════════════════════════════════
            if owner_prof:
                st.markdown("")
                st.markdown('<div class="sec-label">🏢 Owner / Org Profile</div>',
                            unsafe_allow_html=True)
                op1, op2 = st.columns([1, 2], gap="large")
                with op1:
                    av = owner_prof.get("avatar_url","")
                    if av: st.image(av, width=88)
                    odisp = owner_prof.get("name") or handle or "—"
                    ologin= owner_prof.get("login","")
                    obio  = owner_prof.get("bio") or owner_prof.get("description") or "—"
                    otype = "Organisation" if is_org else "Individual"
                    _md(f"""
<div style="margin-top:0.4rem">
  <div style="color:#f1f5f9;font-size:0.95rem;font-weight:700">{odisp}</div>
  <div style="color:#06b6d4;font-size:0.68rem;font-weight:700;
              text-transform:uppercase;letter-spacing:1px">{otype}</div>
  <div style="color:#3d5a75;font-size:0.75rem;margin-top:0.4rem;line-height:1.6">{obio}</div>
</div>""")
                    st.markdown("")
                    for item in [
                        (owner_prof.get("location"), f"📍 {owner_prof.get('location','')}"),
                        (owner_prof.get("blog"),     f"🌐 [{owner_prof.get('blog','')}]({owner_prof.get('blog','')})"),
                        (owner_prof.get("email"),    f"✉️ {owner_prof.get('email','')}"),
                        (owner_prof.get("twitter_username"),
                         f"🐦 [@{owner_prof.get('twitter_username','')}](https://twitter.com/{owner_prof.get('twitter_username','')})"),
                    ]:
                        if item[0]:
                            st.markdown(f"<div style='color:#4a7090;font-size:0.8rem;margin-bottom:0.2rem'>{item[1]}</div>",
                                        unsafe_allow_html=True)
                    st.markdown("")
                    st.markdown(f"[🐙 GitHub](https://github.com/{ologin})")
                    if is_org:
                        st.markdown(f"[🔗 LinkedIn Company](https://www.linkedin.com/company/{ologin})")
                    else:
                        st.markdown(f"[🔗 LinkedIn](https://www.linkedin.com/search/results/people/?keywords={odisp.replace(' ','%20')})")

                with op2:
                    s1, s2, s3 = st.columns(3)
                    s1.metric("Public Repos", _fmt_dl(owner_prof.get("public_repos",0)) or "—")
                    s2.metric("Followers",    _fmt_dl(owner_prof.get("followers",0)) or "—")
                    s3.metric("Following" if not is_org else "Members",
                              _fmt_dl(owner_prof.get("following",0) or
                                      owner_prof.get("public_members",0)) or "—")
                    if owner_repos:
                        st.markdown('<div class="sec-label">Top Repositories</div>',
                                    unsafe_allow_html=True)
                        for r in sorted(owner_repos,
                                        key=lambda x: x.get("stargazers_count",0),
                                        reverse=True)[:5]:
                            _md(f"""
<div style="background:#070d1b;border:1px solid #12243d;border-radius:10px;
            padding:0.6rem 0.85rem;margin-bottom:0.4rem">
  <div style="display:flex;align-items:center;justify-content:space-between">
    <a href="{r.get('html_url','#')}" target="_blank"
       style="color:#06b6d4;font-weight:700;font-size:0.83rem;text-decoration:none">
      {r.get('name','')}
    </a>
    <span style="color:#2e6080;font-size:0.72rem">
      ⭐ {_fmt_dl(r.get('stargazers_count',0))} &nbsp; 🍴 {_fmt_dl(r.get('forks_count',0))}
      {"&nbsp;·&nbsp;" + r.get('language','') if r.get('language') else ""}
    </span>
  </div>
  <div style="color:#3d5a75;font-size:0.73rem;margin-top:0.2rem">
    {_trunc(r.get('description','') or '—', 90)}
  </div>
</div>""")

            # ══════════════════════════════════════════════════════════════
            # SECTION E — Security Intelligence: Key Maintainers from GitHub
            # ══════════════════════════════════════════════════════════════
            st.markdown("")
            st.markdown(
                '<div class="sec-label">🔍 Security Intelligence — Key Maintainers</div>',
                unsafe_allow_html=True)

            if contrib_intel:
                st.markdown(
                    f'<div style="color:#4a6580;font-size:0.78rem;margin-bottom:1rem">'
                    f'Top {len(contrib_intel)} contributors to '
                    f'<code style="color:#06b6d4">{gh_path}</code> · '
                    f'enriched with GitHub Social Accounts, orgs, 2FA, GPG signing, '
                    f'account age risk, email domain classification.</div>',
                    unsafe_allow_html=True)

                for idx, ci in enumerate(contrib_intel):
                    rank      = idx + 1
                    av        = ci.get("avatar_url", "")
                    name      = ci.get("name", ci["login"])
                    login_    = ci["login"]
                    commits   = _fmt_dl(ci.get("contributions", 0))
                    bio       = ci.get("bio", "") or "—"
                    company   = ci.get("company", "") or ""
                    location  = ci.get("location", "") or ""
                    email     = ci.get("email", "") or ""
                    blog      = ci.get("blog", "") or ""
                    followers = _fmt_dl(ci.get("followers", 0))
                    following = _fmt_dl(ci.get("following", 0))
                    repos     = _fmt_dl(ci.get("public_repos", 0))
                    gists     = _fmt_dl(ci.get("public_gists", 0))
                    gh_url    = ci.get("github_url", f"https://github.com/{login_}")
                    li_url    = ci.get("linkedin_url")
                    tw_url    = ci.get("twitter_url")
                    last_act  = ci.get("last_active", "—")
                    created   = ci.get("created_at", "—")
                    hireable  = ci.get("hireable")
                    is_admin  = ci.get("site_admin", False)

                    # Security signals
                    age_info       = ci.get("account_age", {})
                    email_cls      = ci.get("email_class", {})
                    sig_info       = ci.get("sig_info", {})
                    npm_2fa_val    = ci.get("npm_2fa", "unknown")
                    npm_pkgs_val   = ci.get("npm_pkgs")
                    user_orgs      = ci.get("user_orgs", [])
                    is_org_member  = ci.get("is_org_member", False)
                    repo_org_      = ci.get("repo_org", "")

                    # ── Rank badge ────────────────────────────────────────────
                    rank_colors = {1:"#f59e0b", 2:"#94a3b8", 3:"#cd7c3a"}
                    rank_color  = rank_colors.get(rank, "#06b6d4")
                    rank_label  = {1:"🥇 #1 Maintainer", 2:"🥈 #2 Contributor",
                                   3:"🥉 #3 Contributor"}.get(rank, f"#{rank} Contributor")

                    av_html = (
                        f'<img src="{av}" style="width:60px;height:60px;border-radius:50%;'
                        f'border:2px solid {rank_color};flex-shrink:0">'
                        if av else
                        f'<div style="width:60px;height:60px;border-radius:50%;background:#0a1e36;'
                        f'border:2px solid {rank_color};display:flex;align-items:center;'
                        f'justify-content:center;color:{rank_color};font-weight:800;'
                        f'font-size:1.3rem;flex-shrink:0">{login_[:1].upper()}</div>')

                    # ── LinkedIn ──────────────────────────────────────────────
                    li_svg = ('<svg width="12" height="12" viewBox="0 0 24 24" fill="white">'
                              '<path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037'
                              '-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046'
                              'c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286z'
                              'M5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063'
                              ' 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065z'
                              'M6.955 20.452H3.722V9h3.233v11.452z'
                              'M22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24'
                              'h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>')
                    if li_url:
                        li_html = (f'<a href="{li_url}" target="_blank" style="display:inline-flex;'
                                   f'align-items:center;gap:0.3rem;background:#0a66c2;color:#fff;'
                                   f'border-radius:6px;padding:0.28rem 0.7rem;font-size:0.72rem;'
                                   f'font-weight:700;text-decoration:none">{li_svg} LinkedIn ↗</a>')
                    else:
                        sq = f"site:linkedin.com/in+{name.replace(' ','+')}".replace(" ","+")
                        li_html = (f'<a href="https://www.google.com/search?q={sq}" target="_blank" '
                                   f'style="display:inline-flex;align-items:center;gap:0.3rem;'
                                   f'background:#1e3a5f;color:#7eb3d4;border:1px solid #12243d;'
                                   f'border-radius:6px;padding:0.28rem 0.7rem;font-size:0.72rem;'
                                   f'font-weight:700;text-decoration:none">🔎 Search LinkedIn</a>'
                                   f'<span style="color:#2e5070;font-size:0.66rem">(not on GitHub)</span>')

                    # ── Social links ──────────────────────────────────────────
                    tw_html   = (f'<a href="{tw_url}" target="_blank" style="color:#94a3b8;'
                                 f'font-size:0.72rem;text-decoration:none">𝕏 Twitter ↗</a>'
                                 if tw_url else "")
                    blog_html = (f'<a href="{blog}" target="_blank" style="color:#5a9fd4;'
                                 f'font-size:0.72rem;text-decoration:none">'
                                 f'🌐 {blog[:35]}{"…" if len(blog)>35 else ""}</a>'
                                 if blog else "")

                    # ── Security signal chips ─────────────────────────────────
                    age_color  = age_info.get("color","#4a6580")
                    age_label  = age_info.get("label","—")
                    ecls_color = email_cls.get("color","#4a6580")
                    ecls_label = email_cls.get("label","—")
                    sig_label  = sig_info.get("label","—")

                    # npm 2FA
                    if   npm_2fa_val == "disabled":
                        npm2fa_html = '<span style="color:#ef4444;font-weight:700">🔴 npm 2FA OFF</span>'
                    elif npm_2fa_val == "unknown":
                        npm2fa_html = '<span style="color:#4a6580">npm 2FA: unknown</span>'
                    else:
                        npm2fa_html = f'<span style="color:#22c55e;font-weight:700">🟢 npm 2FA: {npm_2fa_val}</span>'

                    # Org membership
                    if is_org_member:
                        org_html = f'<span style="color:#22c55e">✅ Official org member (@{repo_org_})</span>'
                    else:
                        org_html = f'<span style="color:#f59e0b">⚠️ Not in @{repo_org_} org</span>'

                    # Public orgs list
                    orgs_html = (", ".join(
                        f'<a href="https://github.com/{o}" target="_blank" '
                        f'style="color:#06b6d4;text-decoration:none">@{o}</a>'
                        for o in user_orgs[:5])
                        if user_orgs else '<span style="color:#2e6080">No public orgs</span>')

                    npm_pkgs_html = (f'<span style="color:#94a3b8">📦 {npm_pkgs_val} npm packages</span>'
                                     if npm_pkgs_val is not None else "")
                    hireable_html = ('<span style="color:#22c55e">💼 Open to work</span>'
                                     if hireable else "")
                    admin_html    = ('<span style="color:#ef4444;font-weight:700">⚡ GitHub Staff</span>'
                                     if is_admin else "")

                    _md(f"""
<div style="background:#070d1b;border:1px solid #12243d;border-left:3px solid {rank_color};
            border-radius:14px;padding:1.1rem 1.3rem;margin-bottom:1rem">

  <!-- ① Header: avatar + name + rank -->
  <div style="display:flex;align-items:center;gap:1rem;margin-bottom:0.75rem">
    {av_html}
    <div style="flex:1;min-width:0">
      <div style="display:flex;align-items:center;gap:0.6rem;flex-wrap:wrap">
        <a href="{gh_url}" target="_blank"
           style="color:#f1f5f9;font-size:1.05rem;font-weight:800;text-decoration:none">{name}</a>
        <span style="color:{rank_color};font-size:0.67rem;font-weight:800;border:1px solid {rank_color};
                     border-radius:20px;padding:0.1rem 0.55rem;background:rgba(0,0,0,0.3)">{rank_label}</span>
        {admin_html}
      </div>
      <a href="{gh_url}" target="_blank" style="color:#4a7090;font-size:0.77rem;text-decoration:none">
        @{login_}</a>
      {"<span style='color:#4a7090;font-size:0.72rem'> · " + company + "</span>" if company else ""}
      <div style="color:#3d5a75;font-size:0.77rem;margin-top:0.25rem;line-height:1.5">{_trunc(bio,120)}</div>
    </div>
  </div>

  <!-- ② Activity & stats row -->
  <div style="display:flex;flex-wrap:wrap;gap:1.2rem;font-size:0.73rem;color:#4a6580;
              padding:0.6rem 0;border-top:1px solid #0f1e30;border-bottom:1px solid #0f1e30;
              margin-bottom:0.7rem">
    <span>🔀 <strong style="color:#94a3b8">{commits}</strong> commits</span>
    <span>👥 <strong style="color:#94a3b8">{followers}</strong> followers</span>
    <span>➡️ <strong style="color:#94a3b8">{following}</strong> following</span>
    <span>📦 <strong style="color:#94a3b8">{repos}</strong> repos</span>
    <span>📝 <strong style="color:#94a3b8">{gists}</strong> gists</span>
    {"<span>📍 <strong style='color:#94a3b8'>" + location + "</strong></span>" if location else ""}
    {"<span>🗓️ Joined <strong style='color:#94a3b8'>" + created + "</strong></span>" if created and created!="—" else ""}
    {"<span>⚡ Active <strong style='color:#94a3b8'>" + last_act + "</strong></span>" if last_act and last_act!="—" else ""}
    {npm_pkgs_html}
    {hireable_html}
  </div>

  <!-- ③ Security signals -->
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.45rem;
              margin-bottom:0.75rem;font-size:0.73rem">
    <div style="background:#0a1e36;border:1px solid #12243d;border-radius:8px;padding:0.4rem 0.6rem">
      <div style="color:#4a6580;font-size:0.63rem;text-transform:uppercase;
                  letter-spacing:1px;margin-bottom:0.15rem">Account Age</div>
      <div style="color:{age_color};font-weight:700">{age_label}</div>
    </div>
    <div style="background:#0a1e36;border:1px solid #12243d;border-radius:8px;padding:0.4rem 0.6rem">
      <div style="color:#4a6580;font-size:0.63rem;text-transform:uppercase;
                  letter-spacing:1px;margin-bottom:0.15rem">Email Domain</div>
      <div style="color:{ecls_color};font-weight:600">
        {ecls_label}{"  <span style='color:#4a6580;font-weight:400'>(" + (email or "—") + ")</span>" if email else ""}
      </div>
    </div>
    <div style="background:#0a1e36;border:1px solid #12243d;border-radius:8px;padding:0.4rem 0.6rem">
      <div style="color:#4a6580;font-size:0.63rem;text-transform:uppercase;
                  letter-spacing:1px;margin-bottom:0.15rem">GPG Commit Signing</div>
      <div style="font-weight:600">{sig_label if sig_label!="—" else "<span style='color:#4a6580'>No commits sampled</span>"}</div>
    </div>
    <div style="background:#0a1e36;border:1px solid #12243d;border-radius:8px;padding:0.4rem 0.6rem">
      <div style="color:#4a6580;font-size:0.63rem;text-transform:uppercase;
                  letter-spacing:1px;margin-bottom:0.15rem">npm 2FA</div>
      <div>{npm2fa_html}</div>
    </div>
    <div style="background:#0a1e36;border:1px solid #12243d;border-radius:8px;padding:0.4rem 0.6rem">
      <div style="color:#4a6580;font-size:0.63rem;text-transform:uppercase;
                  letter-spacing:1px;margin-bottom:0.15rem">Org Membership</div>
      <div style="font-size:0.73rem">{org_html}</div>
    </div>
    <div style="background:#0a1e36;border:1px solid #12243d;border-radius:8px;padding:0.4rem 0.6rem">
      <div style="color:#4a6580;font-size:0.63rem;text-transform:uppercase;
                  letter-spacing:1px;margin-bottom:0.15rem">Public Orgs</div>
      <div style="font-size:0.72rem">{orgs_html}</div>
    </div>
  </div>

  <!-- ④ Social / contact links -->
  <div style="display:flex;align-items:center;gap:0.7rem;flex-wrap:wrap">
    {li_html}
    <a href="{gh_url}" target="_blank"
       style="color:#06b6d4;font-size:0.72rem;text-decoration:none">🐙 GitHub ↗</a>
    {tw_html}
    {blog_html}
  </div>

</div>""")

            elif not gh_path:
                st.info("No GitHub repository linked — cannot fetch contributor intelligence.", icon="ℹ️")
            else:
                # Not yet loaded — show on-demand button
                _md(f"""
<div style="background:#070d1b;border:1px solid #12243d;border-radius:14px;
            padding:1.4rem 1.6rem;text-align:center">
  <div style="color:#94a3b8;font-size:0.85rem;margin-bottom:0.3rem">
    🔍 Security intelligence for <code style="color:#06b6d4">{gh_path}</code>
    not loaded yet.
  </div>
  <div style="color:#4a6580;font-size:0.75rem;margin-bottom:1rem">
    Fetches top 5 contributors · LinkedIn · npm 2FA · GPG signing ·
    account age risk · email classification · org membership
    <br><strong style="color:#f59e0b">~25 GitHub API calls</strong> —
    result is cached for 7 days after first load.
  </div>
</div>""")

                _load_btn_key = f"load_intel_{_pkey}"
                if st.button("🔍 Load Security Intelligence", key=_load_btn_key,
                             use_container_width=True):
                    tok = github_token or None
                    with st.spinner("Fetching contributor intelligence…"):
                        _jc2 = _load_json_cache(pkg_name, reg_name)
                        contrib_intel = gh_contributors_intel(
                            gh_path, tok, n=5, reg_name=reg_name)
                        _jcache_set(_jc2, "contrib_intel", contrib_intel)
                        _save_json_cache(pkg_name, reg_name, _jc2)
                        # Update session cache too
                        st.session_state.get("profile_cache",{}).get(_pkey, {}) \
                            .__setitem__("contrib_intel", contrib_intel) \
                            if _pkey in st.session_state.get("profile_cache",{}) else None
                    st.rerun()

            # ══════════════════════════════════════════════════════════════
            # SECTION F — OpenSSF Security Scorecard
            # ══════════════════════════════════════════════════════════════
            if openssf:
                st.markdown("")
                st.markdown('<div class="sec-label">🛡️ OpenSSF Security Scorecard</div>',
                            unsafe_allow_html=True)
                score     = openssf.get("score", 0)
                sc_date   = openssf.get("date", "")
                sc_checks = openssf.get("checks", [])
                sc_color  = "#22c55e" if score >= 7 else "#f59e0b" if score >= 4 else "#ef4444"
                sc_label  = "Good" if score >= 7 else "Needs work" if score >= 4 else "Poor"

                # Overall score banner
                _md(f"""
<div style="background:#070d1b;border:1px solid #12243d;border-radius:14px;
            padding:1rem 1.3rem;margin-bottom:0.8rem;display:flex;
            align-items:center;gap:1.5rem">
  <div style="text-align:center;flex-shrink:0">
    <div style="font-size:2.5rem;font-weight:900;color:{sc_color};line-height:1">{score}</div>
    <div style="font-size:0.65rem;color:{sc_color};font-weight:700;
                text-transform:uppercase;letter-spacing:1px">/10 · {sc_label}</div>
  </div>
  <div>
    <div style="color:#f1f5f9;font-weight:700;font-size:0.9rem">
      OpenSSF Security Scorecard</div>
    <div style="color:#4a6580;font-size:0.75rem;margin-top:0.2rem">
      Automated security health check for
      <code style="color:#06b6d4">{gh_path}</code>
      {"· as of " + sc_date if sc_date else ""}
    </div>
    <div style="margin-top:0.5rem">
      <a href="https://securityscorecards.dev/viewer/?uri=github.com/{gh_path}"
         target="_blank"
         style="color:#06b6d4;font-size:0.75rem;text-decoration:none">
        View full report ↗
      </a>
    </div>
  </div>
</div>""")

                # Per-check breakdown (2 columns)
                if sc_checks:
                    cols = st.columns(2, gap="small")
                    for i, chk in enumerate(sorted(sc_checks,
                                                    key=lambda x: x.get("score",-1))):
                        chk_name   = chk.get("name","").replace("-"," ")
                        chk_score  = chk.get("score", -1)
                        chk_reason = chk.get("reason","")
                        if chk_score < 0:
                            chk_color, chk_bar = "#4a6580", "—"
                        elif chk_score >= 8:
                            chk_color, chk_bar = "#22c55e", "█" * chk_score + "░" * (10-chk_score)
                        elif chk_score >= 5:
                            chk_color, chk_bar = "#f59e0b", "█" * chk_score + "░" * (10-chk_score)
                        else:
                            chk_color, chk_bar = "#ef4444", "█" * max(chk_score,0) + "░" * (10-max(chk_score,0))

                        with cols[i % 2]:
                            _md(f"""
<div style="background:#0a1e36;border:1px solid #12243d;border-radius:8px;
            padding:0.5rem 0.7rem;margin-bottom:0.4rem">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <span style="color:#94a3b8;font-size:0.73rem;font-weight:600">{chk_name}</span>
    <span style="color:{chk_color};font-size:0.73rem;font-weight:800">
      {chk_score if chk_score>=0 else "N/A"}/10
    </span>
  </div>
  <div style="color:{chk_color};font-size:0.65rem;font-family:monospace;
              letter-spacing:0.5px;margin:0.2rem 0">{chk_bar}</div>
  <div style="color:#2e6080;font-size:0.67rem">{_trunc(chk_reason,80)}</div>
</div>""")

            # ══════════════════════════════════════════════════════════════
            # SECTION G — Live CVE Intelligence Feed
            # ══════════════════════════════════════════════════════════════
            st.markdown("")
            st.markdown('<div class="sec-label">🚨 Live CVE Intelligence Feed</div>',
                        unsafe_allow_html=True)

            _cve_eco_supported = reg_name in _REG_TO_OSV_ECO

            # Fetch directly via @st.cache_data — completely independent of the
            # session_state / JSON cache system, so it ALWAYS reflects live API data.
            if _cve_eco_supported:
                with st.spinner("Fetching live CVE data…"):
                    _cve_tok = globals().get("github_token") or None
                    live_cves = fetch_live_cves(
                        pkg_name, reg_name,
                        gh_path=gh_path, token=_cve_tok)
            else:
                live_cves = []

            if not _cve_eco_supported:
                st.info(f"CVE feed not available for **{reg_name}** — "
                        "covered registries: NPM, PyPI, RubyGems, Maven Central, "
                        "NuGet, crates.io, Go Modules, Packagist.", icon="ℹ️")
            elif not live_cves:
                st.success(f"✅ No known vulnerabilities found for **{pkg_name}** "
                           f"on **{reg_name}** (OSV.dev + GitHub Advisory Database).",
                           icon="🛡️")
            else:
                # ── Summary banner ────────────────────────────────────────
                _crit  = sum(1 for c in live_cves if c.get("severity") == "CRITICAL")
                _high  = sum(1 for c in live_cves if c.get("severity") == "HIGH")
                _med   = sum(1 for c in live_cves if c.get("severity") == "MEDIUM")
                _low   = sum(1 for c in live_cves if c.get("severity") == "LOW")
                _total = len(live_cves)

                def _sev_badge(label, count, bg, fg="#fff"):
                    if not count: return ""
                    return (f'<span style="background:{bg};color:{fg};font-size:0.72rem;'
                            f'font-weight:800;border-radius:20px;padding:0.18rem 0.65rem;'
                            f'margin-right:0.4rem">{label} {count}</span>')

                badges = (
                    _sev_badge("CRITICAL", _crit, "#7f1d1d") +
                    _sev_badge("HIGH",     _high, "#9a3412") +
                    _sev_badge("MEDIUM",   _med,  "#92400e") +
                    _sev_badge("LOW",      _low,  "#14532d")
                )
                _md(f"""
<div style="background:#1a0a0a;border:1px solid #7f1d1d;border-radius:12px;
            padding:0.9rem 1.2rem;margin-bottom:1rem;
            display:flex;align-items:center;gap:1rem;flex-wrap:wrap">
  <div style="font-size:1.6rem;font-weight:900;color:#ef4444;flex-shrink:0">{_total}</div>
  <div>
    <div style="color:#fca5a5;font-weight:700;font-size:0.88rem">
      Known vulnerabilities · <code style="color:#06b6d4;font-size:0.8rem">{pkg_name}</code>
    </div>
    <div style="margin-top:0.4rem">{badges}</div>
  </div>
  <div style="margin-left:auto;font-size:0.68rem;color:#4a6580;text-align:right">
    🔴 NVD · OSV.dev · GitHub Advisory · Repo Advisories<br>
    <span style="color:#2e6080">4 live sources · refreshes every hour</span>
  </div>
</div>""")

                # ── Per-CVE cards ─────────────────────────────────────────
                _SEV_COLORS = {
                    "CRITICAL": ("#7f1d1d", "#fca5a5", "#ef4444"),
                    "HIGH":     ("#431407", "#fdba74", "#f97316"),
                    "MEDIUM":   ("#451a03", "#fcd34d", "#f59e0b"),
                    "LOW":      ("#052e16", "#86efac", "#22c55e"),
                    "UNKNOWN":  ("#0f172a", "#94a3b8", "#64748b"),
                }

                for cve in live_cves:
                    sev   = cve.get("severity", "UNKNOWN")
                    bg, fg, accent = _SEV_COLORS.get(sev, _SEV_COLORS["UNKNOWN"])
                    cve_id  = cve.get("cve_id", cve.get("id","?"))
                    summary = cve.get("summary","") or "No description available."
                    pub     = cve.get("published","") or "—"
                    mod     = cve.get("modified","") or "—"
                    fixed   = cve.get("fixed_versions",[])
                    vuln_v  = cve.get("vuln_versions",[])
                    refs    = cve.get("references",[])
                    src     = cve.get("source","OSV.dev")
                    osv_url = cve.get("osv_url","")
                    cvss    = cve.get("cvss_score")
                    aliases = cve.get("aliases",[])

                    # CVE ID links
                    cve_links = ""
                    if cve_id.startswith("CVE"):
                        nvd_url = f"https://nvd.nist.gov/vuln/detail/{cve_id}"
                        cve_links += (f'<a href="{nvd_url}" target="_blank" '
                                      f'style="color:{accent};font-size:0.72rem;'
                                      f'text-decoration:none;margin-right:0.7rem">NVD ↗</a>')
                    if osv_url:
                        cve_links += (f'<a href="{osv_url}" target="_blank" '
                                      f'style="color:#06b6d4;font-size:0.72rem;'
                                      f'text-decoration:none;margin-right:0.7rem">{src} ↗</a>')
                    for ref in refs[:2]:
                        rurl = ref.get("url","")
                        if rurl and rurl not in (osv_url,):
                            rlabel = ref.get("type","REF")
                            cve_links += (f'<a href="{rurl}" target="_blank" '
                                          f'style="color:#4a7090;font-size:0.68rem;'
                                          f'text-decoration:none;margin-right:0.5rem">'
                                          f'{rlabel} ↗</a>')

                    fixed_html = ""
                    if fixed:
                        fixed_html = (f'<span style="color:#22c55e;font-size:0.72rem;'
                                      f'font-weight:600">✔ Fixed in: '
                                      f'{", ".join(fixed)}</span>')
                    elif vuln_v:
                        fixed_html = (f'<span style="color:#f59e0b;font-size:0.72rem">'
                                      f'⚠ Affected: {", ".join(vuln_v[:3])}</span>')
                    else:
                        fixed_html = '<span style="color:#4a6580;font-size:0.72rem">Fix version: unknown</span>'

                    cvss_html = ""
                    if cvss is not None:
                        cvss_color = "#ef4444" if cvss>=9 else "#f97316" if cvss>=7 else "#f59e0b" if cvss>=4 else "#22c55e"
                        cvss_html  = (f'<span style="color:{cvss_color};font-size:0.72rem;'
                                      f'font-weight:800;margin-left:0.8rem">CVSS {cvss:.1f}</span>')

                    _safe_summary = _trunc(summary, 220).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                    st.markdown(
                        f'<div style="background:{bg};border:1px solid {accent}33;'
                        f'border-left:4px solid {accent};border-radius:10px;'
                        f'padding:0.75rem 1rem;margin-bottom:0.55rem">'
                        # top row: severity badge + CVE ID + CVSS | dates
                        f'<div style="display:flex;align-items:flex-start;'
                        f'justify-content:space-between;flex-wrap:wrap;gap:0.4rem">'
                        f'<div>'
                        f'<span style="background:{accent};color:#fff;font-size:0.68rem;'
                        f'font-weight:900;border-radius:5px;padding:0.12rem 0.5rem;'
                        f'text-transform:uppercase;letter-spacing:1px">{sev}</span>'
                        f'<span style="color:{fg};font-size:0.88rem;font-weight:800;'
                        f'margin-left:0.6rem;font-family:monospace">{cve_id}</span>'
                        f'{cvss_html}'
                        f'</div>'
                        f'<div style="font-size:0.67rem;color:#2e6080;text-align:right">'
                        f'Published: {pub}<br>Updated: {mod}'
                        f'</div>'
                        f'</div>'
                        # summary
                        f'<div style="color:#cbd5e1;font-size:0.8rem;'
                        f'margin-top:0.45rem;line-height:1.55">{_safe_summary}</div>'
                        # fix / affected versions
                        f'<div style="margin-top:0.5rem;display:flex;flex-wrap:wrap;'
                        f'gap:0.5rem;align-items:center">{fixed_html}</div>'
                        # reference links
                        f'<div style="margin-top:0.45rem">{cve_links}</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )

                # OSV / NVD attribution
                st.markdown(
                    '<div style="color:#2e6080;font-size:0.67rem;margin-top:0.4rem">'
                    '🔴 Live feeds: '
                    '<a href="https://nvd.nist.gov" target="_blank" '
                    'style="color:#06b6d4;text-decoration:none">NVD</a> · '
                    '<a href="https://osv.dev" target="_blank" '
                    'style="color:#06b6d4;text-decoration:none">OSV.dev</a> · '
                    '<a href="https://github.com/advisories" target="_blank" '
                    'style="color:#06b6d4;text-decoration:none">GitHub Advisory DB</a> · '
                    'GitHub Repo Advisories'
                    ' &nbsp;·&nbsp; Repo advisories publish instantly on disclosure '
                    '— before NVD processes them. Cached 1 hr.</div>',
                    unsafe_allow_html=True)

            # ── JSON Export ────────────────────────────────────────────────
            st.markdown("---")
            profile_export = {
                "package":  pkg_name,
                "registry": reg_name,
                "github_repo": {
                    "path":        gh_path,
                    "url":         f"https://github.com/{gh_path}" if gh_path else None,
                    "stars":       repo_info.get("stargazers_count") if repo_info else None,
                    "forks":       repo_info.get("forks_count")      if repo_info else None,
                    "open_issues": repo_info.get("open_issues_count")if repo_info else None,
                    "language":    repo_info.get("language")         if repo_info else None,
                    "license":    (repo_info.get("license") or {}).get("name") if repo_info else None,
                    "last_push":  (repo_info.get("pushed_at","") or "")[:10] if repo_info else None,
                    "topics":      repo_info.get("topics",[]) if repo_info else [],
                    "last_commit_date": lc_display,
                    "recent_commits":   all_cmts,
                },
                "original_author": {
                    "name":           author_name,
                    "github_profile": maint_gh_profiles.get(author_name),
                },
                "maintainers": [
                    {**m, "github_profile": maint_gh_profiles.get(m.get("name",""))}
                    for m in all_m
                ],
                "owner_profile": {
                    "github_handle": handle,
                    "type": "org" if is_org else "user",
                    "profile": ({k: v for k, v in owner_prof.items()
                                 if k not in ("_etype",) and not k.startswith("url")}
                                if owner_prof else None),
                    "top_repositories": [
                        {"name": r.get("name"), "stars": r.get("stargazers_count"),
                         "forks": r.get("forks_count"), "language": r.get("language"),
                         "url": r.get("html_url")}
                        for r in sorted(owner_repos,
                                        key=lambda r: r.get("stargazers_count",0),
                                        reverse=True)[:5]
                    ],
                },
                "security_intel": {
                    "source": f"https://github.com/{gh_path}" if gh_path else None,
                    "openssf_scorecard": openssf,
                    "live_cve_feed": {
                        "total":     len(live_cves),
                        "critical":  sum(1 for c in live_cves if c.get("severity")=="CRITICAL"),
                        "high":      sum(1 for c in live_cves if c.get("severity")=="HIGH"),
                        "medium":    sum(1 for c in live_cves if c.get("severity")=="MEDIUM"),
                        "low":       sum(1 for c in live_cves if c.get("severity")=="LOW"),
                        "sources":   ["NVD","OSV.dev","GitHub Advisory Database","GitHub Repo Advisories"],
                        "vulnerabilities": live_cves,
                    },
                    "key_maintainers": [
                        {
                            "rank":             i + 1,
                            "login":            ci["login"],
                            "name":             ci.get("name", ""),
                            "github_url":       ci.get("github_url", ""),
                            "linkedin_url":     ci.get("linkedin_url"),
                            "twitter_url":      ci.get("twitter_url"),
                            "blog":             ci.get("blog", ""),
                            "email":            ci.get("email", ""),
                            "email_domain_classification": ci.get("email_class", {}),
                            "company":          ci.get("company", ""),
                            "location":         ci.get("location", ""),
                            "bio":              ci.get("bio", ""),
                            "followers":        ci.get("followers", 0),
                            "following":        ci.get("following", 0),
                            "public_repos":     ci.get("public_repos", 0),
                            "public_gists":     ci.get("public_gists", 0),
                            "commits_to_repo":  ci.get("contributions", 0),
                            "account_created":  ci.get("created_at", ""),
                            "account_age_risk": ci.get("account_age", {}),
                            "last_active":      ci.get("last_active", ""),
                            "npm_2fa":          ci.get("npm_2fa", "unknown"),
                            "npm_package_count":ci.get("npm_pkgs"),
                            "gpg_signing":      ci.get("sig_info", {}),
                            "public_orgs":      ci.get("user_orgs", []),
                            "is_official_org_member": ci.get("is_org_member", False),
                            "hireable":         ci.get("hireable"),
                            "site_admin":       ci.get("site_admin", False),
                        }
                        for i, ci in enumerate(contrib_intel)
                    ],
                },
            }
            dl_name = (gh_path or pkg_name).replace("/","_").replace(":","_")
            st.download_button(
                "⬇ Download Full Profile JSON",
                json.dumps(profile_export, indent=2, default=str),
                f"profile_{dl_name}.json",
                "application/json",
                use_container_width=True)

    else:
        st.error("No matches found across any registry.", icon="🔍")
        with st.expander("Format reference", expanded=True):
            st.markdown("""
**Add a space to switch to search mode** — e.g. `Google Guava`, `image recognition`

| Registry | Format | Example |
|---|---|---|
| Maven Central | `groupId:artifactId` | `com.google.guava:guava` |
| Go Modules | full module path | `github.com/gin-gonic/gin` |
| Ansible Galaxy | `namespace.role` | `geerlingguy.ruby` |
| VS Code | `publisher.extension` | `ms-python.python` |
| GHCR | `owner/image` | `myorg/myapp` |
| Nexus Mods | `game/mod-id` | `skyrimspecialedition/12345` |
| Docker Hub | `image` or `org/image` | `nginx` |
            """)

    if all_errors:
        with st.expander(f"⚠️ {len(all_errors)} registry error(s) — click to expand"):
            st.caption("These are unexpected errors (not network timeouts — those are silently skipped).")
            for e in all_errors:
                # Extract adapter name and short message for a clean display
                parts = e.split(":", 2)
                adapter_name = parts[0].replace("Adapter","") if parts else "Unknown"
                short_msg    = parts[-1].strip() if len(parts) > 1 else e
                st.markdown(
                    f'<div style="background:#0d1b2a;border:1px solid #1e3a5f;border-left:3px solid #ef4444;'
                    f'border-radius:8px;padding:0.5rem 0.75rem;margin-bottom:0.4rem;font-size:0.78rem">'
                    f'<span style="color:#ef4444;font-weight:700">{adapter_name}</span>'
                    f'<span style="color:#4a6580"> — </span>'
                    f'<span style="color:#94a3b8">{short_msg[:200]}</span></div>',
                    unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# MONITORING PIPELINE DASHBOARD  — always visible, DB-backed, no scan required
# ══════════════════════════════════════════════════════════════════════════════

if not st.session_state.get("_monitor_checked"):
    st.session_state["_monitor_checked"] = True
    try:
        _due = _get_due_packages()
        for _bg_lib, _bg_reg in _due[:10]:
            try:
                _bg_results, _ = run_audit(_bg_lib, github_token=github_token or None)
                for _bgrow in _bg_results:
                    if _bgrow.get("Registry", "") == _bg_reg:
                        _bg_snap = {
                            "version":      _bgrow.get("Version",      "N/A"),
                            "maintainer":   _bgrow.get("Maintainer",   "—"),
                            "cves":         _bgrow.get("CVEs",         "—"),
                            "license":      _bgrow.get("License",      "—"),
                            "last_updated": _bgrow.get("Last Updated", "—"),
                            "downloads":    _bgrow.get("Downloads",    "—"),
                            "source":       _bgrow.get("Repo",         ""),
                        }
                        _old = _snapshot_get_latest(_bg_lib, _bg_reg)
                        if _old:
                            _diff_and_alert(_bg_lib, _bg_reg, _old, _bg_snap)
                        _snapshot_insert(_bg_lib, _bg_reg, _bg_snap)
                        _monitor_update_checked(_bg_lib, _bg_reg)
                        break
            except Exception:
                pass
    except Exception:
        pass

st.markdown("---")

_dash_col1, _dash_col2, _dash_col3, _dash_col4 = st.columns([4, 1.5, 1.5, 1.5])
with _dash_col1:
    st.markdown("### 🔍 Monitoring Dashboard")
    st.caption(
        "🗄️ **DB-driven** — data flows from `bulk_enroll.py` + `monitor_job.py`. "
        "No UI scan needed."
    )
with _dash_col2:
    if st.button("🔄  Refresh", key="_dash_refresh", use_container_width=True):
        st.rerun()
with _dash_col3:
    _auto_refresh = st.toggle("⏱ Auto-refresh", key="_auto_refresh", value=False)
with _dash_col4:
    import io as _io, csv as _csv
    _rpt_pkgs    = _monitored_get_all()
    _rpt_alerts  = _alerts_get_all(limit=500)
    _rpt_now     = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    _rpt_24h_cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
    _rpt_checked_24h = sum(
        1 for p in _rpt_pkgs
        if p.get("last_checked") and p["last_checked"] > _rpt_24h_cutoff
    )
    _rpt_buf = _io.StringIO()
    _rpt_w   = _csv.writer(_rpt_buf)
    # ── Section 1: Summary ──
    _rpt_w.writerow(["SCAN COVERAGE REPORT"])
    _rpt_w.writerow(["Generated", _rpt_now])
    _rpt_w.writerow(["Total packages monitored", len(_rpt_pkgs)])
    _rpt_w.writerow(["Packages checked in last 24h", _rpt_checked_24h])
    _rpt_w.writerow(["Coverage %", f"{round(_rpt_checked_24h / max(len(_rpt_pkgs),1) * 100)}%"])
    _rpt_w.writerow(["Total alerts", len(_rpt_alerts)])
    _rpt_w.writerow(["Critical alerts", sum(1 for a in _rpt_alerts if a.get("severity") == "critical")])
    _rpt_w.writerow(["High alerts",     sum(1 for a in _rpt_alerts if a.get("severity") == "high")])
    _rpt_w.writerow(["Medium alerts",   sum(1 for a in _rpt_alerts if a.get("severity") == "medium")])
    _rpt_w.writerow(["Check frequency", "Every 6 hours (automated via GitHub Actions)"])
    _rpt_w.writerow([])
    # ── Section 2: Packages ──
    _rpt_w.writerow(["MONITORED PACKAGES"])
    _rpt_w.writerow(["Library","Registry","Enrolled","Last Checked","Next Check","Version","Maintainer","CVEs","License"])
    for _p in _rpt_pkgs:
        _s = _p.get("snapshot") or {}
        _rpt_w.writerow([
            _p.get("library",""), _p.get("registry",""),
            str(_p.get("enrolled_at",""))[:10],
            str(_p.get("last_checked","") or "—")[:16],
            str(_p.get("next_check_at","") or "—")[:16],
            _s.get("version","—"), _s.get("maintainer","—"),
            _s.get("cves","—"),    _s.get("license","—"),
        ])
    _rpt_w.writerow([])
    # ── Section 3: Alerts ──
    _rpt_w.writerow(["ALERTS"])
    _rpt_w.writerow(["Library","Registry","Severity","Field","Before","After","Detected At"])
    _FIELD_LABEL_RPT = {
        "maintainer_email_domain": "Email domain changed (P1 - hijack signal)",
        "maintainer":  "Maintainer changed",
        "cves":        "CVEs changed",
        "license":     "License changed",
        "last_updated":"Last-updated date changed",
    }
    for _a in _rpt_alerts:
        _rpt_w.writerow([
            _a.get("library",""), _a.get("registry",""),
            _a.get("severity","").upper(),
            _FIELD_LABEL_RPT.get(_a.get("field",""), _a.get("field","")),
            _a.get("old_value","") or "—",
            _a.get("new_value","") or "—",
            str(_a.get("detected_at",""))[:16],
        ])
    _rpt_date = datetime.datetime.utcnow().strftime('%Y%m%d')
    _col_csv, _col_json = st.columns(2)
    with _col_csv:
        st.download_button(
            label="📊 Export CSV",
            data=_rpt_buf.getvalue().encode("utf-8"),
            file_name=f"library_scanner_report_{_rpt_date}.csv",
            mime="text/csv",
            use_container_width=True,
            key="_export_report_csv",
        )
    with _col_json:
        import json as _json_mod
        _rpt_json_payload = {
            "generated": _rpt_now,
            "summary": {
                "total_packages":        len(_rpt_pkgs),
                "packages_checked_24h":  _rpt_checked_24h,
                "coverage_pct":          round(_rpt_checked_24h / max(len(_rpt_pkgs), 1) * 100),
                "total_alerts":          len(_rpt_alerts),
                "critical_alerts":       sum(1 for a in _rpt_alerts if a.get("severity") == "critical"),
                "high_alerts":           sum(1 for a in _rpt_alerts if a.get("severity") == "high"),
                "medium_alerts":         sum(1 for a in _rpt_alerts if a.get("severity") == "medium"),
            },
            "packages": [
                {
                    "library":      _p.get("library", ""),
                    "registry":     _p.get("registry", ""),
                    "enrolled_at":  str(_p.get("enrolled_at", ""))[:10],
                    "last_checked": str(_p.get("last_checked", "") or "—")[:16],
                    "next_check_at":str(_p.get("next_check_at", "") or "—")[:16],
                    "version":      (_p.get("snapshot") or {}).get("version", "—"),
                    "maintainer":   (_p.get("snapshot") or {}).get("maintainer", "—"),
                    "cves":         (_p.get("snapshot") or {}).get("cves", "—"),
                    "license":      (_p.get("snapshot") or {}).get("license", "—"),
                }
                for _p in _rpt_pkgs
            ],
            "alerts": [
                {
                    "library":     _a.get("library", ""),
                    "registry":    _a.get("registry", ""),
                    "severity":    _a.get("severity", "").upper(),
                    "field":       _FIELD_LABEL_RPT.get(_a.get("field", ""), _a.get("field", "")),
                    "before":      _a.get("old_value", "") or "—",
                    "after":       _a.get("new_value", "") or "—",
                    "detected_at": str(_a.get("detected_at", ""))[:16],
                }
                for _a in _rpt_alerts
            ],
        }
        st.download_button(
            label="🗂️ Export JSON",
            data=_json_mod.dumps(_rpt_json_payload, indent=2, ensure_ascii=False).encode("utf-8"),
            file_name=f"library_scanner_report_{_rpt_date}.json",
            mime="application/json",
            use_container_width=True,
            key="_export_report_json",
        )

if _auto_refresh:
    import time as _time
    _last_refresh = st.session_state.get("_last_refresh_ts", 0)
    _now_ts       = _time.time()
    if _now_ts - _last_refresh >= 30:
        st.session_state["_last_refresh_ts"] = _now_ts
        _time.sleep(1)
        st.rerun()
    else:
        _secs_left = int(30 - (_now_ts - _last_refresh))
        st.caption(f"⏱ Next refresh in {_secs_left}s")

_mon_alerts_tab, _mon_packages_tab = st.tabs(["🔔  Alerts", "📦  Monitored Packages"])

with _mon_alerts_tab:
    _all_alerts = _alerts_get_all(limit=200)
    _unread_cnt = sum(1 for a in _all_alerts if not a["is_read"])

    _col_a1, _col_a2 = st.columns([5, 1])
    with _col_a1:
        _last_ts = datetime.datetime.utcnow().strftime("%H:%M:%S UTC")
        st.markdown(
            f"**{len(_all_alerts)} alerts** stored · "
            f"**{_unread_cnt} unread** · "
            f"<span style='color:#64748b;font-size:0.78rem'>as of {_last_ts}</span>",
            unsafe_allow_html=True
        )
    with _col_a2:
        if _unread_cnt and st.button("✅  Mark all read", key="_mark_all_read"):
            _alerts_mark_all_read()
            st.rerun()

    if not _all_alerts:
        st.info(
            "No alerts yet. Alerts appear automatically when a monitored package "
            "changes its version, maintainer, CVEs, license, or last-updated date.",
            icon="ℹ️",
        )
    else:
        _SEV_COLOR = {
            "critical": "#ef4444", "high": "#f97316",
            "medium": "#eab308",   "info": "#3b82f6",
        }
        _FIELD_LABEL = {
            "maintainer_email_domain": "Email domain changed (P1 — hijack signal)",
            "version":                 "Version changed",
            "maintainer":              "Maintainer changed",
            "cves":                    "CVEs changed",
            "license":                 "License changed",
            "last_updated":            "Last-updated date changed",
        }
        for _alert in _all_alerts:
            _sev        = _alert.get("severity", "info")
            _fld        = _alert.get("field", "")
            _lib        = _alert.get("library", "")
            _reg        = _alert.get("registry", "")
            _old_v      = _alert.get("old_value", "") or "—"
            _new_v      = _alert.get("new_value", "") or "—"
            _det        = _alert.get("detected_at")
            _det_s      = str(_det)[:16].replace("T", " ") if _det else "—"
            _read       = _alert.get("is_read", False)
            _border_col = _SEV_COLOR.get(_sev, "#3b82f6")
            _alpha      = "0.45" if _read else "1"
            st.markdown(
                f'<div style="background:#0d1b2a;border:1px solid #1e3a5f;'
                f'border-left:4px solid {_border_col};border-radius:8px;'
                f'padding:0.55rem 0.85rem;margin-bottom:0.45rem;opacity:{_alpha}">'
                f'<span style="color:{_border_col};font-weight:700;font-size:0.82rem">'
                f'{_sev.upper()}</span>'
                f'<span style="color:#94a3b8;font-size:0.78rem;margin-left:0.6rem">{_det_s}</span>'
                f'<br><span style="color:#e2e8f0;font-size:0.88rem">'
                f'<b>{_lib}</b> · {_reg}</span>'
                f'<br><span style="color:#94a3b8;font-size:0.8rem">'
                f'{_FIELD_LABEL.get(_fld, _fld)}</span>'
                f'<br><span style="color:#64748b;font-size:0.77rem">'
                f'<b>Before:</b> {_old_v[:120]} &nbsp;→&nbsp; '
                f'<b>After:</b> <span style="color:#e2e8f0">{_new_v[:120]}</span></span>'
                f'</div>',
                unsafe_allow_html=True,
            )

with _mon_packages_tab:
    _all_monitored = _monitored_get_all()

    if not _all_monitored:
        st.info(
            "No packages enrolled yet. Every package you scan is automatically "
            "enrolled in weekly monitoring. Run a scan to get started.",
            icon="ℹ️",
        )
    else:
        st.caption(
            f"{len(_all_monitored)} package(s) under weekly monitoring. "
            "Re-checks happen automatically in the background when you open the app."
        )
        _mon_rows = []
        for _mp in _all_monitored:
            _snap     = _mp.get("snapshot") or {}
            _enrolled = str(_mp.get("enrolled_at",   "") or "")[:10]
            _checked  = str(_mp.get("last_checked",  "") or "—")[:16].replace("T", " ")
            _next_chk = str(_mp.get("next_check_at", "") or "—")[:16].replace("T", " ")
            _mon_rows.append({
                "Library":      _mp.get("library",  ""),
                "Registry":     _mp.get("registry", ""),
                "Enrolled":     _enrolled,
                "Last Checked": _checked,
                "Next Check":   _next_chk,
                "Version":      _snap.get("version",    "—"),
                "Maintainer":   _snap.get("maintainer", "—"),
                "CVEs":         _snap.get("cves",       "—"),
                "License":      _snap.get("license",    "—"),
            })
        _mon_df = pd.DataFrame(_mon_rows)
        st.dataframe(
            _mon_df,
            use_container_width=True,
            hide_index=True,
            height=min(56 + 38 * len(_mon_df), 640),
            column_config={
                "Library":      st.column_config.TextColumn("Library",      width="medium"),
                "Registry":     st.column_config.TextColumn("Registry",     width="small"),
                "Enrolled":     st.column_config.TextColumn("Enrolled",     width="small"),
                "Last Checked": st.column_config.TextColumn("Last Checked", width="medium"),
                "Next Check":   st.column_config.TextColumn("Next Check",   width="medium"),
                "Version":      st.column_config.TextColumn("Version",      width="small"),
                "Maintainer":   st.column_config.TextColumn("Maintainer",   width="medium"),
                "CVEs":         st.column_config.TextColumn("CVEs",         width="small"),
                "License":      st.column_config.TextColumn("License",      width="small"),
            },
        )
