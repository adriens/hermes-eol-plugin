"""Offline tests for the eol_* handlers: the HTTP layer is replaced by fixtures."""

import json
import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hints  # noqa: E402
import tools  # noqa: E402

try:
    tools._load_yaml("a: 1")
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False

PRODUCTS = [
    {"name": "python", "label": "Python", "aliases": [], "category": "lang", "tags": ["lang"]},
    {"name": "postgresql", "label": "PostgreSQL", "aliases": ["postgres", "pg"],
     "category": "database", "tags": ["database"]},
    {"name": "ubuntu", "label": "Ubuntu", "aliases": [], "category": "os", "tags": ["linux-distribution", "os"]},
]


def _rel(name, eol, is_eol, maintained, lts=False, eoas=None, is_eoas=False, latest=None):
    return {"name": name, "codename": None, "releaseDate": "2020-01-01", "isLts": lts,
            "isEoas": is_eoas, "eoasFrom": eoas, "isEol": is_eol, "eolFrom": eol,
            "isMaintained": maintained, "latest": {"name": latest or name + ".0", "date": "2026-01-01"}}


DOCS = {
    "/products": PRODUCTS,
    "/categories": [{"name": "os"}, {"name": "lang"}],
    "/tags": [{"name": "linux-distribution"}],
    "/identifiers/purl": [
        {"identifier": "pkg:docker/library/python", "product": {"name": "python"}},
        {"identifier": "pkg:oci/python?repository_url=cgr.dev/chainguard", "product": {"name": "python"}},
    ],
    "/identifiers/cpe": [
        {"identifier": "cpe:2.3:o:canonical:ubuntu_linux", "product": {"name": "ubuntu"}},
    ],
    "/products/python": {"name": "python", "label": "Python", "category": "lang",
                         "versionCommand": "python --version", "releases": [
                             _rel("3.14", "2030-10-31", False, True, latest="3.14.10"),
                             _rel("3.10", "2026-12-31", False, True, is_eoas=True, latest="3.10.19"),
                             _rel("3.9", "2025-10-31", True, False, is_eoas=True, latest="3.9.25"),
                         ]},
    "/products/postgresql": {"name": "postgresql", "label": "PostgreSQL", "category": "database",
                             "releases": [_rel("18", "2030-11-14", False, True, latest="18.1")]},
    "/products/ubuntu": {"name": "ubuntu", "label": "Ubuntu", "category": "os", "releases": [
        _rel("26.10", "2027-07-01", False, True, latest="26.10"),
        _rel("26.04", "2031-05-29", False, True, lts=True, latest="26.04.1"),
        _rel("22.04", "2027-06-01", False, True, lts=True, is_eoas=True, latest="22.04.5"),
    ]},
}


def fake_get(path):
    if path not in DOCS:
        raise tools.NotFound(path)
    return DOCS[path]


@mock.patch.object(tools, "_today", lambda: date(2026, 11, 13))
@mock.patch.object(tools, "_get", side_effect=fake_get)
class EolToolsTest(unittest.TestCase):

    def setUp(self):
        tools._cache.clear()

    def test_search_alias_ranks_exact_first(self, _):
        out = json.loads(tools.eol_search({"query": "postgres"}))
        self.assertEqual(out["results"][0]["product"], "postgresql")

    def test_search_by_category(self, _):
        out = json.loads(tools.eol_search({"query": "os"}))
        self.assertIn("ubuntu", [r["product"] for r in out["results"]])

    def test_product_resolves_alias(self, _):
        out = json.loads(tools.eol_product({"product": "pg"}))
        self.assertEqual(out["product"], "postgresql")

    def test_product_excludes_eol(self, _):
        out = json.loads(tools.eol_product({"product": "python", "include_eol": False}))
        self.assertEqual([r["cycle"] for r in out["releases"]], ["3.14", "3.10"])

    def test_check_eol_with_patch_behind(self, _):
        r = json.loads(tools.eol_check({"product": "python", "version": "3.9.7"}))["results"][0]
        self.assertEqual((r["cycle"], r["status"], r["patch_behind"]), ("3.9", "eol", True))
        self.assertEqual(r["upgrade_to"]["cycle"], "3.14")

    def test_check_security_only_and_soon(self, _):
        r = json.loads(tools.eol_check({"product": "python", "version": "v3.10.19"}))["results"][0]
        self.assertEqual(r["status"], "security-only")
        self.assertTrue(r["eol_soon"])
        self.assertFalse(r["patch_behind"])

    def test_check_lists_maintained_cycles(self, _):
        r = json.loads(tools.eol_check({"product": "python", "version": "3.9"}))["results"][0]
        self.assertEqual([c["cycle"] for c in r["maintained_cycles"]], ["3.14", "3.10"])
        self.assertFalse(r["has_lts_releases"])

    def test_check_lts_upgrades_to_lts(self, _):
        r = json.loads(tools.eol_check({"product": "ubuntu", "version": "22.04"}))["results"][0]
        self.assertEqual(r["upgrade_to"]["cycle"], "26.04")

    def test_check_does_not_confuse_prefixes(self, _):
        r = json.loads(tools.eol_check({"product": "python", "version": "3.1"}))["results"][0]
        self.assertEqual(r["status"], "unknown")

    def test_check_batch_summary(self, _):
        out = json.loads(tools.eol_check({"items": [
            {"product": "python", "version": "3.9"},
            {"product": "ubuntu", "version": "26.04"},
            {"product": "pyhton", "version": "3"},
        ]}))
        self.assertEqual(out["summary"]["eol"], 1)
        self.assertEqual(out["summary"]["supported"], 1)
        self.assertEqual(out["summary"]["unknown"], 1)
        self.assertIn("python", out["results"][2]["did_you_mean"])

    def test_check_requires_input(self, _):
        self.assertIn("error", json.loads(tools.eol_check({})))

    def test_api_error_is_reported_not_raised(self, get):
        get.side_effect = tools.ApiError("endoflife.date unreachable: timeout")
        out = json.loads(tools.eol_product({"product": "python"}))
        self.assertIn("unreachable", out["error"])

    def test_search_lists_categories(self, _):
        out = json.loads(tools.eol_search({"list": "categories"}))
        self.assertEqual(out["names"], ["lang", "os"])

    def test_check_at_reference_date(self, _):
        r = json.loads(tools.eol_check({"product": "python", "version": "3.10", "date": "2027-01-15"}))
        self.assertEqual(r["checked_on"], "2027-01-15")
        self.assertEqual(r["results"][0]["status"], "eol")
        self.assertEqual([c["cycle"] for c in r["results"][0]["maintained_cycles"]], ["3.14"])

    def test_check_rejects_bad_date(self, _):
        self.assertIn("error", json.loads(tools.eol_check({"product": "python", "version": "3.9",
                                                           "date": "next year"})))

    def test_check_by_purl_with_qualifiers(self, _):
        out = json.loads(tools.eol_check({"items": [
            {"purl": "pkg:docker/library/python@3.9.7"},
            {"purl": "pkg:oci/python@3.14?repository_url=cgr.dev/chainguard"},
            {"purl": "pkg:npm/left-pad@1.3.0"},
        ]}))
        self.assertEqual([r["status"] for r in out["results"]], ["eol", "supported", "unknown"])
        self.assertEqual(out["results"][0]["identifier"], "pkg:docker/library/python@3.9.7")

    def test_check_by_cpe(self, _):
        r = json.loads(tools.eol_check({"cpe": "cpe:2.3:o:canonical:ubuntu_linux:22.04:*:*:*:lts:*:*:*"}))
        self.assertEqual((r["results"][0]["product"], r["results"][0]["cycle"]), ("ubuntu", "22.04"))


@unittest.skipUnless(HAVE_YAML, "needs hermes_yaml or PyYAML (run with Hermes' Python)")
@mock.patch.object(tools, "_today", lambda: date(2026, 11, 13))
@mock.patch.object(tools, "_get", side_effect=fake_get)
class StackFileTest(unittest.TestCase):

    def setUp(self):
        tools._cache.clear()

    def test_generated_file_uses_cycles_and_skips_unknown(self, _):
        out = json.loads(tools.eol_stack_file({"app_name": "Demo API", "items": [
            {"product": "python", "version": "3.9.7"},
            {"product": "ubuntu", "version": "22.04", "lts_strategy": "latest", "lts_grace_days": 30},
            {"product": "my-lib", "version": "1.0"},
            {"purl": "pkg:pypi/gunicorn@21.2.0"},
        ]}))
        doc = tools._load_yaml(out["content"])
        self.assertEqual(doc["geolVersion"], "2")
        self.assertEqual(doc["app_id"], "demo-api")
        self.assertEqual(doc["stack"][0], {"name": "Python", "version": "3.9", "id_eol": "python"})
        self.assertEqual(doc["stack"][1]["lts_strategy"], "latest")
        self.assertEqual(doc["stack"][1]["lts_grace_days"], 30)
        self.assertTrue(doc["stack"][2]["skip"])
        self.assertEqual(out["unresolved"][0]["name"], "my-lib")
        self.assertEqual(doc["stack"][3], {"name": "gunicorn", "version": "21.2.0",
                                           "id_eol": "gunicorn", "skip": True})

    def test_round_trip_through_stack_check(self, _):
        out = json.loads(tools.eol_stack_file({"app_name": "x", "items": [
            {"product": "python", "version": "3.9.7"},
            {"product": "ubuntu", "version": "26.04", "lts_strategy": "any"},
        ]}))
        res = json.loads(tools.eol_stack_check({"content": out["content"]}))
        self.assertFalse(res["passed"])
        self.assertEqual(res["summary"]["EOL"], 1)
        self.assertEqual(res["summary"]["OK"], 1)
        self.assertEqual(res["warnings"], [])

    def test_lts_latest_with_grace_period(self, _):
        stack = """geolVersion: "2"
stack:
  - name: ubuntu
    version: "22.04"
    id_eol: ubuntu
    lts_strategy: latest
    lts_grace_days: 99999
"""
        res = json.loads(tools.eol_stack_check({"content": stack}))
        self.assertTrue(res["passed"])
        self.assertIn("grace period", res["warnings"][0])
        res = json.loads(tools.eol_stack_check({"content": stack.replace("99999", "0")}))
        self.assertIn("not the latest LTS", res["violations"][0])

    def test_skip_manual_eol_and_warnings(self, _):
        stack = """geolVersion: "2"
stack:
  - {name: legacy, version: "1", id_eol: nope, skip: true}
  - {name: inhouse, version: "2", id_eol: inhouse, manual_eol: "2026-12-01"}
  - {name: py, version: 3.10, id_eol: python}
  - {name: py, version: "3.14.1", id_eol: python, always-latest: true}
"""
        res = json.loads(tools.eol_stack_check({"content": stack}))
        self.assertEqual(res["skipped"][0]["name"], "legacy")
        by_name = {r["name"]: r for r in res["results"]}
        self.assertEqual(by_name["inhouse"]["geol_status"], "WARN")
        joined = " ".join(res["warnings"] + res["violations"])
        self.assertIn("YAML number", joined)
        self.assertIn("Duplicate name", joined)
        self.assertIn("should be on the latest version", joined)

    def test_rejects_non_stack_yaml(self, _):
        self.assertIn("error", json.loads(tools.eol_stack_check({"content": "foo: bar"})))


class HintTest(unittest.TestCase):

    def test_matches_version_questions(self):
        for msg in ("Is Python 3.9 still supported?",
                    "@ghsa:GHSA-q238-5cxm-5c9h are we affected?",
                    "Check our Dockerfile and docker-compose.yml",
                    "Which Node.js LTS should we upgrade to?",
                    "write a .geol.yaml for this repo",
                    "CVE-2026-15830 impact on our stack"):
            self.assertTrue(hints.wants_hint(msg), msg)

    def test_ignores_unrelated_messages(self):
        for msg in ("", "Summarize this meeting", "What's the weather in Noumea?",
                    "Rename the variable foo to bar"):
            self.assertFalse(hints.wants_hint(msg), msg)

    def test_hook_respects_setting_and_never_raises(self):
        ctx = mock.Mock()
        ctx.get_config.return_value = True
        hook = hints.make_hook(ctx)
        self.assertEqual(hook(user_message="Is Ubuntu 22.04 EOL?")["context"], hints.HINT)
        self.assertIsNone(hook(user_message="hello"))
        ctx.get_config.return_value = False
        self.assertIsNone(hook(user_message="Is Ubuntu 22.04 EOL?"))
        ctx.get_config.side_effect = RuntimeError("boom")
        self.assertIsNotNone(hook(user_message="Is Ubuntu 22.04 EOL?"))
        self.assertIsNone(hook(user_message=None))


if __name__ == "__main__":
    unittest.main()
