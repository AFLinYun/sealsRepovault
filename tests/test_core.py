"""sealsrepo 核心功能测试。零依赖，python3 -m unittest tests/test_core.py"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sealsrepo import core
from sealsrepo.cli import main


class TestUrlAndId(unittest.TestCase):
    def test_canonicalize(self):
        self.assertEqual(
            core.canonicalize_url("https://github.com/Google/Guava/"),
            "https://github.com/google/guava",
        )
        self.assertEqual(
            core.canonicalize_url("http://github.com/a/b"),
            "https://github.com/a/b",
        )

    def test_invalid_url(self):
        with self.assertRaises(ValueError):
            core.canonicalize_url("https://example.com/foo/bar")
        with self.assertRaises(ValueError):
            core.canonicalize_url("https://github.com/onlyowner")

    def test_make_id(self):
        self.assertEqual(
            core.make_id("https://github.com/Owner/Repo"),
            "gh-owner-repo",
        )

    def test_url_roundtrip(self):
        rid = core.make_id("https://github.com/foo/bar")
        self.assertEqual(core.url_from_id(rid), "https://github.com/foo/bar")


class TestRecordRoundtrip(unittest.TestCase):
    def test_md_roundtrip(self):
        rec = core.new_record("https://github.com/a/b", desc="hello world")
        rec["grade"] = "B"
        rec["hit_directions"] = ["agent_capability"]
        rec["capability_summary"] = "do things"
        text = core.record_to_md(rec)
        parsed = core.parse_record_md(text)
        self.assertEqual(parsed["id"], rec["id"])
        self.assertEqual(parsed["url"], rec["url"])
        self.assertEqual(parsed["grade"], "B")
        self.assertEqual(parsed["desc"], "hello world")
        self.assertEqual(parsed["hit_directions"], ["agent_capability"])

    def test_yaml_escaping(self):
        rec = core.new_record("https://github.com/a/b", desc='say "hi": now')
        text = core.record_to_md(rec)
        parsed = core.parse_record_md(text)
        self.assertEqual(parsed["desc"], 'say "hi": now')


class TestValidation(unittest.TestCase):
    def test_valid_record_passes(self):
        rec = core.new_record("https://github.com/a/b", desc="d")
        self.assertEqual(core.validate_record(rec), [])

    def test_bad_status(self):
        rec = core.new_record("https://github.com/a/b", desc="d")
        rec["status"] = "nonsense"
        self.assertTrue(core.validate_record(rec))

    def test_bad_grade(self):
        rec = core.new_record("https://github.com/a/b", desc="d")
        rec["grade"] = "Z"
        self.assertTrue(core.validate_record(rec))

    def test_id_url_mismatch(self):
        rec = core.new_record("https://github.com/a/b", desc="d")
        rec["id"] = "gh-x-y"
        self.assertTrue(any("不一致" in e for e in core.validate_record(rec)))


class TestCliFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_flow(self):
        r = str(self.root)
        self.assertEqual(main(["init", "--root", r]), 0)
        self.assertTrue((self.root / "config.json").exists())
        self.assertTrue((self.root / "projects" / "index.md").exists())

        self.assertEqual(main(["add", "--root", r, "https://github.com/foo/bar", "--desc", "x"]), 0)
        rec = core.load_record(r, "gh-foo-bar")
        self.assertEqual(rec["status"], "candidate")

        # 重复添加命中同一记录
        self.assertEqual(main(["add", "--root", r, "https://github.com/Foo/Bar/"]), 0)
        recs = core.all_records(r)
        self.assertEqual(len(recs), 1)

        # 评级
        self.assertEqual(
            main(["grade", "--root", r, "gh-foo-bar", "--grade", "B",
                  "--summary", "s", "--direction", "agent_capability"]),
            0,
        )
        rec = core.load_record(r, "gh-foo-bar")
        self.assertEqual(rec["grade"], "B")
        self.assertEqual(rec["status"], "evaluated")

        # S/A/B 缺 summary 应失败
        self.assertNotEqual(
            main(["grade", "--root", r, "gh-foo-bar", "--grade", "A"]), 0
        )

        # 校验通过
        self.assertEqual(main(["validate", "--root", r]), 0)

    def test_trending_import(self):
        r = str(self.root)
        main(["init", "--root", r])
        data = {
            "date": "2026-08-08",
            "items": [
                {"url": "https://github.com/a/one", "desc": "one", "stars": 1, "today_stars": 2},
                {"url": "https://github.com/a/two", "desc": "two", "stars": 3, "today_stars": 4},
                {"url": "https://github.com/a/one", "desc": "dup"},  # 重复
            ],
        }
        jf = self.root / "trending.json"
        jf.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(main(["trending-import", "--root", r, "--json", str(jf)]), 0)
        recs = core.all_records(r)
        self.assertEqual(len(recs), 2)
        self.assertTrue(all(x["source"] == "trending" for x in recs))


if __name__ == "__main__":
    unittest.main()
