#!/usr/bin/env python3
"""Regression tests for mirror_skills.py. Standard library only: python test_mirror_skills.py

Every test works inside a temporary directory and points the destination table at
it, so nothing here can touch a real ~/.codex, ~/.gemini or ~/.qwen.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import mirror_skills as ms

SKILL_MD = """---
name: demo
description: A demo skill.
allowed-tools: Read, Grep
paths:
  - "**/*.py"
license: MIT
---

# Demo

Body text.
"""


def write_skill(canon: Path, name: str, text: str = SKILL_MD, extra: dict | None = None) -> Path:
    root = canon / name
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(text, encoding="utf-8")
    for rel, content in (extra or {}).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


class MirrorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mirror-test-"))
        self.canon = self.tmp / "canon"
        self.canon.mkdir()
        self.dest = self.tmp / "dest"
        self.saved = {k: v["root"] for k, v in ms.DESTINATIONS.items()}
        for spec in ms.DESTINATIONS.values():
            spec["root"] = lambda: self.dest

    def tearDown(self):
        for key, root in self.saved.items():
            ms.DESTINATIONS[key]["root"] = root
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- canon discovery ---------------------------------------------------------

    def test_only_directories_with_skill_md_count(self):
        write_skill(self.canon, "demo")
        (self.canon / "not-a-skill").mkdir()
        (self.canon / "loose.md").write_text("x", encoding="utf-8")
        self.assertEqual(list(ms.canon_skills(self.canon)), ["demo"])

    def test_unknown_skill_name_is_an_error(self):
        write_skill(self.canon, "demo")
        with self.assertRaises(ms.MirrorError):
            ms.select(self.canon, "nope")

    # --- frontmatter -------------------------------------------------------------

    def test_unknown_keys_are_dropped_and_nested_lines_travel_with_them(self):
        text, dropped = ms.sanitize_frontmatter(
            "demo", SKILL_MD, {"name", "description", "license"})
        self.assertEqual(dropped, ["allowed-tools", "paths"])
        self.assertNotIn("allowed-tools", text)
        self.assertNotIn('"**/*.py"', text)          # the list item under `paths` went too
        self.assertIn("license: MIT", text)
        self.assertIn("# Demo", text)

    def test_body_containing_a_dashed_line_is_not_truncated(self):
        text, _ = ms.sanitize_frontmatter(
            "demo", SKILL_MD.replace("Body text.", "Body\n---\nmore"), {"name", "description"})
        self.assertIn("more", text)

    def test_missing_required_key_after_filtering_is_an_error(self):
        with self.assertRaises(ms.MirrorError):
            ms.sanitize_frontmatter("demo", SKILL_MD, {"name"})       # description dropped

    def test_missing_frontmatter_is_an_error(self):
        with self.assertRaises(ms.MirrorError):
            ms.sanitize_frontmatter("demo", "# no frontmatter\n", {"name", "description"})

    # --- copy --------------------------------------------------------------------

    def test_copy_takes_the_whole_directory_and_marks_it(self):
        write_skill(self.canon, "demo", extra={"knowledge/notes.md": "detail"})
        changes, _ = ms.install("codex", self.canon, ms.select(self.canon, None), check=False)
        self.assertEqual(changes, 1)
        self.assertEqual((self.dest / "demo" / "knowledge" / "notes.md").read_text(encoding="utf-8"),
                         "detail")
        self.assertTrue((self.dest / "demo" / ms.MARKER).is_file())
        head = (self.dest / "demo" / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("paths:", head.split("\n---", 1)[0])

    def test_copy_is_idempotent(self):
        write_skill(self.canon, "demo")
        picked = ms.select(self.canon, None)
        ms.install("codex", self.canon, picked, check=False)
        first = (self.dest / "demo" / "SKILL.md").read_text(encoding="utf-8")
        ms.install("codex", self.canon, picked, check=False)
        self.assertEqual(first, (self.dest / "demo" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual(ms.install("codex", self.canon, picked, check=True)[0], 0)

    def test_binary_assets_survive_byte_for_byte(self):
        root = write_skill(self.canon, "demo")
        blob = bytes(range(256))
        (root / "logo.png").write_bytes(blob)
        ms.install("codex", self.canon, ms.select(self.canon, None), check=False)
        self.assertEqual((self.dest / "demo" / "logo.png").read_bytes(), blob)

    # --- pruning boundary --------------------------------------------------------

    def test_prune_removes_only_what_we_made(self):
        write_skill(self.canon, "demo")
        write_skill(self.canon, "gone")
        ms.install("codex", self.canon, ms.select(self.canon, None), check=False)
        hand_written = self.dest / "user-own"
        hand_written.mkdir()
        (hand_written / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
        shutil.rmtree(self.canon / "gone")

        _, notes = ms.install("codex", self.canon, ms.select(self.canon, None), check=False)
        self.assertFalse((self.dest / "gone").exists())
        self.assertTrue((hand_written / "SKILL.md").is_file())
        self.assertTrue(any("pruned gone" in n for n in notes))

    def test_an_unmarked_collision_stops_instead_of_overwriting(self):
        write_skill(self.canon, "demo")
        (self.dest / "demo").mkdir(parents=True)
        (self.dest / "demo" / "SKILL.md").write_text("someone else's work", encoding="utf-8")
        with self.assertRaises(ms.MirrorError):
            ms.install("codex", self.canon, ms.select(self.canon, None), check=False)
        self.assertEqual((self.dest / "demo" / "SKILL.md").read_text(encoding="utf-8"),
                         "someone else's work")

    # --- check mode --------------------------------------------------------------

    def test_check_reports_without_writing(self):
        write_skill(self.canon, "demo")
        changes, notes = ms.install("codex", self.canon, ms.select(self.canon, None), check=True)
        self.assertEqual(changes, 1)
        self.assertTrue(any("missing" in n for n in notes))
        self.assertFalse(self.dest.exists())

    def test_check_sees_a_stale_mirror(self):
        write_skill(self.canon, "demo")
        write_skill(self.canon, "gone")
        ms.install("codex", self.canon, ms.select(self.canon, None), check=False)
        shutil.rmtree(self.canon / "gone")
        changes, notes = ms.install("codex", self.canon, ms.select(self.canon, None), check=True)
        self.assertEqual(changes, 1)
        self.assertTrue(any("stale" in n for n in notes))
        self.assertTrue((self.dest / "gone").is_dir())      # check mode wrote nothing

    # --- link --------------------------------------------------------------------

    def test_link_points_at_the_canon_and_is_idempotent(self):
        write_skill(self.canon, "demo")
        picked = ms.select(self.canon, None)
        try:
            ms.install("gemini", self.canon, picked, check=False)
        except OSError as exc:                              # unprivileged Windows, no junction
            self.skipTest(f"cannot create links here: {exc}")
        link = self.dest / "demo"
        self.assertTrue(ms.links_to_canon(link, self.canon))
        self.assertEqual((link / "SKILL.md").read_text(encoding="utf-8"), SKILL_MD)
        self.assertEqual(ms.install("gemini", self.canon, picked, check=True)[0], 0)

    def test_removing_a_link_leaves_the_canon_intact(self):
        write_skill(self.canon, "demo")
        picked = ms.select(self.canon, None)
        try:
            ms.install("gemini", self.canon, picked, check=False)
        except OSError as exc:
            self.skipTest(f"cannot create links here: {exc}")
        shutil.rmtree(self.canon / "demo")
        write_skill(self.canon, "other")
        ms.install("gemini", self.canon, ms.select(self.canon, None), check=False)
        self.assertFalse((self.dest / "demo").exists())
        self.assertTrue((self.canon / "other" / "SKILL.md").is_file())


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False, verbosity=2).result.wasSuccessful() else 1)
