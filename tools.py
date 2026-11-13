"""Tool handlers — endoflife.date API v1 client and the eol_* tools.

Stdlib only: the plugin talks HTTPS to endoflife.date and nothing else.
"""

import difflib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

API_BASE = "https://endoflife.date/api/v1"
SITE_BASE = "https://endoflife.date"
USER_AGENT = "hermes-eol-plugin/0.1.0 (+https://github.com/adriens/hermes-eol-plugin)"
TIMEOUT_S = 10
CACHE_TTL_S = 6 * 3600
MAX_ITEMS = 50
MAX_MAINTAINED = 10

_cache = {}
_cache_lock = threading.Lock()


class ApiError(Exception):
    """An endoflife.date request failed; the message is safe to show the model."""


class NotFound(ApiError):
    pass


def _get(path):
    """GET a v1 endpoint and return its `result`, cached in memory."""
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(path)
        if hit and now - hit[0] < CACHE_TTL_S:
            return hit[1]

    req = urllib.request.Request(
        API_BASE + path,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NotFound(path) from e
        raise ApiError(f"endoflife.date returned HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ApiError(f"endoflife.date unreachable: {e}") from e
    except ValueError as e:
        raise ApiError("endoflife.date returned invalid JSON") from e

    result = payload.get("result")
    with _cache_lock:
        _cache[path] = (now, result)
    return result


def _products():
    return _get("/products") or []


def _resolve_product(name):
    """Return the product document for a name or alias, or raise NotFound."""
    key = (name or "").strip().lower()
    if not key:
        raise NotFound("empty product name")
    try:
        return _get("/products/" + urllib.parse.quote(key, safe=""))
    except NotFound:
        pass
    for p in _products():
        names = [p.get("name", ""), p.get("label", "")] + list(p.get("aliases") or [])
        if key in (n.lower() for n in names if n):
            return _get("/products/" + urllib.parse.quote(p["name"], safe=""))
    raise NotFound(name)


def _search(query, limit=20):
    q = (query or "").strip().lower()
    exact, partial = [], []
    for p in _products():
        names = [p.get("name", ""), p.get("label", "")] + list(p.get("aliases") or [])
        names = [n.lower() for n in names if n]
        fields = names + [(p.get("category") or "").lower()] + [t.lower() for t in p.get("tags") or []]
        if q in names:
            exact.append(p)
        elif any(q in f for f in fields):
            partial.append(p)
    return [
        {
            "product": p.get("name"),
            "label": p.get("label"),
            "category": p.get("category"),
            "aliases": p.get("aliases") or [],
        }
        for p in (exact + partial)[:limit]
    ]


def _not_found(product):
    suggestions = [s["product"] for s in _search(product, limit=5)]
    if not suggestions:
        names = [p.get("name", "") for p in _products()]
        suggestions = difflib.get_close_matches(product.strip().lower(), names, n=5, cutoff=0.75)
    out = {"error": f"Unknown product '{product}' on endoflife.date"}
    if suggestions:
        out["did_you_mean"] = suggestions
    else:
        out["hint"] = "Call eol_search to find the product identifier."
    return out


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _today():
    return datetime.now(timezone.utc).date()


def _release_summary(r):
    latest = r.get("latest") or {}
    return {
        "cycle": r.get("name"),
        "codename": r.get("codename"),
        "released": r.get("releaseDate"),
        "lts": bool(r.get("isLts")),
        "maintained": bool(r.get("isMaintained")),
        "active_support_until": r.get("eoasFrom"),
        "eol": r.get("eolFrom"),
        "is_eol": bool(r.get("isEol")),
        "latest": latest.get("name"),
        "latest_date": latest.get("date"),
    }


def _normalize_version(version):
    v = (version or "").strip()
    if v[:1] in ("v", "V") and v[1:2].isdigit():
        v = v[1:]
    return v


def _match_cycle(releases, version):
    """Pick the release cycle a version belongs to (longest matching prefix)."""
    v = _normalize_version(version).lower()
    best = None
    for r in releases:
        name = str(r.get("name", "")).lower()
        if not name:
            continue
        if v == name or any(v.startswith(name + sep) for sep in (".", "-", "+", "_", " ")):
            if best is None or len(name) > len(str(best.get("name", ""))):
                best = r
    return best


def _version_key(v):
    parts = []
    for chunk in _normalize_version(v).replace("-", ".").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return parts


def _check_one(product, version, warn_days):
    try:
        doc = _resolve_product(product)
    except NotFound:
        return dict(_not_found(product), product=product, version=version, status="unknown")

    releases = doc.get("releases") or []
    rel = _match_cycle(releases, version)
    maintained = [r for r in releases if r.get("isMaintained")]
    # Someone on an LTS line should be pointed at the next LTS, not a short-lived release.
    if rel is not None and rel.get("isLts"):
        newest_maintained = next((r for r in maintained if r.get("isLts")), None)
    else:
        newest_maintained = None
    newest_maintained = newest_maintained or (maintained[0] if maintained else None)
    base = {
        "product": doc.get("name"),
        "label": doc.get("label"),
        "version": version,
        "source": f"{SITE_BASE}/{doc.get('name')}",
    }
    if rel is None:
        return dict(
            base,
            status="unknown",
            error=f"No release cycle of {doc.get('label')} matches version '{version}'",
            known_cycles=[r.get("name") for r in releases[:20]],
        )

    today = _today()
    eol = _parse_date(rel.get("eolFrom"))
    days_left = (eol - today).days if eol else None
    if rel.get("isEol"):
        status = "eol"
    elif rel.get("isEoas"):
        status = "security-only"
    else:
        status = "supported"

    latest = (rel.get("latest") or {}).get("name")
    normalized = _normalize_version(version)
    patch_behind = None
    if latest and normalized.lower() != str(rel.get("name")).lower():
        patch_behind = _version_key(normalized) < _version_key(latest)

    out = dict(
        base,
        cycle=rel.get("name"),
        status=status,
        lts=bool(rel.get("isLts")),
        eol_date=rel.get("eolFrom"),
        days_until_eol=days_left,
        eol_soon=bool(status != "eol" and days_left is not None and days_left <= warn_days),
        active_support_until=rel.get("eoasFrom"),
        latest_patch=latest,
        patch_behind=patch_behind,
    )
    if newest_maintained and newest_maintained is not rel:
        out["upgrade_to"] = {
            "cycle": newest_maintained.get("name"),
            "latest": (newest_maintained.get("latest") or {}).get("name"),
            "eol_date": newest_maintained.get("eolFrom"),
        }
    # The real upgrade options, so the model does not invent intermediate steps or LTS lines.
    out["has_lts_releases"] = any(r.get("isLts") for r in releases)
    out["maintained_cycles"] = [
        {
            "cycle": r.get("name"),
            "lts": bool(r.get("isLts")),
            "active_support_until": r.get("eoasFrom"),
            "eol_date": r.get("eolFrom"),
            "latest": (r.get("latest") or {}).get("name"),
        }
        for r in maintained[:MAX_MAINTAINED]
    ]
    return out


def _int_arg(args, key, default, lo, hi):
    try:
        value = int(args.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def eol_search(args: dict, **kwargs) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return json.dumps({"error": "No query provided"})
    limit = _int_arg(args, "limit", 20, 1, 100)
    try:
        results = _search(query, limit)
    except ApiError as e:
        return json.dumps({"error": str(e)})
    return json.dumps({"query": query, "count": len(results), "results": results})


def eol_product(args: dict, **kwargs) -> str:
    product = (args.get("product") or "").strip()
    if not product:
        return json.dumps({"error": "No product provided"})
    max_releases = _int_arg(args, "max_releases", 15, 1, 200)
    include_eol = args.get("include_eol", True) is not False
    try:
        doc = _resolve_product(product)
    except NotFound:
        return json.dumps(_not_found(product))
    except ApiError as e:
        return json.dumps({"error": str(e)})

    releases = doc.get("releases") or []
    shown = [r for r in releases if include_eol or not r.get("isEol")]
    return json.dumps({
        "product": doc.get("name"),
        "label": doc.get("label"),
        "category": doc.get("category"),
        "version_command": doc.get("versionCommand"),
        "source": f"{SITE_BASE}/{doc.get('name')}",
        "total_cycles": len(releases),
        "maintained_cycles": sum(1 for r in releases if r.get("isMaintained")),
        "releases": [_release_summary(r) for r in shown[:max_releases]],
        "truncated": len(shown) > max_releases,
    })


def eol_check(args: dict, **kwargs) -> str:
    warn_days = _int_arg(args, "warn_days", 180, 0, 3650)
    items = args.get("items")
    if not items and args.get("product"):
        items = [{"product": args.get("product"), "version": args.get("version")}]
    if not items or not isinstance(items, list):
        return json.dumps({"error": "Provide product and version, or items: [{product, version}]"})
    if len(items) > MAX_ITEMS:
        return json.dumps({"error": f"Too many items ({len(items)}); the limit is {MAX_ITEMS}"})

    results = []
    for item in items:
        product = str((item or {}).get("product") or "").strip()
        version = str((item or {}).get("version") or "").strip()
        if not product or not version:
            results.append({"product": product, "version": version, "status": "unknown",
                            "error": "Both product and version are required"})
            continue
        try:
            results.append(_check_one(product, version, warn_days))
        except ApiError as e:
            results.append({"product": product, "version": version, "status": "unknown",
                            "error": str(e)})

    summary = {s: sum(1 for r in results if r.get("status") == s)
               for s in ("supported", "security-only", "eol", "unknown")}
    summary["eol_soon"] = sum(1 for r in results if r.get("eol_soon"))
    return json.dumps({"checked_on": _today().isoformat(), "summary": summary, "results": results})
