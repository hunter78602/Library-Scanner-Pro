"""
bulk_enroll.py — Batch-enrol packages from packages.yaml into monitoring
────────────────────────────────────────────────────────────────────────
Reads packages.yaml, fetches a LIVE baseline snapshot for each package,
and registers it in the Neon database.

After running this once, monitor_job.py handles everything daily —
no Streamlit UI interaction needed.

Usage:
    python bulk_enroll.py                 # enrol new packages only (safe to re-run)
    python bulk_enroll.py --force         # re-baseline ALL packages (overwrites existing)
    python bulk_enroll.py --dry-run       # preview without writing anything to DB

Requirements:
    pip install pyyaml psycopg2-binary python-dotenv requests
"""

import os, sys, re, json, time, datetime
import requests
import psycopg2
import psycopg2.pool
from contextlib import contextmanager

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Config ─────────────────────────────────────────────────────────────────────
DATABASE_URL   = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/registry_intel"
).strip()
PACKAGES_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "packages.yaml")
GITHUB_TOKEN   = os.environ.get("GITHUB_TOKEN", "")
TIMEOUT        = 10

# GitHub URL pattern
_GH_URL_RE = re.compile(
    r"(?:https?://)?github\.com/([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+?)(?:\.git)?/?$",
    re.IGNORECASE
)

# ── Logging ─────────────────────────────────────────────────────────────────────
def log(msg, level=""):
    ts     = datetime.datetime.utcnow().strftime("%H:%M:%S")
    prefix = {"OK": "✅", "SKIP": "⏭ ", "FAIL": "❌", "INFO": "ℹ️ "}.get(level, "  ")
    print(f"[{ts}] {prefix} {msg}", flush=True)

# ── DB connection ───────────────────────────────────────────────────────────────
_pool = None

def _get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 5, dsn=DATABASE_URL)
    return _pool

@contextmanager
def _db():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)

# ── DB helpers ──────────────────────────────────────────────────────────────────
def is_enrolled(library, registry):
    """Return True if the package is already in monitored_packages."""
    try:
        with _db() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM monitored_packages WHERE library=%s AND registry=%s",
                (library, registry)
            )
            found = cur.fetchone() is not None
            cur.close()
        return found
    except Exception:
        return False


def has_snapshot(library, registry):
    """Return True if a baseline snapshot already exists."""
    try:
        with _db() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM package_snapshots WHERE library=%s AND registry=%s LIMIT 1",
                (library, registry)
            )
            found = cur.fetchone() is not None
            cur.close()
        return found
    except Exception:
        return False


def write_enroll(library, registry, snapshot):
    """Enrol package and write baseline snapshot to DB."""
    with _db() as conn:
        cur = conn.cursor()
        # Enrol (no-op if already exists)
        cur.execute(
            """INSERT INTO monitored_packages
               (library, registry, enrolled_at, next_check_at)
               VALUES (%s, %s, NOW(), NOW() + INTERVAL '1 day')
               ON CONFLICT (library, registry) DO NOTHING""",
            (library, registry)
        )
        # Baseline snapshot
        cur.execute(
            """INSERT INTO package_snapshots
               (library, registry, snapped_at, snapshot)
               VALUES (%s, %s, NOW(), %s::jsonb)""",
            (library, registry, json.dumps(snapshot, default=str))
        )
        # Prune — keep last 10 per package
        cur.execute(
            """DELETE FROM package_snapshots
               WHERE library=%s AND registry=%s
                 AND id NOT IN (
                     SELECT id FROM package_snapshots
                     WHERE library=%s AND registry=%s
                     ORDER BY snapped_at DESC LIMIT 10
                 )""",
            (library, registry, library, registry)
        )
        cur.close()

# ── Registry fetchers ───────────────────────────────────────────────────────────

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
        if r.status_code != 200: return None
        d      = r.json()
        latest = d.get("dist-tags", {}).get("latest", "")
        info   = d.get("versions", {}).get(latest, {})
        maints = d.get("maintainers", [])
        if len(maints) > 1:
            maint_str = f"User · {maints[0].get('name','—')} +{len(maints)-1}"
        else:
            maint_str = f"User · {maints[0].get('name','—')}" if maints else "—"
        lic = info.get("license", "—")
        if isinstance(lic, dict):
            lic = lic.get("type", "—")
        return {
            "version":      latest or "N/A",
            "maintainer":   maint_str,
            "cves":         _fetch_cves("npm", pkg, latest),
            "license":      lic or "—",
            "last_updated": (d.get("time", {}).get(latest, "") or "")[:10] or "—",
            "downloads":    "—",
            "source":       f"https://www.npmjs.com/package/{pkg.lower()}",
        }
    except Exception:
        return None


def fetch_pypi(pkg):
    try:
        r = requests.get(f"https://pypi.org/pypi/{pkg}/json", timeout=TIMEOUT)
        if r.status_code != 200: return None
        d       = r.json()
        info    = d.get("info", {})
        version = info.get("version", "N/A")
        maint   = (info.get("maintainer") or info.get("author") or "").strip()
        if not maint or maint.lower() in ("none", "null", ""):
            maint = "—"
        last_updated = "—"
        release_files = d.get("releases", {}).get(version, [])
        if release_files:
            t = release_files[-1].get("upload_time", "")
            last_updated = t[:10] if t else "—"
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
            "source":       f"https://pypi.org/project/{pkg}/",
        }
    except Exception:
        return None


def fetch_rubygems(pkg):
    try:
        r = requests.get(f"https://rubygems.org/api/v1/gems/{pkg}.json", timeout=TIMEOUT)
        if r.status_code != 200: return None
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
            "source":       f"https://rubygems.org/gems/{pkg}",
        }
    except Exception:
        return None


def fetch_nuget(pkg):
    try:
        r = requests.get(
            f"https://api.nuget.org/v3/registration5-semver1/{pkg.lower()}/index.json",
            timeout=TIMEOUT
        )
        if r.status_code != 200: return None
        items   = r.json().get("items", [])
        if not items: return None
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
            "source":       f"https://www.nuget.org/packages/{pkg}",
        }
    except Exception:
        return None


def fetch_crates(pkg):
    try:
        ua  = {"User-Agent": "registry-intel-bulk-enroll/1.0"}
        r   = requests.get(f"https://crates.io/api/v1/crates/{pkg}", timeout=TIMEOUT, headers=ua)
        if r.status_code != 200: return None
        data    = r.json()
        crate   = data.get("crate", {})
        version = crate.get("newest_version", "N/A")
        lic     = "—"
        versions = data.get("versions", [])
        if versions:
            lic = versions[0].get("license", "—") or "—"
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
            "source":       f"https://crates.io/crates/{pkg}",
        }
    except Exception:
        return None


def fetch_maven(pkg):
    try:
        parts = pkg.split(":")
        if len(parts) != 2: return None
        g, a  = parts
        r = requests.get(
            f"https://search.maven.org/solrsearch/select?q=g:{g}+AND+a:{a}&rows=1&wt=json",
            timeout=TIMEOUT
        )
        if r.status_code != 200: return None
        docs = r.json().get("response", {}).get("docs", [])
        if not docs: return None
        doc     = docs[0]
        version = doc.get("latestVersion", "N/A")
        last_updated = "—"
        ts = doc.get("timestamp")
        if ts:
            import datetime as _dt
            last_updated = _dt.datetime.utcfromtimestamp(ts / 1000).strftime("%Y-%m-%d")
        return {
            "version":      version,
            "maintainer":   f"Org · {g}",
            "cves":         _fetch_cves("Maven", f"{g}:{a}", version),
            "license":      "—",
            "last_updated": last_updated,
            "downloads":    "—",
            "source":       f"https://search.maven.org/artifact/{g}/{a}",
        }
    except Exception:
        return None


def fetch_github_direct(owner, repo):
    """Fetch a GitHub repo directly by owner/repo — no star filter."""
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    try:
        r = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}",
            headers=headers, timeout=TIMEOUT
        )
        if r.status_code == 404:
            return None, "not found or private"
        if r.status_code == 403:
            return None, "rate limit — set GITHUB_TOKEN env var"
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        rd = r.json()
        # Latest release
        ver, last_updated = "—", "—"
        try:
            rr = requests.get(
                f"https://api.github.com/repos/{owner}/{repo}/releases/latest",
                headers=headers, timeout=6
            )
            if rr.status_code == 200:
                rel          = rr.json()
                ver          = rel.get("tag_name", "—") or "—"
                last_updated = (rel.get("published_at") or "")[:10] or "—"
        except Exception:
            pass
        # Latest tag fallback
        if ver == "—":
            try:
                tr = requests.get(
                    f"https://api.github.com/repos/{owner}/{repo}/tags?per_page=1",
                    headers=headers, timeout=6
                )
                if tr.status_code == 200:
                    tags = tr.json()
                    if tags:
                        ver = tags[0].get("name", "—") or "—"
            except Exception:
                pass
        # Security advisories
        cve = "—"
        try:
            ar = requests.get(
                f"https://api.github.com/repos/{owner}/{repo}/security-advisories",
                headers=headers, timeout=6
            )
            if ar.status_code == 200:
                advs    = ar.json()
                cve_ids = [a.get("cve_id") for a in advs if a.get("cve_id")]
                if cve_ids:
                    cve = ", ".join(cve_ids[:5])
                elif advs:
                    n   = len(advs)
                    cve = f"{n} advisory" if n == 1 else f"{n} advisories"
        except Exception:
            pass
        # License
        lic = (rd.get("license") or {}).get("spdx_id") or "—"
        if lic == "NOASSERTION":
            lic = "—"
        snapshot = {
            "version":      ver,
            "maintainer":   f"User · {owner}",
            "cves":         cve,
            "license":      lic,
            "last_updated": last_updated,
            "downloads":    f"{rd.get('stargazers_count', 0):,} stars",
            "source":       f"https://github.com/{owner}/{repo}",
        }
        return snapshot, None
    except Exception as e:
        return None, str(e)


# Registry → fetcher map
try:
    from monitor_job import (fetch_packagist, fetch_homebrew,
                             fetch_wordpress_plugins, fetch_vscode, fetch_winget)
    _extra = {
        "Packagist":           fetch_packagist,
        "Homebrew":            fetch_homebrew,
        "WordPress Plugins":   fetch_wordpress_plugins,
        "VS Code Marketplace": fetch_vscode,
        "Winget":              fetch_winget,
    }
except Exception:
    _extra = {}

FETCHERS = {
    "NPM":           fetch_npm,
    "PyPI":          fetch_pypi,
    "RubyGems":      fetch_rubygems,
    "NuGet":         fetch_nuget,
    "Crates.io":     fetch_crates,
    "Maven Central": fetch_maven,
    **_extra,
}


# ── Package parser ──────────────────────────────────────────────────────────────
def parse_entry(entry):
    """
    Parse one entry from packages.yaml.
    Returns (library, registry) or None if invalid.

    GitHub URL  → library = "owner/repo"
    Everything  → library = name as-is
    """
    name     = str(entry.get("name", "")).strip()
    registry = str(entry.get("registry", "")).strip()
    if not name or not registry:
        return None

    if registry == "GitHub":
        gh_m = _GH_URL_RE.match(name)
        if gh_m:
            library = f"{gh_m.group(1)}/{gh_m.group(2)}"
        else:
            library = name   # assume already owner/repo
        return library, "GitHub"

    return name, registry


# ── Main ────────────────────────────────────────────────────────────────────────
def main():
    force   = "--force"   in sys.argv
    dry_run = "--dry-run" in sys.argv

    if not os.path.exists(PACKAGES_FILE):
        print(f"ERROR: packages.yaml not found at {PACKAGES_FILE}")
        sys.exit(1)

    with open(PACKAGES_FILE, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    entries = config.get("packages", [])

    print("=" * 60)
    print("  Bulk Enroll — Registry Intelligence Platform")
    if dry_run: print("  MODE: DRY RUN — nothing written to DB")
    if force:   print("  MODE: FORCE  — re-baselining all packages")
    print("=" * 60)
    print(f"  Packages in config : {len(entries)}")
    print(f"  GitHub token       : {'✅ Set' if GITHUB_TOKEN else '⚠️  Not set'}")
    print("=" * 60)
    print()

    enrolled = skipped = failed = 0

    for entry in entries:
        parsed = parse_entry(entry)
        if not parsed:
            log(f"Invalid entry skipped: {entry}", "FAIL")
            failed += 1
            continue

        library, registry = parsed

        # Skip if already enrolled and has a snapshot (unless --force)
        if not force and is_enrolled(library, registry) and has_snapshot(library, registry):
            log(f"{library} / {registry} — already enrolled", "SKIP")
            skipped += 1
            continue

        log(f"Fetching: {library} / {registry}")

        # Fetch baseline
        if registry == "GitHub":
            owner, repo    = library.split("/", 1)
            snapshot, err  = fetch_github_direct(owner, repo)
            if err:
                log(f"  Failed — {err}", "FAIL")
                failed += 1
                continue
        else:
            fetcher  = FETCHERS.get(registry)
            if not fetcher:
                log(f"  No fetcher for registry '{registry}'", "FAIL")
                failed += 1
                continue
            snapshot = fetcher(library)
            if not snapshot:
                log(f"  No data returned from {registry}", "FAIL")
                failed += 1
                continue

        log(f"  version={snapshot.get('version')}  "
            f"license={snapshot.get('license')}  "
            f"cves={snapshot.get('cves')}")

        if dry_run:
            log(f"  [DRY RUN] Would enroll and save baseline", "OK")
        else:
            try:
                write_enroll(library, registry, snapshot)
                log(f"  Enrolled and baseline saved ✓", "OK")
            except Exception as e:
                log(f"  DB write failed — {e}", "FAIL")
                failed += 1
                continue

        enrolled += 1
        time.sleep(0.4)   # gentle rate-limit between API calls

    print()
    print("=" * 60)
    print(f"  Enrolled : {enrolled}")
    print(f"  Skipped  : {skipped}  (already in DB — use --force to re-baseline)")
    print(f"  Failed   : {failed}")
    print("=" * 60)

    if enrolled > 0 and not dry_run:
        print()
        print("  ✅ Done. monitor_job.py will re-check all packages daily.")
        print("     No UI interaction needed from here.")


if __name__ == "__main__":
    main()
