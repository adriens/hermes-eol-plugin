"""Offline tests for the eol_* handlers: the HTTP layer is replaced by fixtures."""

import json
import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
