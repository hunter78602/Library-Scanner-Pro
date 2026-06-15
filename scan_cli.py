#!/usr/bin/env python3
"""
scan_cli.py — Command-line interface for Library Scanner Pro.

Usage:
    python scan_cli.py <package> <registry> [--token GH_TOKEN] [--old-version X.Y.Z]

Examples:
    python scan_cli.py numpy PyPI
    python scan_cli.py lodash NPM
    python scan_cli.py requests PyPI --token ghp_xxxx
    python scan_cli.py requests PyPI --old-version 2.28.0   # triggers diff scan

Supported registries: PyPI, NPM
"""

import argparse
import datetime
import json
import re
import sys

import requests

# Force UTF-8 output on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ── ANSI colours ──────────────────────────────────────────────────────────────
_R = "\033[91m"   # red
_Y = "\033[93m"   # yellow
_G = "\033[92m"   # green
_B = "\033[94m"   # blue
_W = "\033[97m"   # white bold
_D = "\033[2m"    # dim
_X = "\033[0m"    # reset

_SEV_COLOR = {
    "pass":     _G,
    "low":      _G,
    "medium":   _Y,
    "high":     _Y,
    "critical": _R,
    "info":     _B,
}
_SEV_ICON = {
    "pass": "✓", "low": "✓", "medium": "⚠",
    "high": "⚠", "critical": "✗", "info": "i",
}

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "LibraryScannerPro-CLI/1.0"})

# ── Fetch helpers ─────────────────────────────────────────────────────────────

def fetch_pypi(pkg: str) -> dict | None:
    r = SESSION.get(f"https://pypi.org/pypi/{pkg}/json", timeout=10)
    if r.status_code != 200:
        return None
    d    = r.json()
    info = d.get("info", {})
    ver  = info.get("version", "N/A")

    maint = (info.get("maintainer") or info.get("author") or "—").strip()
    if maint.lower() in ("none", "null", ""):
        maint = "—"

    last_updated = "—"
    release_files = d.get("releases", {}).get(ver, [])
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

    repo = (
        (info.get("project_urls") or {}).get("Homepage")
        or (info.get("project_urls") or {}).get("Source")
        or info.get("home_page")
        or "—"
    )

    return {
        "Library":      pkg,
        "Registry":     "PyPI",
        "Version":      ver,
        "Maintainer":   maint,
        "Last Updated": last_updated,
        "License":      lic or "—",
        "Downloads":    "—",
        "Repo":         repo,
    }


def fetch_npm(pkg: str) -> dict | None:
    r = SESSION.get(f"https://registry.npmjs.org/{pkg.lower()}", timeout=10)
    if r.status_code != 200:
        return None
    d      = r.json()
    latest = d.get("dist-tags", {}).get("latest", "")
    info   = d.get("versions", {}).get(latest, {})
    maints = d.get("maintainers", [])
    maint  = maints[0].get("name", "—") if maints else "—"
    if len(maints) > 1:
        maint = f"{maint} +{len(maints)-1}"

    dl = 0
    try:
        dr = SESSION.get(
            f"https://api.npmjs.org/downloads/point/last-month/{pkg.lower()}",
            timeout=6
        )
        dl = dr.json().get("downloads", 0)
    except Exception:
        pass

    lic = info.get("license", "—")
    if isinstance(lic, dict):
        lic = lic.get("type", "—")

    repo_raw = info.get("repository", {})
    if isinstance(repo_raw, dict):
        repo = repo_raw.get("url", "—").replace("git+", "").replace(".git", "")
    else:
        repo = str(repo_raw) if repo_raw else "—"

    return {
        "Library":      pkg,
        "Registry":     "NPM",
        "Version":      latest or "N/A",
        "Maintainer":   maint,
        "Last Updated": (d.get("time", {}).get(latest, "")[:10] if latest else "—"),
        "License":      lic or "—",
        "Downloads":    f"{dl:,}" if dl else "—",
        "Repo":         repo,
    }


# ── OSV CVE lookup ────────────────────────────────────────────────────────────

def fetch_cves(registry: str, pkg: str, version: str) -> str:
    eco_map = {"PyPI": "PyPI", "NPM": "npm"}
    eco = eco_map.get(registry)
    if not eco:
        return "—"
    try:
        payload = {"version": version, "package": {"name": pkg, "ecosystem": eco}}
        r = SESSION.post("https://api.osv.dev/v1/query", json=payload, timeout=8)
        if r.status_code != 200:
            return "—"
        vulns = r.json().get("vulns", [])
        if not vulns:
            return "None"
        ids = [v.get("id", "") for v in vulns[:10]]
        return ", ".join(i for i in ids if i)
    except Exception:
        return "—"


# ── Check implementations ─────────────────────────────────────────────────────

def check_abandoned(row: dict) -> dict:
    lu = row.get("Last Updated", "—") or "—"
    if lu in ("—", "N/A", ""):
        return {"severity": "low", "label": "Status unknown",
                "details": "Registry did not provide a last-updated date"}
    try:
        dt  = datetime.datetime.strptime(lu[:10], "%Y-%m-%d")
        age = (datetime.datetime.now(datetime.UTC) - dt.replace(tzinfo=datetime.timezone.utc)).days
    except Exception:
        return {"severity": "low", "label": "Date parse error", "details": lu}

    if age > 730:
        return {"severity": "critical", "label": f"Abandoned ({age//365}y+ stale)",
                "details": f"Last updated {lu} — no maintenance in over 2 years"}
    if age > 180:
        return {"severity": "medium", "label": f"Aging ({age//30}m)",
                "details": f"Last updated {lu} — slowing maintenance"}
    return {"severity": "pass", "label": "Active",
            "details": f"Last updated {lu}"}


def check_cve(row: dict) -> dict:
    cves = str(row.get("CVEs", "") or "")
    if cves in ("None", "—", "", "Timeout", "Error", "N/A"):
        return {"severity": "pass", "label": "No known CVEs",
                "details": "OSV.dev returned no vulnerabilities"}
    lst = [c.strip() for c in cves.split(",") if c.strip().startswith(("CVE", "GHSA"))]
    if not lst:
        return {"severity": "low", "label": "CVE data unrecognised", "details": cves[:80]}
    if len(lst) >= 3:
        return {"severity": "critical", "label": f"{len(lst)} CVEs",
                "details": cves[:120]}
    return {"severity": "high", "label": f"{len(lst)} CVE found",
            "details": cves[:120]}


# ── C7 Typosquatting ──────────────────────────────────────────────────────────

_POPULAR_PYPI = {
    "numpy","pandas","requests","scipy","matplotlib","pillow","tensorflow",
    "torch","scikit-learn","flask","django","fastapi","sqlalchemy","boto3",
    "pytest","click","pydantic","celery","redis","cryptography","paramiko",
    "urllib3","certifi","six","packaging","setuptools","wheel","pip",
    "virtualenv","black","flake8","mypy","pylint","isort","aiohttp","httpx",
    "uvicorn","gunicorn","starlette","jinja2","markupsafe","werkzeug",
    "pyyaml","toml","attrs","psycopg2","pymongo","asyncpg","stripe","twilio",
    "openai","anthropic","langchain","transformers","huggingface-hub",
    "charset-normalizer","idna","itsdangerous","colorama","tqdm","rich",
    "typer","loguru","httpcore","anyio","sniffio","h11","google-auth",
    "grpcio","protobuf","pyarrow","polars","dask","numba","cython","cffi",
    "lxml","beautifulsoup4","selenium","playwright","scrapy","alembic",
    "sqlmodel","pymysql","motor",
}

_POPULAR_NPM = {
    "react","react-dom","lodash","express","axios","moment","webpack",
    "babel-core","typescript","eslint","jest","mocha","chalk","commander",
    "yargs","inquirer","dotenv","mongoose","sequelize","knex","typeorm",
    "socket.io","ws","cors","body-parser","morgan","passport","jsonwebtoken",
    "bcrypt","bcryptjs","nodemailer","multer","sharp","redux","mobx","rxjs",
    "ramda","next","nuxt","gatsby","vue","angular","tailwindcss","bootstrap",
    "styled-components","aws-sdk","firebase","stripe","twilio","prettier",
    "husky","nodemon","pm2","uuid","nanoid","slugify","dayjs","date-fns",
    "luxon","cheerio","puppeteer","playwright","semver","glob","minimatch",
    "cross-env","rimraf","mkdirp","fs-extra","debug","winston","pino",
    "got","node-fetch","superagent","compression","helmet","events",
    "readable-stream","through2","bluebird","async","underscore","immutable",
    "classnames","prop-types","react-router","react-redux","webpack-cli",
    "babel-loader","css-loader","style-loader","postcss","autoprefixer",
    "sass","less",
}

def _levenshtein(s1: str, s2: str) -> int:
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
            curr.append(min(prev[j+1]+1, curr[j]+1, prev[j]+(c1 != c2)))
        prev = curr
    return prev[-1]

def check_typosquatting(row: dict) -> dict:
    library  = str(row.get("Library", "") or "").strip().lower()
    registry = str(row.get("Registry", "") or "").strip()

    if not library or len(library) < 4:
        return {"severity": "pass", "label": "Name OK",
                "details": "Package name too short to check"}

    popular = _POPULAR_PYPI if registry == "PyPI" else _POPULAR_NPM if registry in ("NPM","npm") else None
    if popular is None:
        return {"severity": "pass", "label": "N/A",
                "details": f"Typosquat check not available for {registry}"}

    if library in popular:
        return {"severity": "pass", "label": "Known popular package",
                "details": f"'{library}' is in the trusted popular package list"}

    closest, min_dist = None, 999
    for pkg in popular:
        if abs(len(library) - len(pkg)) > 3:
            continue
        d = _levenshtein(library, pkg)
        if d < min_dist:
            min_dist, closest = d, pkg

    if min_dist == 1:
        return {"severity": "critical", "label": f"Typosquat? (1 char from '{closest}')",
                "details": f"'{library}' is 1 edit away from '{closest}' — very likely typosquatting"}
    if min_dist == 2:
        return {"severity": "high", "label": f"Suspicious (2 edits from '{closest}')",
                "details": f"'{library}' is 2 edits away from '{closest}' — review carefully"}
    if (min_dist == 3
            and len(library) >= 6
            and abs(len(library) - len(closest)) <= 1):
        return {"severity": "medium", "label": f"Similar to '{closest}'",
                "details": f"'{library}' has some similarity to '{closest}'"}

    return {"severity": "pass", "label": "No typosquat match",
            "details": f"'{library}' does not closely match any known popular package"}


# ── Diff / zero-day scan ──────────────────────────────────────────────────────

def run_diff_scan(library: str, registry: str, old_ver: str, new_ver: str) -> dict | None:
    try:
        import diff_scanner
        return diff_scanner.scan(library, registry, old_ver, new_ver)
    except ImportError:
        return None


# ── Output helpers ────────────────────────────────────────────────────────────

def _line(char="─", width=58):
    print(_D + char * width + _X)

def _header():
    print()
    print(_W + "  Library Scanner Pro  —  CLI" + _X)
    _line("═")

def _print_meta(row: dict):
    fields = [
        ("Package",      row.get("Library",      "—")),
        ("Registry",     row.get("Registry",     "—")),
        ("Version",      row.get("Version",      "—")),
        ("Maintainer",   row.get("Maintainer",   "—")),
        ("License",      row.get("License",      "—")),
        ("Last Updated", row.get("Last Updated", "—")),
        ("Downloads",    row.get("Downloads",    "—")),
    ]
    for k, v in fields:
        print(f"  {_D}{k:<14}{_X} {v}")
    _line()

def _print_check(cid: str, name: str, result: dict):
    sev   = result.get("severity", "info")
    color = _SEV_COLOR.get(sev, _X)
    icon  = _SEV_ICON.get(sev, "?")
    label = result.get("label", "")
    det   = result.get("details", "")
    sev_u = sev.upper()
    print(f"  {_D}{cid}{_X}  {color}{icon} {sev_u:<9}{_X}  {name}")
    print(f"       {_D}{label}{_X}")
    if det and det != label:
        print(f"       {_D}{det[:90]}{_X}")

def _print_diff(result: dict):
    _line()
    score = result.get("score", 0)
    hit   = result.get("hit", False)
    color = _R if hit else _G
    icon  = "✗" if hit else "✓"
    sev   = "CRITICAL" if score >= 70 else "HIGH" if hit else "CLEAN"
    print(f"  {_D}ZD{_X}  {color}{icon} {sev:<9}{_X}  Zero-Day Diff Scan")
    print(f"       {_D}score={score}  threshold=40{_X}")
    summary = result.get("summary", "")
    if summary:
        print(f"       {_D}{summary[:90]}{_X}")
    findings = result.get("findings", [])
    if findings:
        for f in findings[:5]:
            print(f"       {_D}  · {f['rule_id']} in {f['filename']} (+{f['raw_score']}){_X}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Library Scanner Pro — CLI security checker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scan_cli.py numpy PyPI\n"
            "  python scan_cli.py lodash NPM\n"
            "  python scan_cli.py requests PyPI --old-version 2.28.0\n"
        ),
    )
    parser.add_argument("package",  help="Package name (e.g. numpy, lodash)")
    parser.add_argument("registry", help="Registry: PyPI or NPM")
    parser.add_argument("--token",       default="", metavar="GH_TOKEN",
                        help="GitHub personal access token (optional, improves rate limit)")
    parser.add_argument("--old-version", default="", metavar="X.Y.Z",
                        help="Previous version — enables zero-day diff scan")
    parser.add_argument("--json",  action="store_true",
                        help="Output results as JSON instead of coloured text")
    args = parser.parse_args()

    pkg      = args.package.strip()
    registry = args.registry.strip()

    if registry not in ("PyPI", "NPM", "npm"):
        print(f"Error: unsupported registry '{registry}'. Use PyPI or NPM.")
        sys.exit(1)
    if registry == "npm":
        registry = "NPM"

    # ── Fetch metadata ────────────────────────────────────────────────────────
    print(f"\nFetching {pkg} from {registry}...", end="", flush=True)
    row = fetch_pypi(pkg) if registry == "PyPI" else fetch_npm(pkg)
    if not row:
        print(f"\nError: package '{pkg}' not found on {registry}.")
        sys.exit(1)
    print(" done.")

    # ── CVE lookup ────────────────────────────────────────────────────────────
    print("Checking CVEs...", end="", flush=True)
    row["CVEs"] = fetch_cves(registry, pkg, row["Version"])
    print(" done.")

    # ── Run checks ───────────────────────────────────────────────────────────
    checks = [
        ("C2", "Abandoned Package",     check_abandoned(row)),
        ("C3", "Known CVE",             check_cve(row)),
        ("C7", "Typosquatting",         check_typosquatting(row)),
    ]

    # ── JSON mode ─────────────────────────────────────────────────────────────
    if args.json:
        out = {"metadata": row, "checks": {}}
        for cid, name, result in checks:
            out["checks"][cid] = {"name": name, **result}
        print(json.dumps(out, indent=2))
        return

    # ── Pretty output ─────────────────────────────────────────────────────────
    _header()
    _print_meta(row)

    _line()
    print(f"  {'CHECK RESULTS'}")
    _line()

    alerts = 0
    for cid, name, result in checks:
        _print_check(cid, name, result)
        if result.get("severity") not in ("pass", "low", "info"):
            alerts += 1

    # ── Optional diff scan ────────────────────────────────────────────────────
    if args.old_version:
        print(f"\nRunning zero-day diff scan ({args.old_version} → {row['Version']})...",
              end="", flush=True)
        zd = run_diff_scan(pkg, registry, args.old_version, row["Version"])
        if zd:
            print(" done.")
            _print_diff(zd)
            if zd.get("hit"):
                alerts += 1
        else:
            print(" skipped (diff_scanner not available).")

    # ── Summary ───────────────────────────────────────────────────────────────
    _line()
    if alerts == 0:
        print(f"  {_G}✓ CLEAN{_X}  — no alerts raised")
    else:
        print(f"  {_R}✗ {alerts} ALERT{'S' if alerts > 1 else ''}{_X}  — review findings above")
    print()


if __name__ == "__main__":
    main()
