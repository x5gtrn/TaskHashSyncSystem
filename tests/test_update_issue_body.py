#!/usr/bin/env python3
"""
Tests for update_issue_body.py — safe atomic operations on GitHub Issue body.

These tests verify all op_* functions operate on lists of strings only
(no GitHub API calls).  fetch_body / push_body are excluded from unit tests
as they require network access.

Run:  python3 -m unittest tests.test_update_issue_body  (from TaskHashSyncSystem/)
  or: python3 -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from update_issue_body import (
    find_line_index,
    detect_indent,
    op_add_task,
    op_add_child,
    op_remove_task,
    op_check_task,
    op_uncheck_task,
)


# ─── Sample Issue body fixtures ───────────────────────────────────────────────

ISSUE_2_BODY = """\
- [x] エラチョイに返信 (35efa56a)
- [x] 【TCS Japan】　弊社ポジションのご案内についてカジュアル面談のご提案 (62d90568)
- [x] Maresuke Yamada に返信 (70a0e1f4)
- [ ] Rayzel からの斡旋に対応 (4375b980)
    - [ ] 送られてきたJDを確認する (3d8c2904)
- [ ] Joana Inamori 13日の17時からTeamsにて (c329bc12)""".splitlines()

ISSUE_3_BODY = """\
- [x] フィードバックページ作成 (51a9ee37) ✅ 2026-05-06
- [ ] バグフィックス (251383dc)
    - [ ] Before & After の文字は不要 (7f1603d8)""".splitlines()


# ─── find_line_index ──────────────────────────────────────────────────────────

class TestFindLineIndex(unittest.TestCase):

    def test_finds_top_level_line(self):
        idx = find_line_index(ISSUE_2_BODY, "35efa56a")
        self.assertEqual(idx, 0)

    def test_finds_nested_line(self):
        idx = find_line_index(ISSUE_2_BODY, "3d8c2904")
        self.assertEqual(idx, 4)

    def test_returns_none_when_not_found(self):
        idx = find_line_index(ISSUE_2_BODY, "00000000")
        self.assertIsNone(idx)

    def test_finds_line_in_issue_3(self):
        idx = find_line_index(ISSUE_3_BODY, "7f1603d8")
        self.assertEqual(idx, 2)

    def test_empty_lines(self):
        self.assertIsNone(find_line_index([], "deadbeef"))


# ─── detect_indent ────────────────────────────────────────────────────────────

class TestDetectIndent(unittest.TestCase):

    def test_root_level_parent_gives_4_space_child_indent(self):
        # Parent at column 0 → child indent is "    " (4 spaces)
        indent = detect_indent(ISSUE_2_BODY, "4375b980")
        self.assertEqual(indent, "    ")

    def test_nested_parent_gives_8_space_child_indent(self):
        # Parent "3d8c2904" is already at 4-space indent → child should be 8
        indent = detect_indent(ISSUE_2_BODY, "3d8c2904")
        self.assertEqual(indent, "        ")

    def test_hash_not_found_defaults_to_4(self):
        indent = detect_indent(ISSUE_2_BODY, "00000000")
        self.assertEqual(indent, "    ")


# ─── op_add_task ──────────────────────────────────────────────────────────────

class TestOpAddTask(unittest.TestCase):

    def test_appends_unchecked_task(self):
        lines = ["- [ ] Existing task (aaaaaaaa)"]
        result = op_add_task(lines, "New task (bbbbbbbb)")
        self.assertEqual(result[-1], "- [ ] New task (bbbbbbbb)")

    def test_appended_to_end(self):
        lines = ["- [ ] First (11111111)", "- [ ] Second (22222222)"]
        result = op_add_task(lines, "Third (33333333)")
        self.assertEqual(len(result), 3)
        self.assertTrue(result[-1].endswith("Third (33333333)"))

    def test_empty_body(self):
        result = op_add_task([], "Only task (aaaaaaaa)")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], "- [ ] Only task (aaaaaaaa)")


# ─── op_add_child ─────────────────────────────────────────────────────────────

class TestOpAddChild(unittest.TestCase):

    def _body(self):
        return [
            "- [ ] Parent task (aaaaaaaa)",
            "    - [ ] Existing child (bbbbbbbb)",
            "- [ ] Sibling task (cccccccc)",
        ]

    def test_inserts_child_after_existing_children(self):
        lines = self._body()
        result = op_add_child(lines, "Parent task (aaaaaaaa)", "New child (dddddddd)")
        # New child should be at index 2 (after existing child, before sibling)
        self.assertEqual(result[2], "    - [ ] New child (dddddddd)")
        # Sibling must not be displaced into wrong position
        self.assertIn("- [ ] Sibling task (cccccccc)", result)

    def test_first_child_inserted_right_after_parent(self):
        lines = [
            "- [ ] Solo parent (aaaaaaaa)",
            "- [ ] Unrelated (eeeeeeee)",
        ]
        result = op_add_child(lines, "Solo parent (aaaaaaaa)", "First child (ffffffff)")
        self.assertEqual(result[1], "    - [ ] First child (ffffffff)")

    def test_child_uses_correct_indent(self):
        lines = [
            "- [ ] Root (11111111)",
            "    - [ ] Child (22222222)",
        ]
        result = op_add_child(lines, "Child (22222222)", "Grandchild (33333333)")
        # Grandchild should be 8-space indent
        self.assertTrue(result[2].startswith("        "))

    def test_parent_not_found_exits(self):
        lines = ["- [ ] Task (aaaaaaaa)"]
        with self.assertRaises(SystemExit):
            op_add_child(lines, "Nonexistent (00000000)", "Child (bbbbbbbb)")


# ─── op_remove_task ───────────────────────────────────────────────────────────

class TestOpRemoveTask(unittest.TestCase):

    def test_removes_top_level_task(self):
        lines = list(ISSUE_2_BODY)
        original_len = len(lines)
        result = op_remove_task(lines, "c329bc12")
        self.assertEqual(len(result), original_len - 1)
        # No line should contain this hash
        self.assertFalse(any("c329bc12" in l for l in result))

    def test_removes_nested_task(self):
        lines = list(ISSUE_2_BODY)
        result = op_remove_task(lines, "3d8c2904")
        self.assertFalse(any("3d8c2904" in l for l in result))

    def test_hash_not_found_exits(self):
        lines = ["- [ ] Task (aaaaaaaa)"]
        with self.assertRaises(SystemExit):
            op_remove_task(lines, "00000000")

    def test_other_lines_untouched(self):
        lines = list(ISSUE_2_BODY)
        result = op_remove_task(lines, "c329bc12")
        # First line should still be present
        self.assertTrue(any("35efa56a" in l for l in result))


# ─── op_check_task ────────────────────────────────────────────────────────────

class TestOpCheckTask(unittest.TestCase):

    def test_marks_unchecked_as_checked(self):
        lines = ["- [ ] Some task (aaaaaaaa)"]
        result = op_check_task(lines, "aaaaaaaa")
        self.assertIn("[x]", result[0])
        self.assertNotIn("[ ]", result[0])

    def test_already_checked_is_noop(self):
        lines = ["- [x] Already done (bbbbbbbb)"]
        result = op_check_task(lines, "bbbbbbbb")
        # Line unchanged
        self.assertEqual(result[0], "- [x] Already done (bbbbbbbb)")

    def test_preserves_other_lines(self):
        lines = [
            "- [ ] Task A (aaaaaaaa)",
            "- [ ] Task B (bbbbbbbb)",
        ]
        result = op_check_task(lines, "aaaaaaaa")
        self.assertIn("[x]", result[0])
        self.assertIn("[ ]", result[1])  # Task B untouched

    def test_hash_not_found_exits(self):
        lines = ["- [ ] Task (aaaaaaaa)"]
        with self.assertRaises(SystemExit):
            op_check_task(lines, "00000000")

    def test_nested_task_checked(self):
        lines = list(ISSUE_2_BODY)
        result = op_check_task(lines, "3d8c2904")
        child_lines = [l for l in result if "3d8c2904" in l]
        self.assertEqual(len(child_lines), 1)
        self.assertIn("[x]", child_lines[0])


# ─── op_uncheck_task ──────────────────────────────────────────────────────────

class TestOpUncheckTask(unittest.TestCase):

    def test_marks_checked_as_unchecked(self):
        lines = ["- [x] Done task (aaaaaaaa)"]
        result = op_uncheck_task(lines, "aaaaaaaa")
        self.assertIn("[ ]", result[0])
        self.assertNotIn("[x]", result[0])

    def test_already_unchecked_is_noop(self):
        lines = ["- [ ] Not done (bbbbbbbb)"]
        result = op_uncheck_task(lines, "bbbbbbbb")
        self.assertEqual(result[0], "- [ ] Not done (bbbbbbbb)")

    def test_preserves_other_lines(self):
        lines = [
            "- [x] Task A (aaaaaaaa)",
            "- [x] Task B (bbbbbbbb)",
        ]
        result = op_uncheck_task(lines, "aaaaaaaa")
        self.assertIn("[ ]", result[0])
        self.assertIn("[x]", result[1])  # Task B untouched

    def test_hash_not_found_exits(self):
        lines = ["- [x] Task (aaaaaaaa)"]
        with self.assertRaises(SystemExit):
            op_uncheck_task(lines, "00000000")


# ─── round-trip safety ────────────────────────────────────────────────────────

class TestRoundTrip(unittest.TestCase):
    """Verify that add → remove and check → uncheck are true inverses."""

    def test_add_then_remove_is_noop(self):
        original = ["- [ ] Existing (aaaaaaaa)"]
        after_add = op_add_task(list(original), "Temp task (bbbbbbbb)")
        after_remove = op_remove_task(after_add, "bbbbbbbb")
        self.assertEqual(after_remove, original)

    def test_check_then_uncheck_restores_line(self):
        lines = ["- [ ] Task (aaaaaaaa)"]
        after_check = op_check_task(list(lines), "aaaaaaaa")
        after_uncheck = op_uncheck_task(list(after_check), "aaaaaaaa")
        self.assertEqual(after_uncheck, lines)

    def test_issue2_check_joana_then_uncheck(self):
        lines = list(ISSUE_2_BODY)
        checked = op_check_task(list(lines), "c329bc12")
        restored = op_uncheck_task(list(checked), "c329bc12")
        self.assertEqual(restored, lines)


if __name__ == "__main__":
    unittest.main()
