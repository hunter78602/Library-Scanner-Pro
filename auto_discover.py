"""
auto_discover.py — Auto-enrol the top-50 most popular packages from every major registry
─────────────────────────────────────────────────────────────────────────────────────────
Runs weekly (every Sunday) via GitHub Actions.
For each of 8 registries, fetches the current top-50 packages and auto-enrolls any that
are not already monitored. Already-monitored packages are skipped (no duplicates).

Usage:
    python auto_discover.py              # discover and enrol new packages
    python auto_discover.py --dry-run    # preview without writing to DB
"""

import os, sys, json, time, datetime
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Re-use bulk_enroll's fetchers and DB helpers
from bulk_enroll import (
    _db, is_enrolled,
    fetch_npm, fetch_pypi, fetch_rubygems, fetch_nuget,
    fetch_crates, fetch_maven, fetch_github_direct,
    GITHUB_TOKEN, TIMEOUT,
)

# ── Logging ──────────────────────────────────────────────────────────────────
def log(msg, level=""):
    ts     = datetime.datetime.utcnow().strftime("%H:%M:%S")
    prefix = {"OK": "✅", "SKIP": "⏭ ", "FAIL": "❌", "INFO": "ℹ️ "}.get(level, "  ")
    print(f"[{ts}] {prefix} {msg}", flush=True)


# ── DB bootstrap ─────────────────────────────────────────────────────────────
def _ensure_source_column():
    """Add source column to monitored_packages if not already present."""
    try:
        with _db() as conn:
            cur = conn.cursor()
            cur.execute(
                "ALTER TABLE monitored_packages "
                "ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'manual'"
            )
            cur.close()
    except Exception as e:
        log(f"Could not add source column: {e}", "FAIL")


def _write_enroll_auto(library: str, registry: str, snapshot: dict):
    """Enroll a package tagged as auto_discover with a baseline snapshot."""
    with _db() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO monitored_packages
               (library, registry, enrolled_at, next_check_at, source)
               VALUES (%s, %s, NOW(), NOW() + INTERVAL '1 day', 'auto_discover')
               ON CONFLICT (library, registry) DO NOTHING""",
            (library, registry)
        )
        cur.execute(
            """INSERT INTO package_snapshots
               (library, registry, snapped_at, snapshot)
               VALUES (%s, %s, NOW(), %s::jsonb)""",
            (library, registry, json.dumps(snapshot, default=str))
        )
        # Keep last 10 snapshots per package
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


# ── Top-N discovery functions ─────────────────────────────────────────────────

def discover_npm(limit=50):
    """Top NPM packages by popularity (download-weighted score)."""
    try:
        r = requests.get(
            f"https://registry.npmjs.org/-/v1/search"
            f"?text=is:popular&size={limit}&popularity=1.0&quality=0.0&maintenance=0.0",
            timeout=15
        )
        if r.status_code != 200:
            return []
        return [obj["package"]["name"] for obj in r.json().get("objects", [])
                if obj.get("package", {}).get("name")]
    except Exception as e:
        log(f"NPM discovery failed: {e}", "FAIL")
        return []


def discover_pypi(limit=50):
    """Top PyPI packages by annual download count (hugovk public dataset)."""
    try:
        r = requests.get(
            "https://hugovk.github.io/top-pypi-packages/top-pypi-packages-365-days.min.json",
            timeout=15
        )
        if r.status_code != 200:
            return []
        rows = r.json().get("rows", [])
        return [row["project"] for row in rows[:limit]]
    except Exception as e:
        log(f"PyPI discovery failed: {e}", "FAIL")
        return []


def discover_maven(limit=50):
    """Top Maven Central packages by popularity score."""
    try:
        r = requests.get(
            f"https://search.maven.org/solrsearch/select?q=*&rows={limit}&wt=json",
            timeout=15
        )
        if r.status_code != 200:
            return []
        docs = r.json().get("response", {}).get("docs", [])
        return [f"{d['g']}:{d['a']}" for d in docs if d.get("g") and d.get("a")]
    except Exception as e:
        log(f"Maven discovery failed: {e}", "FAIL")
        return []


def discover_github(limit=50):
    """Top GitHub repos by star count."""
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    try:
        r = requests.get(
            f"https://api.github.com/search/repositories"
            f"?q=stars:%3E50000&sort=stars&order=desc&per_page={min(limit, 100)}",
            headers=headers, timeout=15
        )
        if r.status_code != 200:
            return []
        return [item["full_name"] for item in r.json().get("items", [])[:limit]]
    except Exception as e:
        log(f"GitHub discovery failed: {e}", "FAIL")
        return []


def discover_crates(limit=50):
    """Top Crates.io packages by total download count."""
    try:
        r = requests.get(
            f"https://crates.io/api/v1/crates?page=1&per_page={limit}&sort=downloads",
            headers={"User-Agent": "registry-intel-auto-discover/1.0"},
            timeout=15
        )
        if r.status_code != 200:
            return []
        return [c["name"] for c in r.json().get("crates", []) if c.get("name")]
    except Exception as e:
        log(f"Crates.io discovery failed: {e}", "FAIL")
        return []


def discover_nuget(limit=50):
    """Top NuGet packages by relevance (download-weighted)."""
    try:
        r = requests.get(
            f"https://azuresearch-usnc.nuget.org/query"
            f"?take={limit}&sortBy=relevance&prerelease=false",
            timeout=15
        )
        if r.status_code != 200:
            return []
        return [d["id"] for d in r.json().get("data", []) if d.get("id")]
    except Exception as e:
        log(f"NuGet discovery failed: {e}", "FAIL")
        return []


def discover_rubygems(limit=50):
    """Top RubyGems packages by download count (2 pages × 30 = 60 → cap 50)."""
    packages = []
    try:
        for page in range(1, 3):
            r = requests.get(
                f"https://rubygems.org/api/v1/search.json?query=*&page={page}",
                timeout=15
            )
            if r.status_code != 200:
                break
            gems = r.json()
            if not isinstance(gems, list) or not gems:
                break
            packages.extend(g["name"] for g in gems if g.get("name"))
            if len(packages) >= limit:
                break
            time.sleep(0.5)
    except Exception as e:
        log(f"RubyGems discovery failed: {e}", "FAIL")
    return packages[:limit]


def discover_packagist(limit=50):
    """Top Packagist packages by downloads (official popular endpoint)."""
    packages = []
    try:
        page = 0
        while len(packages) < limit:
            r = requests.get(
                f"https://packagist.org/explore/popular.json?page={page}",
                timeout=15
            )
            if r.status_code != 200:
                break
            data = r.json().get("packages", [])
            if not data:
                break
            packages.extend(p["name"] for p in data if p.get("name"))
            page += 1
            time.sleep(0.5)
    except Exception as e:
        log(f"Packagist discovery failed: {e}", "FAIL")
    return packages[:limit]


# ── Registry table: (name, discovery_fn, snapshot_fn) ────────────────────────

REGISTRIES = [
    ("NPM",           discover_npm,       fetch_npm),
    ("PyPI",          discover_pypi,      fetch_pypi),
    ("Maven Central", discover_maven,     fetch_maven),
    ("Crates.io",     discover_crates,    fetch_crates),
    ("NuGet",         discover_nuget,     fetch_nuget),
    ("RubyGems",      discover_rubygems,  fetch_rubygems),
    ("Packagist",     discover_packagist, None),
    ("GitHub",        discover_github,    None),
]

# Load Packagist fetcher from monitor_job if available
try:
    from monitor_job import fetch_packagist as _mj_packagist
    REGISTRIES[6] = ("Packagist", discover_packagist, _mj_packagist)
except Exception:
    pass


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print("  Auto Discover — Library Scanner Pro")
    if dry_run:
        print("  MODE: DRY RUN — nothing written to DB")
    print(f"  Registries  : {len(REGISTRIES)}")
    print(f"  Cap per reg : 50")
    print(f"  GitHub token: {'✅ Set' if GITHUB_TOKEN else '⚠️  Not set'}")
    print("=" * 60)

    if not dry_run:
        _ensure_source_column()

    total_enrolled = total_skipped = total_failed = 0

    for reg_name, discover_fn, snapshot_fn in REGISTRIES:
        print(f"\n── {reg_name} {'─' * max(0, 44 - len(reg_name))}")
        log(f"Discovering top 50 from {reg_name}...", "INFO")

        packages = discover_fn(50)
        if not packages:
            log(f"No packages returned — skipping {reg_name}", "FAIL")
            continue

        log(f"Got {len(packages)} candidates — checking which are new...", "INFO")
        enrolled = skipped = failed = 0

        for pkg in packages:
            library = pkg.strip()
            if not library:
                continue

            if is_enrolled(library, reg_name):
                log(f"  {library} — already monitored", "SKIP")
                skipped += 1
                continue

            log(f"  Fetching: {library}")

            try:
                if reg_name == "GitHub":
                    parts = library.split("/", 1)
                    if len(parts) != 2:
                        log(f"  Invalid GitHub slug: {library}", "FAIL")
                        failed += 1
                        continue
                    snapshot, err = fetch_github_direct(parts[0], parts[1])
                    if err or not snapshot:
                        log(f"  Failed — {err}", "FAIL")
                        failed += 1
                        continue
                elif snapshot_fn:
                    snapshot = snapshot_fn(library)
                    if not snapshot:
                        log(f"  No data returned from {reg_name}", "FAIL")
                        failed += 1
                        continue
                else:
                    log(f"  No snapshot fetcher configured for {reg_name}", "FAIL")
                    failed += 1
                    continue
            except Exception as e:
                log(f"  Fetch error — {e}", "FAIL")
                failed += 1
                continue

            log(f"    version={snapshot.get('version')}  "
                f"license={snapshot.get('license')}  "
                f"cves={snapshot.get('cves')}")

            if dry_run:
                log(f"    [DRY RUN] Would auto-enrol", "OK")
            else:
                try:
                    _write_enroll_auto(library, reg_name, snapshot)
                    log(f"    Auto-enrolled ✓", "OK")
                except Exception as e:
                    log(f"    DB write failed — {e}", "FAIL")
                    failed += 1
                    continue

            enrolled += 1
            time.sleep(0.3)

        log(f"  {reg_name}: +{enrolled} new  |  {skipped} skipped  |  {failed} failed", "INFO")
        total_enrolled += enrolled
        total_skipped  += skipped
        total_failed   += failed

    print()
    print("=" * 60)
    print(f"  Total new enrolled : {total_enrolled}")
    print(f"  Total skipped      : {total_skipped}  (already monitored)")
    print(f"  Total failed       : {total_failed}")
    print("=" * 60)

    if total_enrolled > 0 and not dry_run:
        print()
        print("  ✅ Done. monitor_job.py will pick up all new packages automatically.")


if __name__ == "__main__":
    main()
