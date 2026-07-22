"""Annotation-orphan hard-fail + annotation loading."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1]
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from store import serialization  # noqa: E402
from store.annotations import (  # noqa: E402
    AnnotationOrphanError,
    assert_no_orphans,
    find_orphans,
    load_annotations,
)


class OrphanHardFailTests(unittest.TestCase):
    def test_all_matched_passes(self):
        assert_no_orphans(["gh-1", "gh-2"], ["gh-1", "gh-2", "gh-3"])

    def test_orphan_raises(self):
        with self.assertRaises(AnnotationOrphanError) as ctx:
            assert_no_orphans(["gh-1", "gh-missing"], ["gh-1", "gh-2"])
        self.assertEqual(ctx.exception.orphans, ["gh-missing"])

    def test_find_orphans_lists_them(self):
        self.assertEqual(find_orphans(["a", "b", "c"], ["b"]), ["a", "c"])


class LoadAnnotationsTests(unittest.TestCase):
    def test_load_keys_by_stem(self):
        with tempfile.TemporaryDirectory() as td:
            ann_dir = Path(td)
            (ann_dir / "gh-1234567.yaml").write_text(
                serialization.dumps_yaml(
                    {"schema_version": 1, "key": "gh-1234567",
                     "facts": {"workplace": "hybrid"}}))
            loaded = load_annotations(ann_dir)
            self.assertIn("gh-1234567", loaded)
            self.assertEqual(loaded["gh-1234567"]["facts"]["workplace"], "hybrid")

    def test_orphan_check_over_loaded_annotations(self):
        with tempfile.TemporaryDirectory() as td:
            ann_dir = Path(td)
            (ann_dir / "gh-1.yaml").write_text(
                serialization.dumps_yaml({"schema_version": 1, "key": "gh-1"}))
            (ann_dir / "gh-orphan.yaml").write_text(
                serialization.dumps_yaml({"schema_version": 1, "key": "gh-orphan"}))
            keys = list(load_annotations(ann_dir))
            with self.assertRaises(AnnotationOrphanError):
                assert_no_orphans(keys, ["gh-1"])  # gh-orphan matches no entity


if __name__ == "__main__":
    unittest.main()
