"""
diff_scanner.py — Zero-day supply chain detection via version diff analysis.

Supported registries: PyPI, NPM

Flow:
  1. Download old + new version artifacts (wheel for PyPI, tarball for NPM)
  2. Extract all text files from both
  3. Compute added lines (new vs old — only + lines, plus entirely new files)
  4. Load YAML rules from rules/<registry>.yaml
  5. Score: sum(rule.weight * location_multiplier) for all matched rules
  6. score >= ALERT_THRESHOLD  →  hit=True, caller sends alert

Threshold: 40  (same convention as PyDiffWatch)
"""

import io
import os
import re
import difflib
import tarfile
import zipfile
import json
from pathlib import Path

import requests
import yaml

# ── Constants ─────────────────────────────────────────────────────────────────
ALERT_THRESHOLD = 40
MAX_ARTIFACT_MB = 10          # skip artifacts larger than this
RULES_DIR       = Path(__file__).parent / "rules"

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "LibraryScannerPro/1.0"})

# ── Location multipliers ───────────────────────────────────────────────────────
# Files that auto-execute at install time get a higher multiplier so the same
# rule fires harder when it appears in a dangerous location.
_LOC_RULES = [
    (r"setup\.py$",          3.0),
    (r"\.pth$",              3.0),   # Python path hooks — auto-exec on startup
    (r"install\.sh$",        3.0),
    (r"__post_install__",    3.0),
    (r"setup\.cfg$",         2.0),
    (r"pyproject\.toml$",    2.0),
    (r"Makefile$",           2.0),
    (r"package\.json$",      2.5),
    (r"(^|/)tests?/",        0.2),   # test files — low weight
    (r"_test\.",             0.2),
    (r"spec\.",              0.2),
]

def _loc_weight(filename: str) -> float:
    fl = filename.replace("\\", "/").lower()
    for pattern, weight in _LOC_RULES:
        if re.search(pattern, fl):
            return weight
    return 1.0


# ── Rule loading ───────────────────────────────────────────────────────────────
def _load_rules(registry: str) -> list:
    key = {"PyPI": "pypi", "NPM": "npm", "npm": "npm"}.get(registry)
    if not key:
        return []
    path = RULES_DIR / f"{key}.yaml"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or []


# ── Rule matching ──────────────────────────────────────────────────────────────
def _match(rule: dict, lines: list, filename: str) -> bool:
    """Return True if the rule fires on added_lines for the given file."""
    # file_pattern restricts rule to specific files
    fp = rule.get("file_pattern")
    if fp and not re.search(fp, filename.replace("\\", "/"), re.I):
        return False

    m   = rule.get("match", {})
    txt = "\n".join(lines)

    # all: every sub-pattern must appear somewhere in the combined text
    if "all" in m:
        return all(
            bool(re.search(
                p["regex"] if isinstance(p, dict) else p,
                txt, re.I | re.M
            ))
            for p in m["all"]
        )

    # any: at least one pattern matches at least one line
    if "any" in m:
        for p in m["any"]:
            pat = p["regex"] if isinstance(p, dict) else p
            if any(re.search(pat, line, re.I) for line in lines):
                return True
        return False

    # top-level regex shorthand
    if "regex" in m:
        return bool(re.search(m["regex"], txt, re.I | re.M))

    return False


# ── Archive extraction ─────────────────────────────────────────────────────────
_TEXT_EXTS = {
    ".py", ".js", ".ts", ".json", ".yaml", ".yml",
    ".sh", ".cfg", ".toml", ".txt", ".pth", ".rb",
    ".go", ".rs", ".lock", ".md", ".ini", ".bat", ".ps1",
}
_SKIP_EXTS = {
    ".pyc", ".pyo", ".png", ".jpg", ".jpeg", ".gif", ".ico",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".so", ".dll", ".exe", ".bin",
    ".zip", ".tar", ".gz", ".bz2", ".xz",
    ".pdf", ".doc", ".docx",
}

def _is_text(filename: str) -> bool:
    ext = Path(filename.lower()).suffix
    if ext in _SKIP_EXTS:
        return False
    if ext in _TEXT_EXTS:
        return True
    return ext == ""   # no extension — may be a script

def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return ""

def _extract_wheel(data: bytes) -> dict:
    """Extract text files from a .whl (zip) file."""
    files = {}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                if _is_text(name):
                    try:
                        with zf.open(name) as f:
                            files[name] = _decode(f.read())
                    except Exception:
                        pass
    except Exception:
        pass
    return files

def _extract_tgz(data: bytes) -> dict:
    """Extract text files from a .tar.gz file."""
    files = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            for member in tf.getmembers():
                if member.isfile() and _is_text(member.name):
                    try:
                        f = tf.extractfile(member)
                        if f:
                            files[member.name] = _decode(f.read())
                    except Exception:
                        pass
    except Exception:
        pass
    return files


# ── Registry fetchers ──────────────────────────────────────────────────────────
def _pypi_files(pkg: str, version: str) -> dict:
    """Return {filename: content} for all text files in the PyPI artifact."""
    try:
        r = _SESSION.get(
            f"https://pypi.org/pypi/{pkg}/{version}/json", timeout=10
        )
        if r.status_code != 200:
            return {}
        meta  = r.json()
        urls  = meta.get("urls") or meta.get("releases", {}).get(version, [])

        # prefer wheel, fallback to sdist
        artifact = (
            next((u for u in urls if u["filename"].endswith(".whl")), None)
            or next((u for u in urls if u["filename"].endswith(".tar.gz")), None)
        )
        if not artifact:
            return {}
        if artifact.get("size", 0) > MAX_ARTIFACT_MB * 1024 * 1024:
            return {}

        data = _SESSION.get(artifact["url"], timeout=20).content
        return (
            _extract_wheel(data)
            if artifact["filename"].endswith(".whl")
            else _extract_tgz(data)
        )
    except Exception:
        return {}

def _npm_files(pkg: str, version: str) -> dict:
    """Return {filename: content} for all text files in the NPM tarball."""
    try:
        r = _SESSION.get(
            f"https://registry.npmjs.org/{pkg}/{version}", timeout=10
        )
        if r.status_code != 200:
            return {}
        tarball_url = r.json().get("dist", {}).get("tarball", "")
        if not tarball_url:
            return {}

        dl = _SESSION.get(tarball_url, timeout=20)
        if len(dl.content) > MAX_ARTIFACT_MB * 1024 * 1024:
            return {}
        return _extract_tgz(dl.content)
    except Exception:
        return {}

_FETCH = {
    "PyPI": _pypi_files,
    "NPM":  _npm_files,
    "npm":  _npm_files,
}


# ── Diff computation ───────────────────────────────────────────────────────────
def _diff(old_files: dict, new_files: dict) -> list:
    """
    Return list of (filename, added_lines).
    added_lines = lines that appear in new but not in old.
    Entirely new files have all non-empty lines treated as added.
    """
    results = []
    for fname, new_content in new_files.items():
        old_content = old_files.get(fname, "")
        if old_content == new_content:
            continue

        if not old_content:
            # Brand-new file — all non-empty lines are "added"
            added = [l for l in new_content.splitlines() if l.strip()]
        else:
            diff = difflib.unified_diff(
                old_content.splitlines(),
                new_content.splitlines(),
                lineterm="",
            )
            added = [
                l[1:]  # strip leading '+'
                for l in diff
                if l.startswith("+") and not l.startswith("+++")
            ]

        if added:
            results.append((fname, added))
    return results


# ── Scoring ────────────────────────────────────────────────────────────────────
def _score_diff(diff_results: list, rules: list) -> tuple:
    """
    Returns (total_score, findings).
    findings: list of dicts — one per (rule, file) pair that fired.
    """
    total    = 0
    findings = []

    for fname, added_lines in diff_results:
        loc = _loc_weight(fname)
        for rule in rules:
            if _match(rule, added_lines, fname):
                base   = rule["weight"]
                scaled = rule.get("location_scaled", False)
                raw    = int(base * loc) if scaled else base
                total += raw
                findings.append({
                    "rule_id":   rule["id"],
                    "desc":      rule.get("description", ""),
                    "filename":  fname,
                    "weight":    base,
                    "raw_score": raw,
                })

    return total, findings


# ── DB helpers ─────────────────────────────────────────────────────────────────
def _ensure_table(conn):
    """Create zero_day_findings table if it doesn't exist."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS zero_day_findings (
            id          SERIAL PRIMARY KEY,
            library     TEXT          NOT NULL,
            registry    TEXT          NOT NULL,
            old_version TEXT,
            new_version TEXT,
            score       INTEGER,
            findings    JSONB,
            summary     TEXT,
            detected_at TIMESTAMPTZ   DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()

def save_finding(conn, library: str, registry: str,
                 old_ver: str, new_ver: str, result: dict):
    """Persist a zero-day finding to Neon DB."""
    try:
        _ensure_table(conn)
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO zero_day_findings
               (library, registry, old_version, new_version, score, findings, summary)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                library, registry, old_ver, new_ver,
                result["score"],
                json.dumps(result["findings"]),
                result["summary"],
            ),
        )
        conn.commit()
        cur.close()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


# ── Public API ─────────────────────────────────────────────────────────────────
def scan(library: str, registry: str,
         old_version: str, new_version: str) -> dict | None:
    """
    Scan the diff between old_version and new_version of a package.

    Returns:
        {
            "score":    int,          # total risk score
            "findings": list[dict],   # one entry per fired rule
            "summary":  str,          # human-readable one-liner
            "hit":      bool,         # True if score >= ALERT_THRESHOLD
        }
        or None if the registry is unsupported or artifact fetch failed.
    """
    fetch_fn = _FETCH.get(registry)
    if not fetch_fn:
        return None

    old_files = fetch_fn(library, old_version) if old_version else {}
    new_files = fetch_fn(library, new_version)
    if not new_files:
        return None

    rules          = _load_rules(registry)
    diff_results   = _diff(old_files, new_files)
    score, findings = _score_diff(diff_results, rules)

    # Build a short human-readable summary (top 5 findings)
    top = sorted(findings, key=lambda f: f["raw_score"], reverse=True)[:5]
    parts = [
        f"{f['rule_id']} in {Path(f['filename']).name} (+{f['raw_score']})"
        for f in top
    ]
    summary = (
        f"Score {score}: " + ", ".join(parts)
        if parts
        else f"Score {score}: clean"
    )

    return {
        "score":    score,
        "findings": findings,
        "summary":  summary,
        "hit":      score >= ALERT_THRESHOLD,
    }
