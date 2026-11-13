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
USER_AGENT = "hermes-eol-plugin/0.2.0 (+https://github.com/adriens/hermes-eol-plugin)"
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


def _parse_ref_date(value):
    """The reference date for a check: an ISO date, or today when empty."""
    if not value:
        return _today()
    ref = _parse_date(str(value))
    if ref is None:
        raise ValueError(f"Invalid date '{value}', expected YYYY-MM-DD")
    return ref


def _is_eol_at(r, ref):
    eol = _parse_date(r.get("eolFrom"))
    return eol <= ref if eol else bool(r.get("isEol"))


def _is_eoas_at(r, ref):
    eoas = _parse_date(r.get("eoasFrom"))
    return eoas <= ref if eoas else bool(r.get("isEoas"))


def _maintained_at(releases, ref):
    """Cycles released and not end-of-life at `ref`, newest first (API order)."""
    if ref == _today():
        return [r for r in releases if r.get("isMaintained")]
    out = []
    for r in releases:
        released = _parse_date(r.get("releaseDate"))
        if (released is None or released <= ref) and not _is_eol_at(r, ref):
            out.append(r)
    return out


# --- package identifiers (purl, cpe) -> endoflife.date product -----------------

def _identifier_index(kind):
    key = "_index:" + kind
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
            return hit[1]
    index = {}
    for entry in _get("/identifiers/" + kind) or []:
        ident = entry.get("identifier") or ""
        name = (entry.get("product") or {}).get("name")
        if not ident or not name:
            continue
        if kind == "purl":
            ident = _purl_base(ident)[0]
        index.setdefault(ident.lower(), name)
    with _cache_lock:
        _cache[key] = (time.monotonic(), index)
    return index


def _purl_base(purl):
    """Split a purl into (type/namespace/name, version): qualifiers and subpath dropped."""
    s = purl.strip().split("#", 1)[0].split("?", 1)[0]
    version = None
    slash = s.rfind("/")
    at = s.rfind("@")
    if at > slash:
        s, version = s[:at], urllib.parse.unquote(s[at + 1:])
    return urllib.parse.unquote(s).lower(), version


def _cpe_base(cpe):
    """Split a CPE 2.3 or 2.2 URI into (part:vendor:product prefix, version)."""
    parts = cpe.strip().lower().split(":")
    if len(parts) >= 5 and parts[1] == "2.3":
        base, rest = parts[:5], parts[5:]
    elif len(parts) >= 4 and parts[1].startswith("/"):
        base, rest = parts[:4], parts[4:]
    else:
        return None, None
    version = rest[0] if rest and rest[0] not in ("", "*", "-") else None
    return ":".join(base), version


def _resolve_identifier(item):
    """Map an item's purl or cpe to (product, version, identifier); product None if unknown."""
    if item.get("purl"):
        ident = str(item["purl"]).strip()
        base, version = _purl_base(ident)
        return _identifier_index("purl").get(base), version, ident
    if item.get("cpe"):
        ident = str(item["cpe"]).strip()
        base, version = _cpe_base(ident)
        return _identifier_index("cpe").get(base) if base else None, version, ident
    return None, None, None


# --- checks ------------------------------------------------------------------

def _check_one(product, version, warn_days, ref=None):
    ref = ref or _today()
    try:
        doc = _resolve_product(product)
    except NotFound:
        return dict(_not_found(product), product=product, version=version, status="unknown")

    releases = doc.get("releases") or []
    rel = _match_cycle(releases, version)
    maintained = _maintained_at(releases, ref)
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

    eol = _parse_date(rel.get("eolFrom"))
    days_left = (eol - ref).days if eol else None
    if _is_eol_at(rel, ref):
        status = "eol"
    elif _is_eoas_at(rel, ref):
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
        is_newest_cycle=bool(releases) and releases[0] is rel,
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


def _check_item(item, warn_days, ref):
    """Check one {product, version} / {purl} / {cpe} item; never raises."""
    item = item if isinstance(item, dict) else {}
    product = str(item.get("product") or "").strip()
    version = str(item.get("version") or "").strip()
    try:
        ident_product, ident_version, ident = _resolve_identifier(item)
        if ident:
            version = version or (ident_version or "")
            if not ident_product:
                return {"identifier": ident, "version": version, "status": "unknown",
                        "error": f"No endoflife.date product is mapped to '{ident}'",
                        "hint": "Retry with product+version (eol_search finds the product)."}
            product = ident_product
        if not product or not version:
            return {"product": product, "version": version, "status": "unknown",
                    "error": "Need product and version (or a purl/cpe that carries a version)"}
        out = _check_one(product, version, warn_days, ref)
        if ident:
            out["identifier"] = ident
        return out
    except ApiError as e:
        return {"product": product, "version": version, "status": "unknown", "error": str(e)}


def _int_arg(args, key, default, lo, hi):
    try:
        value = int(args.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def _summary(results):
    summary = {s: sum(1 for r in results if r.get("status") == s)
               for s in ("supported", "security-only", "eol", "unknown")}
    summary["eol_soon"] = sum(1 for r in results if r.get("eol_soon"))
    return summary


# --- tools -------------------------------------------------------------------

def eol_search(args: dict, **kwargs) -> str:
    listing = (args.get("list") or "").strip().lower()
    if listing:
        if listing not in ("categories", "tags"):
            return json.dumps({"error": "list must be 'categories' or 'tags'"})
        try:
            names = sorted(e.get("name") for e in _get("/" + listing) or [] if e.get("name"))
        except ApiError as e:
            return json.dumps({"error": str(e)})
        return json.dumps({"list": listing, "count": len(names), "names": names})

    query = (args.get("query") or "").strip()
    if not query:
        return json.dumps({"error": "Provide query, or list: 'categories' | 'tags'"})
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
    identifiers = {}
    for ident in doc.get("identifiers") or []:
        bucket = identifiers.setdefault(ident.get("type") or "other", [])
        if len(bucket) < 10:
            bucket.append(ident.get("id"))
    return json.dumps({
        "product": doc.get("name"),
        "label": doc.get("label"),
        "category": doc.get("category"),
        "tags": doc.get("tags") or [],
        "version_command": doc.get("versionCommand"),
        "identifiers": identifiers,
        "source": f"{SITE_BASE}/{doc.get('name')}",
        "total_cycles": len(releases),
        "maintained_cycles": sum(1 for r in releases if r.get("isMaintained")),
        "releases": [_release_summary(r) for r in shown[:max_releases]],
        "truncated": len(shown) > max_releases,
    })


def eol_check(args: dict, **kwargs) -> str:
    warn_days = _int_arg(args, "warn_days", 180, 0, 3650)
    try:
        ref = _parse_ref_date(args.get("date"))
    except ValueError as e:
        return json.dumps({"error": str(e)})
    items = args.get("items")
    if not items and (args.get("product") or args.get("purl") or args.get("cpe")):
        items = [{k: args.get(k) for k in ("product", "version", "purl", "cpe") if args.get(k)}]
    if not items or not isinstance(items, list):
        return json.dumps({"error": "Provide product+version, purl, cpe, or items: [...]"})
    if len(items) > MAX_ITEMS:
        return json.dumps({"error": f"Too many items ({len(items)}); the limit is {MAX_ITEMS}"})

    results = [_check_item(item, warn_days, ref) for item in items]
    return json.dumps({"checked_on": ref.isoformat(), "summary": _summary(results), "results": results})


# --- geol stack files (.geol.yaml) ---------------------------------------------

GEOL_VERSION = "2"
GEOL_WARN_DAYS = 30  # geol check reports WARN under 30 days before EOL


def _load_yaml(text):
    try:
        from hermes_yaml import safe_load
    except ImportError:  # outside Hermes (unit tests): PyYAML if present
        from yaml import safe_load
    return safe_load(text)


def _active_lts(releases, ref):
    """Active LTS cycles at `ref`, newest first: what geol's lts_strategy checks against."""
    return [r for r in releases if r.get("isLts") and not _is_eol_at(r, ref)
            and (_parse_date(r.get("releaseDate")) or ref) <= ref]


def _stack_item(item, ref, warnings, violations):
    name = str(item.get("name") or item.get("id_eol") or "?")
    version_raw = item.get("version")
    version = "" if version_raw is None else str(version_raw)
    id_eol = str(item.get("id_eol") or "").strip()
    if isinstance(version_raw, float):
        warnings.append(f"{name}: version {version_raw!r} is a YAML number; quote it "
                        f"(an unquoted 3.10 is read as 3.1)")
    if not version or not id_eol:
        violations.append(f"{name}: version and id_eol are required")
        return {"name": name, "version": version, "id_eol": id_eol, "status": "unknown",
                "geol_status": "ERROR", "error": "version and id_eol are required"}

    if item.get("manual_eol"):
        eol = _parse_date(str(item["manual_eol"]))
        days = (eol - ref).days if eol else None
        res = {"name": name, "version": version, "id_eol": id_eol, "eol_date": str(item["manual_eol"]),
               "days_until_eol": days, "source": "manual_eol",
               "status": "eol" if days is not None and days < 0 else "supported"}
    else:
        res = dict(_check_one(id_eol, version, GEOL_WARN_DAYS, ref), name=name, id_eol=id_eol)
        if res.get("cycle") and str(res["cycle"]) != version:
            warnings.append(f"{name}: geol expects the release cycle as version "
                            f"(version: \"{res['cycle']}\"), '{version}' makes geol check fail")

    days = res.get("days_until_eol")
    if res.get("status") == "unknown":
        res["geol_status"] = "ERROR"
        violations.append(f"{name} {version}: {res.get('error', 'not found on endoflife.date')}")
    elif res.get("status") == "eol" or (days is not None and days < 0):
        res["geol_status"] = "EOL"
        violations.append(f"{name} {version} is end-of-life since {res.get('eol_date')}")
    elif days is not None and days < GEOL_WARN_DAYS:
        res["geol_status"] = "WARN"
        warnings.append(f"{name} {version} reaches end-of-life in {days} days")
    else:
        res["geol_status"] = "OK"

    strategy = item.get("lts_strategy")
    if strategy and res.get("status") != "unknown" and not item.get("manual_eol"):
        releases = (_resolve_product(id_eol).get("releases") or [])
        active = _active_lts(releases, ref)
        names = [r.get("name") for r in active]
        res["lts_strategy"] = strategy
        if not active:
            violations.append(f"{name}: lts_strategy '{strategy}' set but {id_eol} has no active LTS")
        elif strategy == "any" and res.get("cycle") not in names:
            violations.append(f"{name} {version} is not an active LTS (active LTS: {', '.join(names)})")
        elif strategy == "latest" and res.get("cycle") != names[0]:
            grace = int(item.get("lts_grace_days") or 0)
            released = _parse_date(active[0].get("releaseDate"))
            age = (ref - released).days if released else None
            if grace and age is not None and age < grace:
                warnings.append(f"{name} {version}: newer LTS {names[0]} released {age}d ago "
                                f"(grace period {grace}d)")
            else:
                violations.append(f"{name} {version} is not the latest LTS (latest LTS: {names[0]})")
        elif strategy not in ("any", "latest"):
            violations.append(f"{name}: lts_strategy must be 'any' or 'latest', got '{strategy}'")

    if item.get("always-latest") and res.get("status") != "unknown" and not item.get("manual_eol"):
        if not res.get("is_newest_cycle") or res.get("patch_behind"):
            violations.append(f"{name} {version} should be on the latest version")
    return res


def eol_stack_check(args: dict, **kwargs) -> str:
    content = args.get("content") or ""
    if not content.strip():
        return json.dumps({"error": "Pass the text of the .geol.yaml file as content"})
    try:
        ref = _parse_ref_date(args.get("date"))
    except ValueError as e:
        return json.dumps({"error": str(e)})
    try:
        doc = _load_yaml(content)
    except Exception as e:  # YAML errors, or no YAML parser available
        return json.dumps({"error": f"Could not parse the stack file: {e}"})
    if not isinstance(doc, dict) or not isinstance(doc.get("stack"), list):
        return json.dumps({"error": "Not a geol stack file: expected a mapping with a 'stack' list"})
    if len(doc["stack"]) > MAX_ITEMS:
        return json.dumps({"error": f"Too many stack items ({len(doc['stack'])}); the limit is {MAX_ITEMS}"})

    warnings, violations, skipped, results = [], [], [], []
    if str(doc.get("geolVersion") or "") != GEOL_VERSION:
        warnings.append(f"geolVersion is {doc.get('geolVersion')!r}; this checker follows geolVersion \"2\"")
    seen = set()
    for item in doc["stack"]:
        if not isinstance(item, dict):
            violations.append(f"Stack entry {item!r} is not a mapping")
            continue
        name = str(item.get("name") or "")
        if name in seen:
            violations.append(f"Duplicate name '{name}': names must be unique")
        seen.add(name)
        if item.get("skip"):
            skipped.append({"name": name, "version": str(item.get("version") or ""),
                            "id_eol": item.get("id_eol")})
            continue
        try:
            results.append(_stack_item(item, ref, warnings, violations))
        except ApiError as e:
            violations.append(f"{name}: {e}")

    order = {"ERROR": 0, "EOL": 1, "WARN": 2, "OK": 3}
    results.sort(key=lambda r: (order.get(r.get("geol_status"), 9),
                                r.get("days_until_eol") if r.get("days_until_eol") is not None else 10**9))
    summary = {s: sum(1 for r in results if r.get("geol_status") == s) for s in order}
    summary["skipped"] = len(skipped)
    return json.dumps({
        "app_name": doc.get("app_name"),
        "app_id": doc.get("app_id"),
        "checked_on": ref.isoformat(),
        "passed": not violations,
        "summary": summary,
        "violations": violations,
        "warnings": warnings,
        "results": results,
        "skipped": skipped,
    })


def _q(value):
    """A double-quoted YAML scalar (JSON strings are valid YAML)."""
    return json.dumps(str(value), ensure_ascii=False)


def _slug(text):
    out = "".join(ch.lower() if ch.isalnum() else "-" for ch in text).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out or "app"


def eol_stack_file(args: dict, **kwargs) -> str:
    app_name = str(args.get("app_name") or "").strip()
    items = args.get("items")
    if not app_name or not items or not isinstance(items, list):
        return json.dumps({"error": "Provide app_name and items: [{name, product|purl|cpe, version}]"})
    if len(items) > MAX_ITEMS:
        return json.dumps({"error": f"Too many items ({len(items)}); the limit is {MAX_ITEMS}"})
    app_id = str(args.get("app_id") or "").strip() or _slug(app_name)

    entries, warnings, unresolved, names = [], [], [], set()
    for item in items:
        item = item if isinstance(item, dict) else {}
        version = str(item.get("version") or "").strip()
        product = str(item.get("product") or "").strip()
        try:
            ident_product, ident_version, ident = _resolve_identifier(item)
            if ident:
                product = ident_product or product
                version = version or (ident_version or "")
            doc = _resolve_product(product) if product else None
        except NotFound:
            doc = None
        except ApiError as e:
            return json.dumps({"error": str(e)})

        name = str(item.get("name") or (doc or {}).get("label") or product or ident or "?").strip()
        if name in names:
            warnings.append(f"Duplicate name '{name}': geol needs unique names, add a suffix (e.g. -prod)")
        names.add(name)
        if not version:
            warnings.append(f"{name}: no version given")

        entry = {"name": name, "version": version, "comment": None}
        if doc is None:
            entry["id_eol"] = product or _slug(name)
            entry["skip"] = True
            entry["comment"] = "not found on endoflife.date: kept for inventory, skipped by checks"
            unresolved.append({"name": name, "product": product or None, "identifier": ident})
        else:
            entry["id_eol"] = doc.get("name")
            rel = _match_cycle(doc.get("releases") or [], version) if version else None
            if version and rel is None:
                warnings.append(f"{name}: version '{version}' matches no {doc.get('label')} release cycle")
            elif rel is not None and str(rel.get("name")) != version:
                # geol looks up /releases/<version>, so it needs the cycle ("20"), not "20.10.0".
                entry["comment"] = f"in use: {version}"
                entry["version"] = str(rel.get("name"))
            if item.get("skip"):
                entry["skip"] = True
        if item.get("lts_strategy") in ("any", "latest"):
            entry["lts_strategy"] = item["lts_strategy"]
            if item["lts_strategy"] == "latest" and item.get("lts_grace_days"):
                entry["lts_grace_days"] = _int_arg(item, "lts_grace_days", 0, 0, 3650)
        if item.get("always_latest") or item.get("always-latest"):
            entry["always-latest"] = True
        entries.append(entry)

    lines = [
        f"geolVersion: {_q(GEOL_VERSION)}",
        "# cuelang file : https://github.com/opt-nc/geol/blob/main/geol_stack.cue",
        f"# Generated by hermes-eol-plugin on {_today().isoformat()}; check with: geol check --file .geol.yaml",
        f"app_name: {_q(app_name)}",
        f"app_id: {_q(app_id)}",
        "",
        "stack:",
    ]
    for e in entries:
        if e["comment"]:
            lines.append(f"  # {e['comment']}")
        lines.append(f"  - name: {_q(e['name'])}")
        lines.append(f"    version: {_q(e['version'])}")
        lines.append(f"    id_eol: {_q(e['id_eol'])}")
        for key in ("skip", "always-latest"):
            if e.get(key):
                lines.append(f"    {key}: true")
        if e.get("lts_strategy"):
            lines.append(f"    lts_strategy: {_q(e['lts_strategy'])}")
        if e.get("lts_grace_days"):
            lines.append(f"    lts_grace_days: {e['lts_grace_days']}")
        lines.append("")

    return json.dumps({
        "path": ".geol.yaml",
        "content": "\n".join(lines),
        "items": len(entries),
        "unresolved": unresolved,
        "warnings": warnings,
        "next_step": ("Show the content to the user, then save it with write_file at the project "
                      "root as .geol.yaml (ask before overwriting an existing one). Verify it with "
                      "eol_stack_check, or in CI with: geol check --strict --file .geol.yaml"),
    })
