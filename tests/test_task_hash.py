#!/usr/bin/env python3
"""
Tests for task_hash.py — TaskHash generation, name cleaning, extraction utilities.

Run:  python3 -m unittest tests.test_task_hash  (from TaskHashSyncSystem/)
  or: python3 -m unittest discover -s tests     (all tests)
"""

import sys
import unittest
from pathlib import Path

# Ensure the parent directory is on the path so we can import task_hash
sys.path.insert(0, str(Path(__file__).parent.parent))

from task_hash import (
    compute_hash,
    make_github_source_id,
    make_vault_source_id,
    has_hash,
    extract_hash,
    remove_hash,
    append_hash,
    extract_markdown_links,
    clean_markdown_links,
    get_markdown_urls,
    clean_task_name_for_hash,
)


# ─── compute_hash ────────────────────────────────────────────────────────────

class TestComputeHash(unittest.TestCase):

    def test_deterministic(self):
        """Same source_id always produces the same hash."""
        src = "vault:Calendar/Daily/2026/05/2026-05-01.md:Buy coffee"
        self.assertEqual(compute_hash(src), compute_hash(src))

    def test_format_8_hex_digits(self):
        """Hash is always exactly 8 lowercase hex characters."""
        src = "github:x5gtrn/LIFE#1:Some Task"
        h = compute_hash(src)
        self.assertEqual(len(h), 8)
        self.assertRegex(h, r'^[0-9a-f]{8}$')

    def test_different_sources_produce_different_hashes(self):
        """Different source_ids must not collide."""
        h1 = compute_hash("vault:Calendar/Daily/2026/05/2026-05-08.md:Task A")
        h2 = compute_hash("vault:Calendar/Daily/2026/05/2026-05-08.md:Task B")
        self.assertNotEqual(h1, h2)

    def test_known_vault_hash(self):
        """Regression: verify hash for a known vault task (from sync_state.json)."""
        # source_id from inbox_rename_requests.json (2026-05-08 session)
        src = "vault:Calendar/Daily/2026/05/2026-05-08.md:46,800円"
        self.assertEqual(compute_hash(src), "c0cb8277")

    def test_known_vault_hash_japanese(self):
        """Regression: verify hash for Japanese task name."""
        src = "vault:Calendar/Daily/2026/05/2026-05-08.md:服畳んでしまう"
        self.assertEqual(compute_hash(src), "68f15567")

    def test_encoding_sensitivity(self):
        """Different encodings of the same string must produce the same hash (UTF-8 throughout)."""
        src = "vault:Calendar/Daily/2026/05/2026-05-08.md:送られてきたJDを確認する"
        h = compute_hash(src)
        self.assertEqual(len(h), 8)


# ─── source_id helpers ────────────────────────────────────────────────────────

class TestMakeSourceId(unittest.TestCase):

    def test_github_source_id_format(self):
        sid = make_github_source_id("x5gtrn", "LIFE", 2, "タスク名")
        self.assertEqual(sid, "github:x5gtrn/LIFE#2:タスク名")

    def test_vault_source_id_format(self):
        sid = make_vault_source_id("Calendar/Daily/2026/05/2026-05-08.md", "My Task")
        self.assertEqual(sid, "vault:Calendar/Daily/2026/05/2026-05-08.md:My Task")

    def test_github_source_id_issue_zero(self):
        sid = make_github_source_id("owner", "repo", 0, "title")
        self.assertTrue(sid.startswith("github:owner/repo#0:"))


# ─── has_hash ─────────────────────────────────────────────────────────────────

class TestHasHash(unittest.TestCase):

    def test_detects_hash_at_end(self):
        self.assertTrue(has_hash("Task Name (a1b2c3d4)"))

    def test_no_hash(self):
        self.assertFalse(has_hash("Task Name"))

    def test_hash_not_at_end_is_ignored(self):
        # Hash embedded mid-string (not suffix) should NOT match
        self.assertFalse(has_hash("(a1b2c3d4) Task Name"))

    def test_wrong_length_not_matched(self):
        self.assertFalse(has_hash("Task (abc123)"))        # 6 chars
        self.assertFalse(has_hash("Task (a1b2c3d4e5)"))    # 10 chars

    def test_uppercase_not_matched(self):
        # Hashes must be lowercase hex
        self.assertFalse(has_hash("Task (A1B2C3D4)"))

    def test_japanese_task_with_hash(self):
        self.assertTrue(has_hash("服畳んでしまう (68f15567)"))

    def test_empty_string(self):
        self.assertFalse(has_hash(""))


# ─── extract_hash ─────────────────────────────────────────────────────────────

class TestExtractHash(unittest.TestCase):

    def test_extracts_hash(self):
        self.assertEqual(extract_hash("Task Name (a1b2c3d4)"), "a1b2c3d4")

    def test_returns_none_when_absent(self):
        self.assertIsNone(extract_hash("Task Name"))

    def test_returns_none_for_mid_string_hash(self):
        self.assertIsNone(extract_hash("(a1b2c3d4) Task Name"))

    def test_japanese_task(self):
        self.assertEqual(extract_hash("送られてきたJDを確認する (3d8c2904)"), "3d8c2904")

    def test_empty_string(self):
        self.assertIsNone(extract_hash(""))


# ─── remove_hash ──────────────────────────────────────────────────────────────

class TestRemoveHash(unittest.TestCase):

    def test_removes_hash_suffix(self):
        self.assertEqual(remove_hash("Task Name (a1b2c3d4)"), "Task Name")

    def test_noop_when_no_hash(self):
        self.assertEqual(remove_hash("Task Name"), "Task Name")

    def test_noop_mid_string_hash(self):
        # Hash not at suffix — must be left untouched
        self.assertEqual(remove_hash("(a1b2c3d4) Task Name"), "(a1b2c3d4) Task Name")

    def test_japanese_task(self):
        self.assertEqual(remove_hash("服畳んでしまう (68f15567)"), "服畳んでしまう")

    def test_idempotent(self):
        name = "Task (deadbeef)"
        self.assertEqual(remove_hash(remove_hash(name)), remove_hash(name))


# ─── append_hash ──────────────────────────────────────────────────────────────

class TestAppendHash(unittest.TestCase):

    def test_appends_hash_when_absent(self):
        src = "vault:Calendar/Daily/2026/05/2026-05-01.md:Buy coffee"
        result = append_hash("Buy coffee", src)
        h = compute_hash(src)
        self.assertEqual(result, f"Buy coffee ({h})")

    def test_idempotent_when_hash_present(self):
        name = "Task (a1b2c3d4)"
        src = "vault:some/path.md:Task"
        # Has hash already → return unchanged
        self.assertEqual(append_hash(name, src), name)


# ─── Markdown link helpers ─────────────────────────────────────────────────────

class TestMarkdownLinks(unittest.TestCase):

    def test_extract_text_and_url(self):
        text, urls = extract_markdown_links("[Google](https://google.com)")
        self.assertEqual(text, "Google")
        self.assertEqual(urls, ["https://google.com"])

    def test_multiple_links(self):
        raw = "[A](http://a.com) and [B](http://b.com)"
        text, urls = extract_markdown_links(raw)
        self.assertEqual(text, "A and B")
        self.assertIn("http://a.com", urls)
        self.assertIn("http://b.com", urls)

    def test_no_links(self):
        text, urls = extract_markdown_links("Plain text")
        self.assertEqual(text, "Plain text")
        self.assertEqual(urls, [])

    def test_clean_markdown_links(self):
        result = clean_markdown_links("[Rayzel Lie](https://linkedin.com/in/abc)")
        self.assertEqual(result, "Rayzel Lie")

    def test_get_markdown_urls(self):
        urls = get_markdown_urls("[X](https://x.com) text [Y](https://y.com)")
        self.assertEqual(sorted(urls), ["https://x.com", "https://y.com"])


# ─── clean_task_name_for_hash ─────────────────────────────────────────────────

class TestCleanTaskNameForHash(unittest.TestCase):
    """
    The single source of truth for task name normalisation before hash generation.
    Cleaning order: markdown links → due date emoji → due date bracket → existing hash.
    """

    def test_strips_markdown_link(self):
        self.assertEqual(
            clean_task_name_for_hash("[Buy Groceries](https://store.com)"),
            "Buy Groceries"
        )

    def test_strips_due_date_emoji(self):
        self.assertEqual(
            clean_task_name_for_hash("Task Name 📅 2026-05-15"),
            "Task Name"
        )

    def test_strips_due_date_bracket(self):
        self.assertEqual(
            clean_task_name_for_hash("Task Name [due:: 2026-05-15]"),
            "Task Name"
        )

    def test_strips_existing_hash(self):
        self.assertEqual(
            clean_task_name_for_hash("Task Name (a1b2c3d4)"),
            "Task Name"
        )

    def test_strips_all_combined(self):
        raw = "[Buy Groceries](https://store.com) 📅 2026-05-10 (a1b2c3d4)"
        self.assertEqual(clean_task_name_for_hash(raw), "Buy Groceries")

    def test_noop_plain_name(self):
        self.assertEqual(clean_task_name_for_hash("Plain Task"), "Plain Task")

    def test_strips_whitespace(self):
        self.assertEqual(clean_task_name_for_hash("  Task  "), "Task")

    def test_japanese_task_unchanged(self):
        self.assertEqual(clean_task_name_for_hash("服畳んでしまう"), "服畳んでしまう")

    def test_hash_stable_after_cleaning(self):
        """Hash computed on cleaned name equals hash of the same name passed directly."""
        raw = "Buy Groceries 📅 2026-05-10 (ffffffff)"
        clean = clean_task_name_for_hash(raw)  # → "Buy Groceries"
        src = f"vault:Calendar/Daily/2026/05/2026-05-01.md:{clean}"
        h_from_raw = compute_hash(f"vault:Calendar/Daily/2026/05/2026-05-01.md:{clean_task_name_for_hash(raw)}")
        h_direct = compute_hash(src)
        self.assertEqual(h_from_raw, h_direct)


if __name__ == "__main__":
    unittest.main()
