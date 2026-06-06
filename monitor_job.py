"""
monitor_job.py — Standalone monitoring job for Render.com (or any scheduler)

Runs independently of the Streamlit app.
- Connects to Neon DB
- Finds packages whose next_check_at <= NOW()
- Re-fetches each from live registries
- Diffs against last snapshot
- Writes alerts to package_alerts
- Updates next_check_at to 1 day from now
- Sends Slack / email notifications for new alerts

Schedule: daily (0 0 * * *)

Notification env vars (optional — set in .env or Render dashboard):
  SLACK_WEBHOOK_URL  — Slack Incoming Webhook URL
  ALERT_EMAIL_TO     — recipient email address
  ALERT_EMAIL_FROM   — sender email address
  SMTP_HOST          — SMTP server host  (e.g. smtp.gmail.com)
  SMTP_PORT          — SMTP port         (default: 587)
  SMTP_USER          — SMTP username
  SMTP_PASS          — SMTP password
"""

import os
import json
import time
import re
import smtplib
import requests
import psycopg2
import psycopg2.pool
import datetime
from contextlib import contextmanager
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ── Load .env if present ───────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Database connection ────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/registry_intel"
).strip()

# ── Notification config (all optional) ────────────────────────────────────────
SLACK_WEBHOOK_URL   = os.environ.get("SLACK_WEBHOOK_URL",   "")
ALERT_EMAIL_TO      = os.environ.get("ALERT_EMAIL_TO",      "")
ALERT_EMAIL_FROM    = os.environ.get("ALERT_EMAIL_FROM",     "")
SMTP_HOST           = os.environ.get("SMTP_HOST",            "smtp.gmail.com")
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN",  "")
TELEGRAM_CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID",     "")
SMTP_PORT         = int(os.environ.get("SMTP_PORT") or "587")
SMTP_USER         = os.environ.get("SMTP_USER",         "")
SMTP_PASS         = os.environ.get("SMTP_PASS",         "")

TIMEOUT = 10  # seconds per request

# When set, this package is force-checked even if next_check_at is in the future.
# Used by webhook-triggered workflow_dispatch to immediately scan the changed repo.
FORCE_PACKAGE  = os.environ.get("FORCE_PACKAGE",  "").strip()
FORCE_REGISTRY = os.environ.get("FORCE_REGISTRY", "GitHub").strip()

_pg_pool = None

def _get_pg_pool():
    global _pg_pool
    if _pg_pool is None:
        _pg_pool = psycopg2.pool.ThreadedConnectionPool(1, 5, dsn=DATABASE_URL)
    return _pg_pool

@contextmanager
def _pg_conn():
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

# ── Field → severity mapping ───────────────────────────────────────────────────
MONITOR_FIELD_SEVERITY = {
    "cves":         "critical",
    "maintainer":   "high",
    "last_updated": "high",
    "license":      "medium",
    # version removed — routine bumps generate noise, not security signal
}

_DOMAIN_ALIASES = [
    {"google.com", "gmail.com", "googlemail.com"},
    {"microsoft.com", "outlook.com", "hotmail.com", "live.com"},
    {"apple.com", "icloud.com", "me.com", "mac.com"},
    {"facebook.com", "meta.com", "fb.com"},
    {"amazon.com", "amazonaws.com"},
]

_GARBAGE_VERSIONS = {"xd", "test", "dummy", "placeholder", "todo", "tbd", "dev", "wip"}

# ── DB helpers ─────────────────────────────────────────────────────────────────

def get_due_packages():
    """Return list of (library, registry) whose next_check_at <= NOW()."""
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
    except Exception as e:
        log(f"ERROR get_due_packages: {e}")
        return []


def get_latest_snapshot(library, registry):
    """Return the most recent snapshot dict, or None."""
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT snapshot FROM package_snapshots
                   WHERE library = %s AND registry = %s
                   ORDER BY snapped_at DESC LIMIT 1""",
                (library, registry)
            )
            row = cur.fetchone()
            cur.close()
        return row[0] if row else None
    except Exception as e:
        log(f"ERROR get_latest_snapshot ({library}/{registry}): {e}")
        return None


def insert_snapshot(library, registry, snapshot):
    """Insert new snapshot and prune to last 10 per package."""
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO package_snapshots (library, registry, snapped_at, snapshot)
                   VALUES (%s, %s, NOW(), %s::jsonb)""",
                (library, registry, json.dumps(snapshot, default=str))
            )
            cur.execute(
                """DELETE FROM package_snapshots
                   WHERE library = %s AND registry = %s
                     AND id NOT IN (
                         SELECT id FROM package_snapshots
                         WHERE library = %s AND registry = %s
                         ORDER BY snapped_at DESC LIMIT 10
                     )""",
                (library, registry, library, registry)
            )
            cur.close()
    except Exception as e:
        log(f"ERROR insert_snapshot ({library}/{registry}): {e}")


_UNKNOWN_VALUES = {"", "—", "n/a", "none", "unknown", "noassertion", "null"}

def _norm_version(v: str) -> str:
    """Strip leading 'v' so v4.5.1 == 4.5.1."""
    return v.lstrip("vV").strip()

def _norm_license(v: str) -> str:
    """Normalise common license synonyms to a canonical form."""
    v = v.lower().strip()
    v = v.replace(" ", "-").replace("_", "-")
    # Apache synonyms
    v = v.replace("apache-2", "apache-2.0").replace("apache2.0", "apache-2.0")
    # MIT synonyms
    v = v.replace("mit-license", "mit")
    return v

def _norm_maintainer(v: str) -> str:
    """Return only the primary maintainer name, ignoring '+N' co-maintainer count."""
    # e.g. "User · aomarks +12"  →  "user · aomarks"
    import re as _re
    return _re.sub(r'\s*\+\d+\s*$', '', v).strip().lower()

def _is_unknown(v: str) -> bool:
    return v.strip().lower() in _UNKNOWN_VALUES

def write_alerts(library, registry, old_snap, new_snap):
    """Compare snapshots, write alerts to DB, return (count, alert_list).

    alert_list items: (library, registry, severity, field, old_val, new_val)
    Used by the notification functions at the end of main().
    """
    alerts = []

    # GitHub-specific: alert on new release tag.
    # Version excluded globally (NPM/PyPI routine bumps = noise), but GitHub
    # releases are explicit publish events — always worth alerting on.
    if registry == "GitHub":
        _old_ver = re.sub(r'\s+', ' ', str(old_snap.get("version", "") or "").strip())
        _new_ver = re.sub(r'\s+', ' ', str(new_snap.get("version", "") or "").strip())
        if (not _is_unknown(_old_ver) and not _is_unknown(_new_ver)
                and _norm_version(_old_ver) != _norm_version(_new_ver)):
            alerts.append(("medium", "version", _old_ver, _new_ver))

    for field, severity in MONITOR_FIELD_SEVERITY.items():
        old_val = re.sub(r'\s+', ' ', str(old_snap.get(field, "") or "").strip())
        new_val = re.sub(r'\s+', ' ', str(new_snap.get(field, "") or "").strip())

        # Skip if new value is unknown/blank — not a meaningful change
        if _is_unknown(new_val):
            continue

        # Skip if old value was also unknown — data just being populated for first time
        if _is_unknown(old_val):
            continue

        # Field-specific normalisation before comparing
        if field == "version":
            if _norm_version(old_val) == _norm_version(new_val):
                continue
            old_v = re.sub(r'^v', '', old_val.strip().lower())
            if old_v in _GARBAGE_VERSIONS:
                continue
        elif field == "license":
            if _norm_license(old_val) == _norm_license(new_val):
                continue
            # Old license is subset of new (more permissive) — not a security event
            old_norm = re.sub(r'[^a-z0-9]', '', old_val.lower())
            new_norm = re.sub(r'[^a-z0-9]', '', new_val.lower())
            if old_norm and old_norm in new_norm:
                continue
        elif field == "maintainer":
            if _norm_maintainer(old_val) == _norm_maintainer(new_val):
                continue
            # First maintainer name same (format change, not real change)
            def _first_name(s):
                if '·' in s: s = s.split('·', 1)[1].strip()
                s = re.sub(r'\s*\+\d+.*$', '', s).strip()
                return s.split(',')[0].strip().lower()
            if _first_name(old_val) == _first_name(new_val):
                continue
            # WebJars/mvnpm group change — same org family, not a real maintainer change
            _WEBJARS = {"org.webjars.npm", "org.webjars.bower", "org.webjars", "org.mvnpm"}
            def _extract_group(m):
                if '·' in m:
                    return m.split('·', 1)[1].strip().lower()
                return m.strip().lower()
            if _extract_group(old_val) in _WEBJARS and _extract_group(new_val) in _WEBJARS:
                continue
        elif field == "maintainer_email_domain":
            old_d = old_val.lower().strip()
            new_d = new_val.lower().strip()
            _skip = False
            for group in _DOMAIN_ALIASES:
                if old_d in group and new_d in group:
                    _skip = True
                    break
            if _skip:
                continue
        elif field == "last_updated":
            # Only alert when the date moves FORWARD by >30 days.
            # Backwards = fetching from different source (false positive).
            try:
                import datetime as _dt
                old_dt = _dt.datetime.strptime(old_val[:10], "%Y-%m-%d")
                new_dt = _dt.datetime.strptime(new_val[:10], "%Y-%m-%d")
                diff = (new_dt - old_dt).days
                if diff <= 30:
                    continue
            except Exception:
                pass

        if old_val != new_val:
            alerts.append((severity, field, old_val, new_val))

    if not alerts:
        return 0, []

    written = []
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
                    (library, registry, sev, fld, old_v, new_v)
                )
                log(f"  ALERT [{sev.upper()}] {fld}: '{old_v}' -> '{new_v}'")
                written.append((library, registry, sev, fld, old_v, new_v))
            cur.close()
    except Exception as e:
        log(f"ERROR write_alerts ({library}/{registry}): {e}")
        return 0, []

    return len(written), written


def force_due(library, registry):
    """Reset next_check_at to NOW() so the package is picked up as due immediately."""
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """UPDATE monitored_packages
                   SET next_check_at = NOW()
                   WHERE library = %s AND registry = %s""",
                (library, registry)
            )
            cur.close()
        log(f"  FORCE_PACKAGE: reset next_check_at for {library}/{registry}")
    except Exception as e:
        log(f"ERROR force_due ({library}/{registry}): {e}")


def update_checked(library, registry):
    """Push next_check_at forward — 1h for all registries."""
    interval = "1 hour"
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"""UPDATE monitored_packages
                   SET last_checked  = NOW(),
                       next_check_at = NOW() + INTERVAL '{interval}'
                   WHERE library = %s AND registry = %s""",
                (library, registry)
            )
            cur.close()
    except Exception as e:
        log(f"ERROR update_checked ({library}/{registry}): {e}")

# ── Registry fetchers ──────────────────────────────────────────────────────────
# Fetches version, maintainer, CVEs (via OSV.dev), license, last_updated, downloads.

_OSV_ECOSYSTEM = {
    "npm": "npm", "PyPI": "PyPI", "RubyGems": "RubyGems",
    "crates.io": "crates.io", "NuGet": "NuGet",
    "Maven": "Maven", "Packagist": "Packagist",
}

def _fetch_cves(ecosystem: str, pkg: str, version: str) -> str:
    """Query OSV.dev for known vulnerabilities. Returns CVE IDs or 'None'."""
    if not ecosystem or not version or version in ("—", "N/A", ""):
        return "—"
    try:
        r = requests.post(
            "https://api.osv.dev/v1/query",
            json={"version": version, "package": {"name": pkg, "ecosystem": ecosystem}},
            timeout=10
        )
        if r.status_code != 200:
            return "—"
        vulns = r.json().get("vulns", [])
        if not vulns:
            return "None"
        ids = []
        for v in vulns[:10]:
            aliases = v.get("aliases", [])
            cve = next((a for a in aliases if a.startswith("CVE-")), v.get("id", ""))
            if cve:
                ids.append(cve)
        return ", ".join(ids) if ids else f"{len(vulns)} vulnerabilities"
    except Exception:
        return "—"


def fetch_npm(pkg):
    try:
        r = requests.get(f"https://registry.npmjs.org/{pkg.lower()}", timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        d      = r.json()
        latest = d.get("dist-tags", {}).get("latest", "")
        info   = d.get("versions", {}).get(latest, {})
        maints = d.get("maintainers", [])
        if len(maints) > 1:
            maint_str = f"User · {maints[0].get('name','—')} +{len(maints)-1}"
        else:
            maint_str = f"User · {maints[0].get('name','—')}" if maints else "—"
        dl = 0
        try:
            dr = requests.get(
                f"https://api.npmjs.org/downloads/point/last-month/{pkg.lower()}",
                timeout=6
            )
            dl = dr.json().get("downloads", 0)
        except Exception:
            pass
        lic = info.get("license", "—")
        if isinstance(lic, dict):
            lic = lic.get("type", "—")
        return {
            "version":      latest or "N/A",
            "maintainer":   maint_str,
            "cves":         _fetch_cves("npm", pkg, latest),
            "license":      lic or "—",
            "last_updated": (d.get("time", {}).get(latest, "")[:10] if latest else "—"),
            "downloads":    f"{dl:,}" if dl else "—",
        }
    except Exception:
        return None


def fetch_pypi(pkg):
    try:
        r = requests.get(f"https://pypi.org/pypi/{pkg}/json", timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        d       = r.json()
        info    = d.get("info", {})
        version = info.get("version", "N/A")
        # Maintainer: prefer maintainer field, fall back to author
        maint = (info.get("maintainer") or info.get("author") or "").strip()
        if not maint or maint.lower() in ("none", "null", ""):
            maint = "—"
        # Last updated: from latest release upload_time
        last_updated = "—"
        release_files = d.get("releases", {}).get(version, [])
        if release_files:
            t = release_files[-1].get("upload_time", "")
            last_updated = t[:10] if t else "—"
        # License: info field, fall back to classifiers
        lic = (info.get("license") or "").strip()
        if not lic or lic.lower() in ("unknown", "none", ""):
            for clf in info.get("classifiers", []):
                if clf.startswith("License ::"):
                    parts = clf.split(" :: ")
                    if len(parts) >= 3:
                        lic = parts[-1].strip()
                        break
        return {
            "version":      version,
            "maintainer":   f"User · {maint}" if maint != "—" else "—",
            "cves":         _fetch_cves("PyPI", pkg, version),
            "license":      lic or "—",
            "last_updated": last_updated,
            "downloads":    "—",
        }
    except Exception:
        return None


def fetch_rubygems(pkg):
    try:
        r = requests.get(f"https://rubygems.org/api/v1/gems/{pkg}.json", timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        d       = r.json()
        version = d.get("version", "N/A")
        maint   = "—"
        try:
            ro = requests.get(
                f"https://rubygems.org/api/v1/gems/{pkg}/owners.json", timeout=6
            )
            if ro.status_code == 200:
                owners = ro.json()
                names  = [o.get("handle") or o.get("login", "") for o in owners[:3]]
                names  = [n for n in names if n]
                if len(names) > 1:
                    maint = f"User · {names[0]} +{len(names)-1}"
                elif names:
                    maint = f"User · {names[0]}"
        except Exception:
            pass
        lic = (d.get("licenses") or ["—"])[0] or "—"
        return {
            "version":      version,
            "maintainer":   maint,
            "cves":         _fetch_cves("RubyGems", pkg, version),
            "license":      lic,
            "last_updated": (d.get("version_created_at", "") or "")[:10] or "—",
            "downloads":    f"{d.get('downloads', 0):,}",
        }
    except Exception:
        return None


def fetch_nuget(pkg):
    try:
        r = requests.get(
            f"https://api.nuget.org/v3/registration5-semver1/{pkg.lower()}/index.json",
            timeout=TIMEOUT
        )
        if r.status_code != 200:
            return None
        items = r.json().get("items", [])
        if not items:
            return None
        latest  = items[-1].get("items", [{}])[-1].get("catalogEntry", {})
        version = latest.get("version", "N/A")
        authors = latest.get("authors", "") or "—"
        if isinstance(authors, list):
            authors = ", ".join(str(a) for a in authors[:3])
        authors = authors.strip() or "—"
        return {
            "version":      version,
            "maintainer":   f"Org · {authors}" if authors != "—" else "—",
            "cves":         _fetch_cves("NuGet", pkg, version),
            "license":      latest.get("licenseExpression", "—") or "—",
            "last_updated": (latest.get("published", "") or "")[:10] or "—",
            "downloads":    "—",
        }
    except Exception:
        return None


def fetch_github(pkg):
    """Fetch from GitHub API.

    If pkg is 'owner/repo' format (e.g. 'hunter78602/desktop-tutorial'),
    calls the repo API directly — exact repo, no search, no star filter.
    This is how GitHub URL scans are stored by the app after the direct-URL
    feature was added.

    Otherwise falls back to searching by repo name sorted by stars (legacy
    behaviour for packages enrolled before the owner/repo fix).
    """
    try:
        headers = {"Accept": "application/vnd.github+json"}

        # ── Direct owner/repo lookup ──────────────────────────────────────────
        if "/" in pkg:
            r = requests.get(
                f"https://api.github.com/repos/{pkg}",
                headers=headers, timeout=TIMEOUT
            )
            if r.status_code != 200:
                return None
            repo  = r.json()
            owner = repo.get("owner", {}).get("login", "—")
            # Latest release — use published_at not pushed_at so last_updated
            # only changes when a real release is created, not on every commit.
            ver          = "—"
            last_updated = "—"
            try:
                rr = requests.get(
                    f"https://api.github.com/repos/{pkg}/releases/latest",
                    headers=headers, timeout=6
                )
                if rr.status_code == 200:
                    _rel     = rr.json()
                    ver          = _rel.get("tag_name", "—") or "—"
                    last_updated = (_rel.get("published_at") or "")[:10] or "—"
            except Exception:
                pass
            # Security advisories → CVE field
            cve = "—"
            try:
                ar = requests.get(
                    f"https://api.github.com/repos/{pkg}/security-advisories",
                    headers=headers, timeout=6
                )
                if ar.status_code == 200:
                    advs     = ar.json()
                    cve_ids  = [a.get("cve_id") for a in advs if a.get("cve_id")]
                    if cve_ids:
                        cve = ", ".join(cve_ids[:5])
                    elif advs:
                        cve = f"{len(advs)} advisory" if len(advs) == 1 else f"{len(advs)} advisories"
            except Exception:
                pass
            _lic = ((repo.get("license") or {}).get("spdx_id") or "—")
            if _lic == "NOASSERTION":
                _lic = "—"
            return {
                "version":      ver,
                "maintainer":   f"User · {owner}",
                "cves":         cve,
                "license":      _lic,
                "last_updated": last_updated,
                "downloads":    f"{repo.get('stargazers_count', 0):,} stars",
            }

        # ── Legacy: search by name (for packages enrolled before owner/repo fix)
        r = requests.get(
            f"https://api.github.com/search/repositories?q={pkg}+in:name&per_page=1&sort=stars",
            headers=headers, timeout=TIMEOUT
        )
        if r.status_code != 200:
            return None
        items = r.json().get("items", [])
        if not items:
            return None
        repo  = items[0]
        owner = repo.get("owner", {}).get("login", "—")
        ver   = "—"
        try:
            rr = requests.get(
                f"https://api.github.com/repos/{repo['full_name']}/releases/latest",
                headers=headers, timeout=6
            )
            if rr.status_code == 200:
                ver = rr.json().get("tag_name", "—")
        except Exception:
            pass
        return {
            "version":      ver,
            "maintainer":   f"User · {owner}",
            "cves":         "—",
            "license":      (repo.get("license") or {}).get("spdx_id", "—") or "—",
            "last_updated": (repo.get("pushed_at", "") or "")[:10],
            "downloads":    f"{repo.get('stargazers_count', 0):,} stars",
        }
    except Exception:
        return None


def fetch_packagist(pkg):
    try:
        # Search for the package if no vendor prefix
        if "/" not in pkg:
            r = requests.get(
                f"https://packagist.org/search.json?q={pkg}&per_page=1",
                timeout=TIMEOUT
            )
            if r.status_code != 200:
                return None
            results = r.json().get("results", [])
            if not results:
                return None
            pkg = results[0]["name"]
        r = requests.get(f"https://packagist.org/packages/{pkg}.json", timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json().get("package", {})
        versions = data.get("versions", {})
        latest = next(
            (v for v in versions
             if not v.startswith("dev-") and "RC" not in v
             and "alpha" not in v and "beta" not in v),
            next(iter(versions), None)
        )
        if not latest:
            return None
        ver_data = versions[latest]
        authors = ver_data.get("authors", [])
        author_names = [a.get("name", "") for a in authors[:2] if a.get("name")]
        maint = f"User · {author_names[0]}" if author_names else "—"
        lic = ver_data.get("license", ["—"])
        if isinstance(lic, list):
            lic = lic[0] if lic else "—"
        dl = data.get("downloads", {}).get("total", 0)
        return {
            "version":      latest.lstrip("v"),
            "maintainer":   maint,
            "cves":         "—",
            "license":      lic or "—",
            "last_updated": (ver_data.get("time", "") or "")[:10] or "—",
            "downloads":    f"{dl:,}" if dl else "—",
        }
    except Exception:
        return None


def fetch_homebrew(pkg):
    try:
        r = requests.get(
            f"https://formulae.brew.sh/api/formula/{pkg.lower()}.json",
            timeout=TIMEOUT
        )
        if r.status_code != 200:
            return None
        data = r.json()
        version = data.get("versions", {}).get("stable", "N/A")
        homepage = data.get("homepage", "")
        maint = "—"
        if "github.com/" in homepage:
            owner = homepage.rstrip("/").split("github.com/")[-1].split("/")[0]
            if owner:
                maint = f"User · {owner}"
        return {
            "version":      version,
            "maintainer":   maint,
            "cves":         "—",
            "license":      data.get("license", "—") or "—",
            "last_updated": "—",
            "downloads":    "—",
        }
    except Exception:
        return None


def fetch_wordpress_plugins(pkg):
    try:
        r = requests.get(
            f"https://api.wordpress.org/plugins/info/1.0/{pkg.lower()}.json",
            timeout=TIMEOUT
        )
        if r.status_code != 200:
            return None
        data = r.json()
        if not data or isinstance(data, bool) or data.get("error"):
            return None
        version = data.get("version", "N/A")
        author = re.sub(r'<[^>]+>', '', data.get("author", "") or "").strip()
        maint = f"User · {author}" if author else "—"
        dl = data.get("downloaded", 0)
        return {
            "version":      version,
            "maintainer":   maint,
            "cves":         "—",
            "license":      data.get("license", "—") or "—",
            "last_updated": (data.get("last_updated", "") or "")[:10] or "—",
            "downloads":    f"{dl:,}" if dl else "—",
        }
    except Exception:
        return None


def fetch_crates(pkg):
    try:
        ua  = {"User-Agent": "registry-monitor-job/1.0"}
        r   = requests.get(f"https://crates.io/api/v1/crates/{pkg}", timeout=TIMEOUT, headers=ua)
        if r.status_code != 200:
            return None
        data    = r.json()
        crate   = data.get("crate", {})
        version = crate.get("newest_version", "N/A")
        # License from latest version
        lic = "—"
        versions = data.get("versions", [])
        if versions:
            lic = versions[0].get("license", "—") or "—"
        # Maintainer from owner_user endpoint
        maint = "—"
        try:
            ro = requests.get(
                f"https://crates.io/api/v1/crates/{pkg}/owner_user",
                timeout=6, headers=ua
            )
            if ro.status_code == 200:
                owners = ro.json().get("users", [])
                names  = [o.get("login", "") for o in owners[:3] if o.get("login")]
                if len(names) > 1:
                    maint = f"User · {names[0]} +{len(names)-1}"
                elif names:
                    maint = f"User · {names[0]}"
        except Exception:
            pass
        return {
            "version":      version,
            "maintainer":   maint,
            "cves":         _fetch_cves("crates.io", pkg, version),
            "license":      lic,
            "last_updated": (crate.get("updated_at", "") or "")[:10] or "—",
            "downloads":    f"{crate.get('downloads', 0):,}",
        }
    except Exception:
        return None


def fetch_maven(pkg):
    try:
        def _fetch_metadata(g, a):
            """Fetch version + last_updated from maven-metadata.xml directly."""
            g_path = g.replace(".", "/")
            r = requests.get(
                f"https://repo1.maven.org/maven2/{g_path}/{a}/maven-metadata.xml",
                timeout=12
            )
            if r.status_code != 200:
                return None, "—"
            txt = r.text
            version = "N/A"
            m_rel = re.search(r"<release>([^<]+)</release>", txt)
            m_lat = re.search(r"<latest>([^<]+)</latest>", txt)
            if m_rel:
                version = m_rel.group(1).strip()
            elif m_lat:
                version = m_lat.group(1).strip()
            last_updated = "—"
            m_upd = re.search(r"<lastUpdated>(\d{8})\d*</lastUpdated>", txt)
            if m_upd:
                raw = m_upd.group(1)
                last_updated = f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
            return version, last_updated

        if ":" in pkg:
            # Explicit groupId:artifactId — go direct
            g, a = pkg.split(":", 1)
            version, last_updated = _fetch_metadata(g, a)
            if version == "N/A" and last_updated == "—":
                return None
        else:
            # Plain name — try WebJars groups and mvnpm (no Solr needed)
            a = pkg
            g = None
            for group in ["org.webjars.npm", "org.webjars.bower",
                          "org.webjars", "org.mvnpm"]:
                ver, lu = _fetch_metadata(group, pkg)
                if ver != "N/A" or lu != "—":
                    g, version, last_updated = group, ver, lu
                    break
            if not g:
                return None

        return {
            "version":      version,
            "maintainer":   f"Org · {g}",
            "cves":         _fetch_cves("Maven", f"{g}:{a}", version),
            "license":      "—",
            "last_updated": last_updated,
            "downloads":    "—",
        }
    except Exception:
        return None


def fetch_vscode(pkg):
    try:
        if "." not in pkg:
            return None
        payload = {
            "filters": [{"criteria": [{"filterType": 7, "value": pkg}],
                         "pageSize": 1, "pageNumber": 1}],
            "flags": 514
        }
        r = requests.post(
            "https://marketplace.visualstudio.com/_apis/public/gallery/"
            "extensionquery?api-version=7.1-preview.1",
            json=payload,
            headers={"Accept": "application/json;api-version=7.1-preview.1",
                     "Content-Type": "application/json"},
            timeout=TIMEOUT
        )
        if r.status_code != 200:
            return None
        res = r.json().get("results", [])
        if not res or not res[0].get("extensions"):
            return None
        ext = res[0]["extensions"][0]
        pub = ext.get("publisher", {})
        ver = (ext.get("versions") or [{}])[0]
        fid = f"{pub.get('publisherName')}.{ext.get('extensionName')}"
        if fid.lower() != pkg.lower():
            return None
        inst = next((int(s.get("value", 0)) for s in (ext.get("statistics") or [])
                     if s.get("statisticName") == "install"), 0)
        pub_name = pub.get("displayName") or pub.get("publisherName", "—")
        return {
            "version":      ver.get("version", "N/A"),
            "maintainer":   f"Org · {pub_name}",
            "cves":         "—",
            "license":      "—",
            "last_updated": (ver.get("lastUpdated", "") or "")[:10] or "—",
            "downloads":    f"{inst:,}" if inst else "—",
        }
    except Exception:
        return None


def fetch_winget(pkg):
    try:
        headers = {"User-Agent": "RegistryMonitorJob/1.0"}
        pkg = pkg.strip()
        # Stage 1: exact ID lookup
        r = requests.get(
            f"https://api.winget.run/v2/packages/{requests.utils.quote(pkg)}",
            timeout=TIMEOUT, headers=headers
        )
        if r.status_code == 200:
            d = r.json()
            if isinstance(d, dict) and ("Id" in d or "PackageIdentifier" in d):
                pid = d.get("Id") or d.get("PackageIdentifier", "")
                latest = d.get("Latest") or {}
                versions = d.get("Versions") or []
                ver = versions[0] if versions else latest.get("PackageVersion", "N/A")
                pub = latest.get("Publisher") or ""
                return {
                    "version":      ver or "N/A",
                    "maintainer":   f"Org · {pub}" if pub else "—",
                    "cves":         "—",
                    "license":      latest.get("License", "—") or "—",
                    "last_updated": (d.get("UpdatedAt", "") or "")[:10] or "—",
                    "downloads":    "—",
                }
        # Stage 2: search
        r = requests.get(
            f"https://api.winget.run/v2/packages?query={requests.utils.quote(pkg)}&limit=10",
            timeout=TIMEOUT, headers=headers
        )
        if r.status_code == 200:
            d = r.json()
            pkgs = d if isinstance(d, list) else d.get("Packages") or d.get("packages") or []
            pkg_norm = re.sub(r"[^a-z0-9]", "", pkg.lower())
            for p in pkgs:
                pid = (p.get("Id") or p.get("PackageIdentifier") or "").lower()
                name = (p.get("Latest", {}).get("Name") or "").lower()
                if (re.sub(r"[^a-z0-9]", "", name) == pkg_norm or
                        re.sub(r"[^a-z0-9]", "", pid.split(".")[-1]) == pkg_norm):
                    latest = p.get("Latest") or {}
                    versions = p.get("Versions") or []
                    ver = versions[0] if versions else "N/A"
                    pub = latest.get("Publisher") or ""
                    return {
                        "version":      ver,
                        "maintainer":   f"Org · {pub}" if pub else "—",
                        "cves":         "—",
                        "license":      latest.get("License", "—") or "—",
                        "last_updated": (p.get("UpdatedAt", "") or "")[:10] or "—",
                        "downloads":    "—",
                    }
        return None
    except Exception:
        return None


# Registry → fetch function map
REGISTRY_FETCHERS = {
    "NPM":                fetch_npm,
    "PyPI":               fetch_pypi,
    "RubyGems":           fetch_rubygems,
    "NuGet":              fetch_nuget,
    "GitHub":             fetch_github,
    "Crates.io":          fetch_crates,
    "Maven Central":      fetch_maven,
    "Packagist":          fetch_packagist,
    "Homebrew":           fetch_homebrew,
    "WordPress Plugins":  fetch_wordpress_plugins,
    "VS Code Marketplace": fetch_vscode,
    "Winget":             fetch_winget,
}

# ── Logging ────────────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# ── Notifications ──────────────────────────────────────────────────────────────

_SEV_EMOJI = {
    "critical": "🚨",
    "high":     "⚠️",
    "medium":   "🔔",
    "info":     "ℹ️",
}

def _format_alert_lines(all_alerts):
    """Format collected alerts into readable lines for Slack / email."""
    lines = []
    # Sort by severity: critical → high → medium → info
    _order = {"critical": 0, "high": 1, "medium": 2, "info": 3}
    sorted_alerts = sorted(all_alerts, key=lambda a: _order.get(a[2], 9))
    for library, registry, sev, field, old_v, new_v in sorted_alerts:
        emoji = _SEV_EMOJI.get(sev, "•")
        lines.append(
            f"{emoji} *{sev.upper()}* — {library} · {registry}\n"
            f"   {field}: `{old_v[:60]}` → `{new_v[:60]}`"
        )
    return lines


def notify_slack(all_alerts):
    """Send a Slack message via Incoming Webhook. Only runs if SLACK_WEBHOOK_URL is set."""
    if not SLACK_WEBHOOK_URL or not all_alerts:
        return
    try:
        date   = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        n      = len(all_alerts)
        header = f"*Registry Intel — {n} alert{'s' if n > 1 else ''} detected ({date})*"
        lines  = _format_alert_lines(all_alerts)
        body   = "\n\n".join(lines)
        payload = {"text": f"{header}\n\n{body}"}
        r = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        if r.status_code == 200:
            log("Slack notification sent ✓")
        else:
            log(f"Slack notification failed — HTTP {r.status_code}")
    except Exception as e:
        log(f"Slack notification error: {e}")


def _registry_url(library, registry):
    """Return a direct URL to the package page on its registry."""
    pkg = library
    if registry == "NPM":
        return f"https://www.npmjs.com/package/{pkg}"
    if registry == "PyPI":
        return f"https://pypi.org/project/{pkg}"
    if registry == "RubyGems":
        return f"https://rubygems.org/gems/{pkg}"
    if registry == "NuGet":
        return f"https://www.nuget.org/packages/{pkg}"
    if registry == "GitHub":
        repo = pkg if "/" in pkg else pkg
        return f"https://github.com/{repo}"
    if registry == "Crates.io":
        return f"https://crates.io/crates/{pkg}"
    if registry == "Maven Central":
        if ":" in pkg:
            g, a = pkg.split(":", 1)
            return f"https://central.sonatype.com/artifact/{g}/{a}"
        return f"https://central.sonatype.com/search?q={pkg}"
    if registry == "Packagist":
        return f"https://packagist.org/packages/{pkg}"
    if registry == "Homebrew":
        return f"https://formulae.brew.sh/formula/{pkg}"
    if registry == "WordPress Plugins":
        return f"https://wordpress.org/plugins/{pkg}"
    if registry == "VS Code Marketplace":
        return f"https://marketplace.visualstudio.com/items?itemName={pkg}"
    return ""


def notify_telegram(all_alerts):
    """Send a Telegram message via Bot API. Only runs if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not all_alerts:
        return
    import html as _html
    try:
        date   = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        count  = len(all_alerts)
        header = f"🚨 <b>Package Monitor Alert — {date}</b>\n<i>{count} change(s) detected</i>"
        _order = {"critical": 0, "high": 1, "medium": 2, "info": 3}
        sorted_alerts = sorted(all_alerts, key=lambda a: _order.get(a[2], 9))
        _sev_emoji = {"critical": "🚨", "high": "⚠️", "medium": "🔔", "info": "ℹ️"}
        lines = []
        for library, registry, sev, field, old_v, new_v in sorted_alerts:
            emoji = _sev_emoji.get(sev, "•")
            lib   = _html.escape(str(library))
            reg   = _html.escape(str(registry))
            fld   = _html.escape(str(field))
            old   = _html.escape(str(old_v)[:60])
            new   = _html.escape(str(new_v)[:60])
            url   = _registry_url(library, registry)
            link  = f'\n   <a href="{url}">View on {registry}</a>' if url else ""
            lines.append(
                f"{emoji} <b>{sev.upper()}</b> — {lib} · {reg}\n"
                f"   {fld}: <code>{old}</code> → <code>{new}</code>{link}"
            )
        text = f"{header}\n\n" + "\n\n".join(lines)
        url  = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "HTML",
        }, timeout=10)
        if r.status_code == 200:
            log("Telegram notification sent ✓")
        else:
            log(f"Telegram notification failed: {r.status_code} {r.text}")
    except Exception as e:
        log(f"Telegram notification error: {e}")


def notify_email(all_alerts):
    """Send an email digest. Only runs if ALERT_EMAIL_TO and SMTP_* vars are set."""
    if not ALERT_EMAIL_TO or not SMTP_HOST or not SMTP_USER or not SMTP_PASS:
        return
    if not all_alerts:
        return
    try:
        date    = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        n       = len(all_alerts)
        subject = f"[Registry Intel] {n} alert{'s' if n > 1 else ''} detected — {date}"

        # Plain text body
        lines    = _format_alert_lines(all_alerts)
        txt_body = f"Registry Intel — {n} alert(s) on {date}\n\n"
        txt_body += "\n\n".join(
            line.replace("*", "").replace("`", "") for line in lines
        )
        txt_body += "\n\nView full details in your Monitoring Dashboard."

        # HTML body
        html_rows = ""
        _order    = {"critical": 0, "high": 1, "medium": 2, "info": 3}
        _colors   = {"critical": "#ef4444", "high": "#f97316",
                     "medium":   "#eab308", "info": "#3b82f6"}
        sorted_a  = sorted(all_alerts, key=lambda a: _order.get(a[2], 9))
        for library, registry, sev, field, old_v, new_v in sorted_a:
            col = _colors.get(sev, "#3b82f6")
            html_rows += (
                f"<tr>"
                f"<td style='color:{col};font-weight:bold;padding:6px 10px'>{sev.upper()}</td>"
                f"<td style='padding:6px 10px'><b>{library}</b> · {registry}</td>"
                f"<td style='padding:6px 10px'>{field}</td>"
                f"<td style='padding:6px 10px;color:#666'>{old_v[:60]}</td>"
                f"<td style='padding:6px 10px'><b>{new_v[:60]}</b></td>"
                f"</tr>"
            )
        html_body = f"""
        <html><body style='font-family:Arial,sans-serif;color:#222'>
        <h2 style='color:#1e3a5f'>🛡️ Registry Intel — {n} alert(s) on {date}</h2>
        <table border='1' cellpadding='0' cellspacing='0'
               style='border-collapse:collapse;width:100%;font-size:13px'>
          <thead style='background:#f1f5f9'>
            <tr>
              <th style='padding:8px 10px'>Severity</th>
              <th style='padding:8px 10px'>Package</th>
              <th style='padding:8px 10px'>Field</th>
              <th style='padding:8px 10px'>Before</th>
              <th style='padding:8px 10px'>After</th>
            </tr>
          </thead>
          <tbody>{html_rows}</tbody>
        </table>
        <p style='color:#666;font-size:12px;margin-top:16px'>
          View full details in your Monitoring Dashboard.
        </p>
        </body></html>
        """

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = ALERT_EMAIL_FROM or SMTP_USER
        msg["To"]      = ALERT_EMAIL_TO
        msg.attach(MIMEText(txt_body,  "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(msg["From"], [ALERT_EMAIL_TO], msg.as_string())

        log(f"Email notification sent to {ALERT_EMAIL_TO} ✓")
    except Exception as e:
        log(f"Email notification error: {e}")


# ── Main job ───────────────────────────────────────────────────────────────────

def main():
    log("=" * 60)
    log("Registry Monitor Job — starting")
    log("=" * 60)

    # If a specific package was passed via env (webhook-triggered dispatch), force it due.
    if FORCE_PACKAGE:
        log(f"FORCE_PACKAGE={FORCE_PACKAGE} registry={FORCE_REGISTRY}")
        force_due(FORCE_PACKAGE, FORCE_REGISTRY)

    due = get_due_packages()
    log(f"Packages due for re-check: {len(due)}")

    if not due:
        log("Nothing to do — all packages are up to date.")
        return

    total_alerts  = 0
    checked       = 0
    skipped       = 0
    all_new_alerts = []   # collected for end-of-run notifications

    for library, registry in due:
        log(f"\nChecking: {library} / {registry}")

        fetcher = REGISTRY_FETCHERS.get(registry)
        if not fetcher:
            log(f"  SKIP — no fetcher for registry '{registry}'")
            skipped += 1
            update_checked(library, registry)
            continue

        new_snap = fetcher(library)
        if not new_snap:
            log(f"  SKIP — registry returned no data")
            skipped += 1
            update_checked(library, registry)
            continue

        log(f"  version={new_snap.get('version')}  "
            f"maintainer={new_snap.get('maintainer')}  "
            f"cves={new_snap.get('cves')}")

        old_snap = get_latest_snapshot(library, registry)
        if old_snap:
            n, alert_list = write_alerts(library, registry, old_snap, new_snap)
            total_alerts     += n
            all_new_alerts   += alert_list
            if n == 0:
                log(f"  No changes detected")
        else:
            log(f"  First snapshot — no diff yet")

        insert_snapshot(library, registry, new_snap)
        update_checked(library, registry)
        checked += 1

    log("\n" + "=" * 60)
    log(f"Done — checked: {checked}  skipped: {skipped}  alerts raised: {total_alerts}")
    log("=" * 60)

    # ── Send notifications if any alerts were raised ───────────────────────────
    if all_new_alerts:
        log(f"\nSending notifications for {len(all_new_alerts)} alert(s)...")
        notify_slack(all_new_alerts)
        notify_email(all_new_alerts)
        notify_telegram(all_new_alerts)
    else:
        log("No notifications to send.")


if __name__ == "__main__":
    main()
