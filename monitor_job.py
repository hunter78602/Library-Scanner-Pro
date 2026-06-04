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
    "version":      "info",
}

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


def write_alerts(library, registry, old_snap, new_snap):
    """Compare snapshots, write alerts to DB, return (count, alert_list).

    alert_list items: (library, registry, severity, field, old_val, new_val)
    Used by the notification functions at the end of main().
    """
    alerts = []
    for field, severity in MONITOR_FIELD_SEVERITY.items():
        old_val = str(old_snap.get(field, "") or "")
        new_val = str(new_snap.get(field, "") or "")
        if old_val != new_val and new_val not in ("", "N/A", "—"):
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
                log(f"  ALERT [{sev.upper()}] {fld}: '{old_v}' → '{new_v}'")
                written.append((library, registry, sev, fld, old_v, new_v))
            cur.close()
    except Exception as e:
        log(f"ERROR write_alerts ({library}/{registry}): {e}")
        return 0, []

    return len(written), written


def update_checked(library, registry):
    """Push next_check_at forward by 1 day."""
    try:
        with _pg_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """UPDATE monitored_packages
                   SET last_checked  = NOW(),
                       next_check_at = NOW() + INTERVAL '1 day'
                   WHERE library = %s AND registry = %s""",
                (library, registry)
            )
            cur.close()
    except Exception as e:
        log(f"ERROR update_checked ({library}/{registry}): {e}")

# ── Registry fetchers ──────────────────────────────────────────────────────────
# Lightweight re-fetch: only pulls version, maintainer, CVEs, license,
# last_updated, downloads — no full Streamlit adapter needed.

def fetch_npm(pkg):
    try:
        r = requests.get(f"https://registry.npmjs.org/{pkg.lower()}", timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        d = r.json()
        latest = d.get("dist-tags", {}).get("latest", "")
        info   = d.get("versions", {}).get(latest, {})
        maint  = d.get("maintainers", [{}])
        maint_name = maint[0].get("name", "—") if maint else "—"
        # Downloads
        dl = 0
        try:
            dr = requests.get(
                f"https://api.npmjs.org/downloads/point/last-month/{pkg.lower()}",
                timeout=6
            )
            dl = dr.json().get("downloads", 0)
        except Exception:
            pass
        return {
            "version":      latest or "N/A",
            "maintainer":   f"User · {maint_name}",
            "cves":         "—",
            "license":      info.get("license", "—"),
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
        d = r.json()
        info = d.get("info", {})
        return {
            "version":      info.get("version", "N/A"),
            "maintainer":   f"User · {info.get('author', '—')}",
            "cves":         "—",
            "license":      info.get("license", "—") or "—",
            "last_updated": "—",
            "downloads":    "—",
        }
    except Exception:
        return None


def fetch_rubygems(pkg):
    try:
        r = requests.get(f"https://rubygems.org/api/v1/gems/{pkg}.json", timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        d = r.json()
        return {
            "version":      d.get("version", "N/A"),
            "maintainer":   "—",
            "cves":         "—",
            "license":      (d.get("licenses") or ["—"])[0],
            "last_updated": (d.get("version_created_at", "") or "")[:10],
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
        latest = items[-1].get("items", [{}])[-1].get("catalogEntry", {})
        return {
            "version":      latest.get("version", "N/A"),
            "maintainer":   "—",
            "cves":         "—",
            "license":      latest.get("licenseExpression", "—") or "—",
            "last_updated": (latest.get("published", "") or "")[:10],
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


def fetch_crates(pkg):
    try:
        r = requests.get(f"https://crates.io/api/v1/crates/{pkg}", timeout=TIMEOUT,
                         headers={"User-Agent": "registry-monitor-job/1.0"})
        if r.status_code != 200:
            return None
        d    = r.json().get("crate", {})
        ver  = d.get("newest_version", "N/A")
        return {
            "version":      ver,
            "maintainer":   "—",
            "cves":         "—",
            "license":      "—",
            "last_updated": (d.get("updated_at", "") or "")[:10],
            "downloads":    f"{d.get('downloads', 0):,}",
        }
    except Exception:
        return None


def fetch_maven(pkg):
    try:
        # pkg format: groupId:artifactId
        parts = pkg.split(":")
        if len(parts) != 2:
            return None
        g, a = parts
        r = requests.get(
            f"https://search.maven.org/solrsearch/select?q=g:{g}+AND+a:{a}&rows=1&wt=json",
            timeout=TIMEOUT
        )
        if r.status_code != 200:
            return None
        docs = r.json().get("response", {}).get("docs", [])
        if not docs:
            return None
        doc = docs[0]
        return {
            "version":      doc.get("latestVersion", "N/A"),
            "maintainer":   f"Org · {g}",
            "cves":         "—",
            "license":      "—",
            "last_updated": "—",
            "downloads":    "—",
        }
    except Exception:
        return None


# Registry → fetch function map
REGISTRY_FETCHERS = {
    "NPM":           fetch_npm,
    "PyPI":          fetch_pypi,
    "RubyGems":      fetch_rubygems,
    "NuGet":         fetch_nuget,
    "GitHub":        fetch_github,
    "Crates.io":     fetch_crates,
    "Maven Central": fetch_maven,
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


def notify_telegram(all_alerts):
    """Send a Telegram message via Bot API. Only runs if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not all_alerts:
        return
    try:
        date  = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        count = len(all_alerts)
        header = f"🚨 *Package Monitor Alert — {date}*\n_{count} change(s) detected_"
        lines  = _format_alert_lines(all_alerts)
        body   = "\n\n".join(lines)
        text   = f"{header}\n\n{body}"
        url    = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "Markdown",
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
            continue

        new_snap = fetcher(library)
        if not new_snap:
            log(f"  SKIP — registry returned no data")
            skipped += 1
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
