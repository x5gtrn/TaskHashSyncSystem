#!/usr/bin/env python3
"""
Comprehensive test suite for the TaskHashSyncSystem.

Covers:
  Group A — task_hash.py
  Group B — prepare_sync.py helpers
  Group C — scan_omnifocus_inbox.py
  Group D — sync_to_omnifocus.py
  Group E — Integration tests (mocked file I/O)

Usage:
  python3 -m pytest test_sync_system.py -v
  python3 -m unittest test_sync_system      # also works
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

# ─── Path bootstrap: ensure sibling imports work regardless of cwd ─────────────
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))


# ══════════════════════════════════════════════════════════════════════════════
# Group A — task_hash.py
# ══════════════════════════════════════════════════════════════════════════════

from task_hash import (
    append_hash,
    clean_markdown_links,
    clean_task_name_for_hash,
    compute_hash,
    extract_hash,
    extract_markdown_links,
    get_markdown_urls,
    has_hash,
    make_github_source_id,
    make_vault_source_id,
    remove_hash,
)


class TestComputeHash(unittest.TestCase):
    """compute_hash() — determinism, format, and uniqueness."""

    def test_deterministic_same_source_id(self):
        """Same source_id always produces the same hash."""
        sid = "github:x5gtrn/LIFE#1:Setup Financial Accounts"
        self.assertEqual(compute_hash(sid), compute_hash(sid))

    def test_deterministic_repeated_calls(self):
        """Multiple calls with the same source_id give identical results."""
        sid = "vault:Calendar/Daily/2026/05/2026-05-01.md:Buy milk"
        hashes = [compute_hash(sid) for _ in range(5)]
        self.assertEqual(len(set(hashes)), 1)

    def test_format_exactly_8_lowercase_hex(self):
        """Hash is exactly 8 lowercase hexadecimal characters."""
        h = compute_hash("vault:Calendar/test.md:Task A")
        self.assertEqual(len(h), 8)
        self.assertRegex(h, r'^[0-9a-f]{8}$')

    def test_different_source_ids_differ(self):
        """Different source_ids (very likely) produce different hashes."""
        h1 = compute_hash("vault:Calendar/test.md:Task A")
        h2 = compute_hash("vault:Calendar/test.md:Task B")
        self.assertNotEqual(h1, h2)


class TestAppendHash(unittest.TestCase):
    """append_hash() — adds hash, idempotent on second call."""

    def test_appends_hash_to_clean_name(self):
        """Hash is appended to a name that has no hash."""
        sid = make_vault_source_id("Calendar/Daily/2026/05/2026-05-01.md", "Buy milk")
        result = append_hash("Buy milk", sid)
        self.assertRegex(result, r'^Buy milk \([0-9a-f]{8}\)$')

    def test_idempotent_second_call_unchanged(self):
        """Calling append_hash a second time does not double-hash."""
        sid = make_vault_source_id("Calendar/Daily/2026/05/2026-05-01.md", "Buy milk")
        once = append_hash("Buy milk", sid)
        twice = append_hash(once, sid)
        self.assertEqual(once, twice)


class TestExtractHash(unittest.TestCase):
    """extract_hash() — returns hash string or None."""

    def test_extracts_known_hash(self):
        self.assertEqual(extract_hash("Buy milk (3f88f98c)"), "3f88f98c")

    def test_returns_none_for_plain_name(self):
        self.assertIsNone(extract_hash("Buy milk"))

    def test_returns_none_for_non_hex_suffix(self):
        self.assertIsNone(extract_hash("Task (not-hash)"))

    def test_returns_none_for_uppercase_hex(self):
        """Pattern requires lowercase; uppercase does not match."""
        self.assertIsNone(extract_hash("Task (ABCDEFGH)"))

    def test_does_not_match_7_digit_hash(self):
        """Requires exactly 8 hex digits."""
        self.assertIsNone(extract_hash("Task (abc123d)"))  # 7 digits

    def test_does_not_match_9_digit_hash(self):
        """9-digit suffix is not a valid TaskHash."""
        self.assertIsNone(extract_hash("Task (abc123def)"))  # 9 digits


class TestRemoveHash(unittest.TestCase):
    """remove_hash() — strips (XXXXXXXX) suffix cleanly."""

    def test_strips_hash_suffix(self):
        self.assertEqual(remove_hash("Buy milk (3f88f98c)"), "Buy milk")

    def test_no_change_when_no_hash(self):
        self.assertEqual(remove_hash("Buy milk"), "Buy milk")

    def test_does_not_strip_non_hash_parentheses(self):
        """Non-hash parenthetical content is left untouched."""
        self.assertEqual(remove_hash("Task (not-hash)"), "Task (not-hash)")

    def test_strips_japanese_task_with_hash(self):
        """Works with multibyte characters."""
        self.assertEqual(
            remove_hash("あとでやる - Later (a1b2c3d4)"),
            "あとでやる - Later",
        )


class TestCleanMarkdownLinks(unittest.TestCase):
    """clean_markdown_links() — removes [text](url) syntax, keeps display text."""

    def test_single_link(self):
        self.assertEqual(
            clean_markdown_links("[Buy Groceries](https://store.com)"),
            "Buy Groceries",
        )

    def test_plain_text_unchanged(self):
        self.assertEqual(clean_markdown_links("Buy Groceries"), "Buy Groceries")

    def test_multiple_links_in_text(self):
        result = clean_markdown_links("[A](http://a.com) and [B](http://b.com)")
        self.assertEqual(result, "A and B")

    def test_mixed_link_and_plain_text(self):
        result = clean_markdown_links("Read [this article](https://example.com) today")
        self.assertEqual(result, "Read this article today")


class TestCleanTaskNameForHash(unittest.TestCase):
    """clean_task_name_for_hash() — single function that strips ALL metadata."""

    def test_removes_markdown_link_syntax(self):
        """[text](url) → just the display text."""
        self.assertEqual(
            clean_task_name_for_hash("[Buy Groceries](https://store.com)"),
            "Buy Groceries",
        )

    def test_removes_due_date_emoji(self):
        """📅 YYYY-MM-DD is removed."""
        self.assertEqual(clean_task_name_for_hash("Buy milk 📅 2026-05-10"), "Buy milk")

    def test_removes_due_date_bracket(self):
        """[due:: YYYY-MM-DD] is removed."""
        self.assertEqual(clean_task_name_for_hash("Buy milk [due:: 2026-05-10]"), "Buy milk")

    def test_removes_existing_hash(self):
        """(XXXXXXXX) suffix is removed."""
        self.assertEqual(clean_task_name_for_hash("Buy milk (a1b2c3d4)"), "Buy milk")

    def test_removes_all_metadata_combined(self):
        """All three metadata types stripped in one call."""
        self.assertEqual(
            clean_task_name_for_hash(
                "[Buy Groceries](https://store.com) 📅 2026-05-10 (a1b2c3d4)"
            ),
            "Buy Groceries",
        )

    def test_removes_link_and_date_no_hash(self):
        """Link + date without a trailing hash."""
        self.assertEqual(
            clean_task_name_for_hash("[Task](https://example.com) 📅 2026-05-15"),
            "Task",
        )

    def test_plain_text_unchanged(self):
        """Task without any metadata is returned as-is."""
        self.assertEqual(clean_task_name_for_hash("Buy milk"), "Buy milk")

    def test_japanese_text_unchanged(self):
        """Multi-byte characters survive the cleaning."""
        self.assertEqual(clean_task_name_for_hash("牛乳を買う"), "牛乳を買う")

    def test_japanese_task_with_all_metadata(self):
        """Japanese display text inside [text](url) with date and hash."""
        self.assertEqual(
            clean_task_name_for_hash("[牛乳を買う](https://store.com) 📅 2026-05-10 (a1b2c3d4)"),
            "牛乳を買う",
        )

    def test_hash_stable_across_metadata_variations(self):
        """The hash for 'Buy Groceries' is the same regardless of surrounding metadata."""
        sid = make_vault_source_id("Calendar/Daily/2026/05/2026-05-01.md", "Buy Groceries")
        expected_hash = compute_hash(sid)

        variants = [
            "Buy Groceries",
            "Buy Groceries (a1b2c3d4)",                        # already has a different hash
            "Buy Groceries 📅 2026-05-10",
            "[Buy Groceries](https://store.com)",
            "[Buy Groceries](https://store.com) 📅 2026-05-10",
        ]
        for variant in variants:
            cleaned = clean_task_name_for_hash(variant)
            sid_variant = make_vault_source_id("Calendar/Daily/2026/05/2026-05-01.md", cleaned)
            self.assertEqual(
                compute_hash(sid_variant),
                expected_hash,
                msg=f"Hash changed for variant: '{variant}'",
            )


class TestGetMarkdownUrls(unittest.TestCase):
    """get_markdown_urls() — extracts URL list from [text](url) syntax."""

    def test_single_url(self):
        self.assertEqual(
            get_markdown_urls("[Buy Groceries](https://store.com)"),
            ["https://store.com"],
        )

    def test_empty_list_for_plain_text(self):
        self.assertEqual(get_markdown_urls("No links here"), [])

    def test_multiple_urls(self):
        urls = get_markdown_urls("[A](http://a.com) and [B](http://b.com)")
        self.assertIn("http://a.com", urls)
        self.assertIn("http://b.com", urls)
        self.assertEqual(len(urls), 2)


class TestExtractMarkdownLinks(unittest.TestCase):
    """extract_markdown_links() — returns (cleaned_text, [urls]) tuple."""

    def test_single_link_returns_tuple(self):
        text, urls = extract_markdown_links("[Task](https://example.com)")
        self.assertEqual(text, "Task")
        self.assertEqual(urls, ["https://example.com"])

    def test_multiple_links(self):
        text, urls = extract_markdown_links("[A](http://a.com) text [B](http://b.com)")
        self.assertEqual(text, "A text B")
        self.assertEqual(len(urls), 2)
        self.assertIn("http://a.com", urls)
        self.assertIn("http://b.com", urls)

    def test_no_links_empty_url_list(self):
        text, urls = extract_markdown_links("Plain text only")
        self.assertEqual(text, "Plain text only")
        self.assertEqual(urls, [])


# ══════════════════════════════════════════════════════════════════════════════
# Group B — prepare_sync.py helpers
# ══════════════════════════════════════════════════════════════════════════════

from prepare_sync import (
    extract_due_date,
    extract_tasks,
    prepare_vault_tasks,
    update_vault_files_with_hashes,
)


class TestExtractDueDate(unittest.TestCase):
    """extract_due_date() — parses 📅 and [due::] formats."""

    def test_emoji_format_returns_clean_name_and_date(self):
        name, date = extract_due_date("Buy milk 📅 2026-05-10")
        self.assertEqual(name, "Buy milk")
        self.assertEqual(date, "2026-05-10")

    def test_bracket_format_returns_clean_name_and_date(self):
        name, date = extract_due_date("Buy milk [due:: 2026-05-10]")
        self.assertEqual(name, "Buy milk")
        self.assertEqual(date, "2026-05-10")

    def test_no_date_returns_none(self):
        name, date = extract_due_date("Buy milk")
        self.assertEqual(name, "Buy milk")
        self.assertIsNone(date)

    def test_hash_preserved_after_date_removal(self):
        """If a TaskHash is present, it survives date extraction."""
        name, date = extract_due_date("Buy milk (a1b2c3d4) 📅 2026-05-10")
        self.assertIn("a1b2c3d4", name)
        self.assertEqual(date, "2026-05-10")

    def test_name_stripped_of_trailing_whitespace(self):
        name, _ = extract_due_date("Buy milk  📅 2026-05-10")
        self.assertEqual(name, "Buy milk")


class TestExtractTasks(unittest.TestCase):
    """extract_tasks() — returns 5-tuples (name, line_num, indent, parent, due_date)."""

    def test_basic_task_returns_5_tuple(self):
        content = "## Tasks\n- [ ] Buy milk\n"
        tasks = extract_tasks(Path("test.md"), content)
        self.assertEqual(len(tasks), 1)
        name, line_num, indent, parent, due_date = tasks[0]
        self.assertEqual(name, "Buy milk")
        self.assertIsNone(parent)
        self.assertIsNone(due_date)

    def test_extracts_due_date_from_task_name(self):
        content = "## Tasks\n- [ ] Buy milk 📅 2026-05-10\n"
        tasks = extract_tasks(Path("test.md"), content)
        self.assertEqual(len(tasks), 1)
        name, _, _, _, due_date = tasks[0]
        self.assertEqual(name, "Buy milk")
        self.assertEqual(due_date, "2026-05-10")

    def test_parent_child_hierarchy_via_indentation(self):
        content = "## Tasks\n- [ ] Parent task\n\t- [ ] Child task\n"
        tasks = extract_tasks(Path("test.md"), content)
        self.assertEqual(len(tasks), 2)
        _, _, _, parent, _ = tasks[1]
        self.assertEqual(parent, "Parent task")

    def test_skips_completed_tasks(self):
        content = "## Tasks\n- [x] Done task\n- [ ] Todo task\n"
        tasks = extract_tasks(Path("test.md"), content)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0][0], "Todo task")

    def test_multiple_tasks_in_order(self):
        content = "## Tasks\n- [ ] First\n- [ ] Second\n- [ ] Third\n"
        tasks = extract_tasks(Path("test.md"), content)
        self.assertEqual([t[0] for t in tasks], ["First", "Second", "Third"])


class TestUpdateVaultFilesWithHashes(unittest.TestCase):
    """update_vault_files_with_hashes() — writes hash to end of task line."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.vault_root = Path(self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def _write_note(self, rel_path: str, content: str) -> Path:
        full = self.vault_root / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        return full

    def test_places_hash_at_end_of_plain_task_line(self):
        note = self._write_note(
            "Calendar/Daily/2026/05/2026-05-01.md",
            "## Tasks\n- [ ] Buy milk\n",
        )
        tasks = [{
            "source_id": "vault:Calendar/Daily/2026/05/2026-05-01.md:Buy milk",
            "hash": "a1b2c3d4",
            "dueDate": None,
        }]
        update_vault_files_with_hashes(self.vault_root, tasks)
        self.assertIn("- [ ] Buy milk (a1b2c3d4)", note.read_text(encoding="utf-8"))

    def test_places_hash_after_due_date(self):
        """Hash comes AFTER the 📅 date, not before it."""
        note = self._write_note(
            "Calendar/Daily/2026/05/2026-05-01.md",
            "## Tasks\n- [ ] Buy milk 📅 2026-05-10\n",
        )
        tasks = [{
            "source_id": "vault:Calendar/Daily/2026/05/2026-05-01.md:Buy milk",
            "hash": "a1b2c3d4",
            "dueDate": "2026-05-10",
        }]
        update_vault_files_with_hashes(self.vault_root, tasks)
        content = note.read_text(encoding="utf-8")
        # Full expected form: "- [ ] Buy milk 📅 2026-05-10 (a1b2c3d4)"
        self.assertIn("📅 2026-05-10 (a1b2c3d4)", content)

    def test_preserves_due_date_in_reconstructed_line(self):
        """The 📅 date survives the hash-insertion rewrite."""
        note = self._write_note(
            "Calendar/Daily/2026/05/2026-05-01.md",
            "## Tasks\n- [ ] Task with date 📅 2026-05-15\n",
        )
        tasks = [{
            "source_id": "vault:Calendar/Daily/2026/05/2026-05-01.md:Task with date",
            "hash": "deadbeef",
            "dueDate": "2026-05-15",
        }]
        update_vault_files_with_hashes(self.vault_root, tasks)
        content = note.read_text(encoding="utf-8")
        self.assertIn("📅 2026-05-15", content)
        self.assertIn("(deadbeef)", content)

    def test_idempotent_second_call_no_double_hash(self):
        """Running update twice does not append the hash a second time."""
        note = self._write_note(
            "Calendar/Daily/2026/05/2026-05-01.md",
            "## Tasks\n- [ ] Buy milk\n",
        )
        tasks = [{
            "source_id": "vault:Calendar/Daily/2026/05/2026-05-01.md:Buy milk",
            "hash": "a1b2c3d4",
            "dueDate": None,
        }]
        update_vault_files_with_hashes(self.vault_root, tasks)
        update_vault_files_with_hashes(self.vault_root, tasks)
        content = note.read_text(encoding="utf-8")
        # Hash should appear exactly once
        self.assertEqual(content.count("(a1b2c3d4)"), 1)


class TestUpdateVaultFilesMarkdownLinks(unittest.TestCase):
    """
    Regression tests for the markdown-link bug:
      update_vault_files_with_hashes() must write the TaskHash back to vault
      lines that contain [text](url) Markdown link syntax.

    Root cause: the function searched for the *cleaned* display text (e.g.
    "Buy Groceries") but the vault line contained "[Buy Groceries](url)", so
    the regex never matched and the hash was silently not written.
    """

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.vault_root = Path(self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def _write_note(self, rel_path: str, content: str) -> Path:
        full = self.vault_root / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        return full

    def test_places_hash_after_markdown_link_task(self):
        """Hash is written to a vault line that uses [text](url) syntax."""
        note = self._write_note(
            "Calendar/Daily/2026/05/2026-05-01.md",
            "## Tasks\n- [ ] [Buy Groceries](https://store.com)\n",
        )
        tasks = [{
            "source_id": "vault:Calendar/Daily/2026/05/2026-05-01.md:Buy Groceries",
            "hash": "a1b2c3d4",
            "dueDate": None,
        }]
        update_vault_files_with_hashes(self.vault_root, tasks)
        content = note.read_text(encoding="utf-8")
        # Hash appended, markdown link syntax preserved
        self.assertIn("[Buy Groceries](https://store.com) (a1b2c3d4)", content)

    def test_markdown_link_preserved_after_hash_insertion(self):
        """The [text](url) wrapper is NOT removed when the hash is written."""
        note = self._write_note(
            "Calendar/Daily/2026/05/2026-05-01.md",
            "## Tasks\n- [ ] [Task](https://example.com)\n",
        )
        tasks = [{
            "source_id": "vault:Calendar/Daily/2026/05/2026-05-01.md:Task",
            "hash": "deadbeef",
            "dueDate": None,
        }]
        update_vault_files_with_hashes(self.vault_root, tasks)
        content = note.read_text(encoding="utf-8")
        self.assertIn("[Task](https://example.com)", content)
        self.assertIn("(deadbeef)", content)

    def test_places_hash_after_markdown_link_with_due_date(self):
        """Hash placed after 📅 date when the task also uses [text](url) syntax."""
        note = self._write_note(
            "Calendar/Daily/2026/05/2026-05-01.md",
            "## Tasks\n- [ ] [Buy Groceries](https://store.com) 📅 2026-05-10\n",
        )
        tasks = [{
            "source_id": "vault:Calendar/Daily/2026/05/2026-05-01.md:Buy Groceries",
            "hash": "a1b2c3d4",
            "dueDate": "2026-05-10",
        }]
        update_vault_files_with_hashes(self.vault_root, tasks)
        content = note.read_text(encoding="utf-8")
        # Expected line: - [ ] [Buy Groceries](https://store.com) 📅 2026-05-10 (a1b2c3d4)
        self.assertIn("[Buy Groceries](https://store.com)", content)
        self.assertIn("📅 2026-05-10 (a1b2c3d4)", content)

    def test_idempotent_markdown_link_no_double_hash(self):
        """Running update twice on a markdown-link task does not double the hash."""
        note = self._write_note(
            "Calendar/Daily/2026/05/2026-05-01.md",
            "## Tasks\n- [ ] [Buy Groceries](https://store.com)\n",
        )
        tasks = [{
            "source_id": "vault:Calendar/Daily/2026/05/2026-05-01.md:Buy Groceries",
            "hash": "a1b2c3d4",
            "dueDate": None,
        }]
        update_vault_files_with_hashes(self.vault_root, tasks)
        update_vault_files_with_hashes(self.vault_root, tasks)
        content = note.read_text(encoding="utf-8")
        self.assertEqual(content.count("(a1b2c3d4)"), 1)

    def test_complex_url_preserved(self):
        """URL with query parameters and path is preserved intact."""
        url = "https://example.com/path/to/page?query=value&foo=bar"
        note = self._write_note(
            "Calendar/Daily/2026/05/2026-05-01.md",
            f"## Tasks\n- [ ] [Check Page]({url})\n",
        )
        tasks = [{
            "source_id": "vault:Calendar/Daily/2026/05/2026-05-01.md:Check Page",
            "hash": "cafebabe",
            "dueDate": None,
        }]
        update_vault_files_with_hashes(self.vault_root, tasks)
        content = note.read_text(encoding="utf-8")
        self.assertIn(url, content)
        self.assertIn("(cafebabe)", content)


class TestPrepareVaultTasksHashInVaultNotInState(unittest.TestCase):
    """
    Regression tests for the silent-skip bug:
      When a task already has a hash written in the Vault file but that hash
      is absent from sync_state.json, prepare_vault_tasks() used to fall
      through both branches and silently drop the task (neither "already
      synced" nor added to the output list).

    Fixed behaviour: the task IS included in the output so it can be synced
    to OmniFocus.
    """

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.vault_root = Path(self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def _write_note(self, rel_path: str, content: str) -> Path:
        full = self.vault_root / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        return full

    # ── Core regression ───────────────────────────────────────────────────────

    def test_hash_in_vault_not_in_state_is_returned_as_new(self):
        """
        A task whose hash is already written in the Vault but is absent from
        sync_state must appear in the returned task list.  This is the exact
        scenario that was silently dropped before the fix.
        """
        # Hash value matches CRC32 of source_id for '期限テスト3'
        self._write_note(
            "Calendar/Daily/2026/05/2026-05-07.md",
            "## Tasks\n- [ ] 期限テスト3 (4b1d22d0)\n",
        )
        tasks, _ = prepare_vault_tasks(self.vault_root, state={})
        self.assertEqual(len(tasks), 1)
        self.assertIn("4b1d22d0", tasks[0]["name"])

    def test_hash_in_vault_with_due_date_not_in_state_is_returned(self):
        """Hash + due date in Vault, not in state → returned with dueDate field."""
        self._write_note(
            "Calendar/Daily/2026/05/2026-05-07.md",
            "## Tasks\n- [ ] 期限テスト3 📅 2026-05-12 (4b1d22d0)\n",
        )
        tasks, _ = prepare_vault_tasks(self.vault_root, state={})
        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        self.assertIn("4b1d22d0", task["name"])
        self.assertEqual(task.get("dueDate"), "2026-05-12")

    def test_hash_in_vault_and_in_state_is_skipped(self):
        """When the hash IS in sync_state the task must be skipped (already synced)."""
        source_id = "vault:Calendar/Daily/2026/05/2026-05-07.md:期限テスト3"
        h = compute_hash(source_id)
        self._write_note(
            "Calendar/Daily/2026/05/2026-05-07.md",
            f"## Tasks\n- [ ] 期限テスト3 ({h})\n",
        )
        state = {h: {"source_id": source_id, "of_task_id": "abc", "status": "open"}}
        tasks, _ = prepare_vault_tasks(self.vault_root, state=state)
        self.assertEqual(tasks, [], "Task already in sync_state must not be re-added")

    # ── Hash field integrity ──────────────────────────────────────────────────

    def test_returned_task_hash_matches_vault_hash(self):
        """The hash in the returned dict matches the one written in the Vault."""
        self._write_note(
            "Calendar/Daily/2026/05/2026-05-07.md",
            "## Tasks\n- [ ] 期限テスト3 (4b1d22d0)\n",
        )
        tasks, _ = prepare_vault_tasks(self.vault_root, state={})
        self.assertEqual(tasks[0]["hash"], "4b1d22d0")

    def test_returned_task_name_unchanged_from_vault(self):
        """The task name returned must equal what is already in the Vault."""
        self._write_note(
            "Calendar/Daily/2026/05/2026-05-07.md",
            "## Tasks\n- [ ] 期限テスト3 (4b1d22d0)\n",
        )
        tasks, _ = prepare_vault_tasks(self.vault_root, state={})
        self.assertEqual(tasks[0]["name"], "期限テスト3 (4b1d22d0)")

    # ── Coexistence with normal (no-hash) tasks ───────────────────────────────

    def test_mixed_note_hash_and_no_hash_tasks(self):
        """
        A file with one already-hashed task and one plain task:
        both must be returned (hash-in-vault is treated as new,
        plain task gets a fresh hash).
        """
        self._write_note(
            "Calendar/Daily/2026/05/2026-05-07.md",
            "## Tasks\n"
            "- [ ] 期限テスト3 (4b1d22d0)\n"
            "- [ ] Buy coffee\n",
        )
        tasks, _ = prepare_vault_tasks(self.vault_root, state={})
        self.assertEqual(len(tasks), 2)
        names = {t["name"] for t in tasks}
        self.assertTrue(any("4b1d22d0" in n for n in names))
        self.assertTrue(any("Buy coffee" in n for n in names))

    def test_source_id_uses_clean_name_without_hash(self):
        """source_id must be computed from the task name *without* the hash suffix."""
        self._write_note(
            "Calendar/Daily/2026/05/2026-05-07.md",
            "## Tasks\n- [ ] 期限テスト3 (4b1d22d0)\n",
        )
        tasks, _ = prepare_vault_tasks(self.vault_root, state={})
        source_id = tasks[0]["source_id"]
        # Must NOT contain the hash inside the name part
        self.assertNotIn("4b1d22d0", source_id)
        self.assertIn("期限テスト3", source_id)


# ══════════════════════════════════════════════════════════════════════════════
# Group C — scan_omnifocus_inbox.py
# ══════════════════════════════════════════════════════════════════════════════

from scan_omnifocus_inbox import (
    classify_task_by_parent,
    detect_new_tasks,
)


class TestDetectNewTasks(unittest.TestCase):
    """detect_new_tasks() — filters to untracked, non-container, non-hashed tasks."""

    def test_skips_tasks_that_already_have_hash(self):
        tasks = [{"name": "Buy milk (a1b2c3d4)", "parent_name": None}]
        self.assertEqual(detect_new_tasks(tasks, {}), [])

    def test_skips_project_container_task_exact_match(self):
        """name == parent_name → OmniFocus container, must be skipped."""
        tasks = [{"name": "あとでやる - Later", "parent_name": "あとでやる - Later"}]
        self.assertEqual(detect_new_tasks(tasks, {}), [])

    def test_skips_container_task_when_parent_carries_hash(self):
        """Container detection strips hash from parent_name before comparing."""
        tasks = [{"name": "Later", "parent_name": "Later (a1b2c3d4)"}]
        self.assertEqual(detect_new_tasks(tasks, {}), [])

    def test_skips_container_task_when_task_carries_hash(self):
        """Container detection strips hash from task name too."""
        tasks = [{"name": "Later (a1b2c3d4)", "parent_name": "Later"}]
        # has_hash is True → already skipped by the earlier guard; result still []
        self.assertEqual(detect_new_tasks(tasks, {}), [])

    def test_keeps_genuine_inbox_task_no_parent(self):
        tasks = [{"name": "Buy milk", "parent_name": None}]
        result = detect_new_tasks(tasks, {})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Buy milk")

    def test_keeps_genuine_child_task_different_name(self):
        """Real work item under a project has a different name from its parent."""
        tasks = [{"name": "Review emails", "parent_name": "Later"}]
        result = detect_new_tasks(tasks, {})
        self.assertEqual(len(result), 1)

    def test_skips_task_already_tracked_in_state(self):
        state = {
            "aaaabbbb": {
                "source_id": "vault:Calendar/test.md:Buy milk",
                "of_task_name": "Buy milk (aaaabbbb)",
            }
        }
        tasks = [{"name": "Buy milk", "parent_name": None}]
        result = detect_new_tasks(tasks, state)
        self.assertEqual(result, [])

    def test_returns_multiple_new_tasks(self):
        tasks = [
            {"name": "Task A", "parent_name": None},
            {"name": "Task B", "parent_name": None},
            {"name": "Container", "parent_name": "Container"},  # skipped
        ]
        result = detect_new_tasks(tasks, {})
        self.assertEqual(len(result), 2)
        names = {t["name"] for t in result}
        self.assertEqual(names, {"Task A", "Task B"})


class TestClassifyTaskByParent(unittest.TestCase):
    """classify_task_by_parent() — routes tasks to github_issue_child or vault_task."""

    def _github_state(self, parent_hash: str, issue_num: int = 2) -> Dict[str, Any]:
        return {
            parent_hash: {
                "source_id": f"github:x5gtrn/LIFE#{issue_num}:My Issue",
                "task_type": "github_project",
                "of_task_name": f"My Issue ({parent_hash})",
                "status": "open",
            }
        }

    def test_github_issue_child_when_parent_is_github_project(self):
        state = self._github_state("a1b2c3d4")
        task = {"name": "Child task", "parent_name": "My Issue (a1b2c3d4)"}
        result = classify_task_by_parent(task, state)
        self.assertEqual(result["classification"], "github_issue_child")

    def test_github_issue_child_extracts_issue_number(self):
        state = self._github_state("a1b2c3d4", issue_num=7)
        task = {"name": "Child task", "parent_name": "My Issue (a1b2c3d4)"}
        result = classify_task_by_parent(task, state)
        self.assertEqual(result["issue_number"], 7)

    def test_vault_task_when_parent_has_no_hash(self):
        task = {"name": "Clean desk", "parent_name": "Later"}
        result = classify_task_by_parent(task, {})
        self.assertEqual(result["classification"], "vault_task")

    def test_vault_task_when_no_parent(self):
        task = {"name": "Buy milk", "parent_name": None}
        result = classify_task_by_parent(task, {})
        self.assertEqual(result["classification"], "vault_task")

    def test_vault_task_when_parent_hash_not_in_state(self):
        """Parent hash exists in name but is absent from sync_state → vault_task."""
        task = {"name": "Child task", "parent_name": "Unknown Project (deadbeef)"}
        result = classify_task_by_parent(task, {})
        self.assertEqual(result["classification"], "vault_task")

    def test_vault_task_when_parent_is_vault_task_not_github(self):
        state = {
            "a1b2c3d4": {
                "source_id": "vault:Calendar/test.md:Parent",
                "task_type": "vault_task",  # NOT github_project
                "of_task_name": "Parent (a1b2c3d4)",
                "status": "open",
            }
        }
        task = {"name": "Child task", "parent_name": "Parent (a1b2c3d4)"}
        result = classify_task_by_parent(task, state)
        self.assertEqual(result["classification"], "vault_task")


# ══════════════════════════════════════════════════════════════════════════════
# Group D — sync_to_omnifocus.py
# ══════════════════════════════════════════════════════════════════════════════

from sync_to_omnifocus import (
    format_for_mcp,
    resolve_parent_task,
)


class TestFormatForMcp(unittest.TestCase):
    """format_for_mcp() — shapes tasks for MCP batch_add_items."""

    def _task(self, **kwargs):
        base = {
            "type": "task",
            "name": "Buy milk (a1b2c3d4)",
            "hash": "a1b2c3d4",
            "source_id": "vault:Calendar/Daily/2026/05/2026-05-01.md:Buy milk",
        }
        base.update(kwargs)
        return base

    def test_includes_due_date_when_present(self):
        items = format_for_mcp([self._task(dueDate="2026-05-10")])
        self.assertIn("dueDate", items[0])
        self.assertEqual(items[0]["dueDate"], "2026-05-10")

    def test_includes_note_when_present(self):
        items = format_for_mcp([self._task(note="https://example.com")])
        self.assertIn("note", items[0])
        self.assertEqual(items[0]["note"], "https://example.com")

    def test_excludes_hash_field(self):
        items = format_for_mcp([self._task()])
        self.assertNotIn("hash", items[0])

    def test_excludes_source_id_field(self):
        items = format_for_mcp([self._task()])
        self.assertNotIn("source_id", items[0])

    def test_excludes_parent_task_hash_field(self):
        """parentTaskHash must be resolved before format_for_mcp; it is excluded."""
        items = format_for_mcp([self._task(parentTaskHash="deadbeef")])
        self.assertNotIn("parentTaskHash", items[0])

    def test_empty_due_date_not_included(self):
        items = format_for_mcp([self._task(dueDate="")])
        self.assertNotIn("dueDate", items[0])

    def test_empty_note_not_included(self):
        items = format_for_mcp([self._task(note="")])
        self.assertNotIn("note", items[0])

    def test_none_due_date_not_included(self):
        items = format_for_mcp([self._task(dueDate=None)])
        self.assertNotIn("dueDate", items[0])

    def test_required_fields_always_present(self):
        items = format_for_mcp([self._task()])
        self.assertIn("type", items[0])
        self.assertIn("name", items[0])


class TestResolveParentTask(unittest.TestCase):
    """resolve_parent_task() — swaps parentTaskHash for parentTaskId."""

    def _state(self):
        return {
            "parent123": {
                "of_task_id": "OF-ID-99",
                "of_task_name": "Parent Task (parent123)",
                "status": "open",
            }
        }

    def test_replaces_parent_task_hash_with_parent_task_id(self):
        task = {"type": "task", "name": "Child (c1c1c1c1)", "parentTaskHash": "parent123"}
        resolved = resolve_parent_task(task, self._state())
        self.assertNotIn("parentTaskHash", resolved)
        self.assertIn("parentTaskId", resolved)
        self.assertEqual(resolved["parentTaskId"], "OF-ID-99")

    def test_preserves_due_date_through_resolution(self):
        task = {
            "type": "task",
            "name": "Child (c1c1c1c1)",
            "parentTaskHash": "parent123",
            "dueDate": "2026-05-10",
        }
        resolved = resolve_parent_task(task, self._state())
        self.assertEqual(resolved["dueDate"], "2026-05-10")

    def test_preserves_note_through_resolution(self):
        task = {
            "type": "task",
            "name": "Child (c1c1c1c1)",
            "parentTaskHash": "parent123",
            "note": "https://example.com",
        }
        resolved = resolve_parent_task(task, self._state())
        self.assertEqual(resolved["note"], "https://example.com")

    def test_task_without_parent_hash_returned_unchanged(self):
        task = {"type": "task", "name": "Orphan (a1b2c3d4)"}
        resolved = resolve_parent_task(task, self._state())
        self.assertEqual(resolved, task)

    def test_unknown_parent_hash_removes_field_gracefully(self):
        """If parent hash is not in state, parentTaskHash is dropped without error."""
        task = {
            "type": "task",
            "name": "Child (c1c1c1c1)",
            "parentTaskHash": "unknown0",
        }
        resolved = resolve_parent_task(task, self._state())
        self.assertNotIn("parentTaskHash", resolved)
        self.assertNotIn("parentTaskId", resolved)


# ══════════════════════════════════════════════════════════════════════════════
# Group E — Integration tests (uses real prepare_vault_tasks on temp vault)
# ══════════════════════════════════════════════════════════════════════════════

from prepare_sync import prepare_vault_tasks


class TestIntegration(unittest.TestCase):
    """End-to-end tests covering the full prepare_vault_tasks pipeline."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.vault = Path(self.tmp)
        self.daily_dir = self.vault / "Calendar" / "Daily" / "2026" / "05"
        self.daily_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _note(self, filename: str, content: str) -> Path:
        p = self.daily_dir / filename
        p.write_text(content, encoding="utf-8")
        return p

    # ── due date forwarding ────────────────────────────────────────────────

    def test_vault_task_with_due_date_produces_due_date_in_output(self):
        """📅 date in Vault → dueDate field in tasks_to_sync entry."""
        self._note("2026-05-01.md", "## Tasks\n- [ ] Buy milk 📅 2026-05-10\n")
        tasks, _ = prepare_vault_tasks(self.vault, {})
        self.assertEqual(len(tasks), 1)
        self.assertIn("dueDate", tasks[0])
        self.assertEqual(tasks[0]["dueDate"], "2026-05-10")

    def test_vault_task_without_due_date_has_no_due_date_field(self):
        self._note("2026-05-01.md", "## Tasks\n- [ ] Buy milk\n")
        tasks, _ = prepare_vault_tasks(self.vault, {})
        self.assertEqual(len(tasks), 1)
        self.assertNotIn("dueDate", tasks[0])

    # ── URL / note forwarding ──────────────────────────────────────────────

    def test_vault_task_with_markdown_url_has_non_empty_note(self):
        """Markdown URL in task → non-empty note field in output."""
        self._note(
            "2026-05-01.md",
            "## Tasks\n- [ ] [Buy Groceries](https://store.example.com)\n",
        )
        tasks, _ = prepare_vault_tasks(self.vault, {})
        self.assertEqual(len(tasks), 1)
        self.assertIn("note", tasks[0])
        self.assertIn("https://store.example.com", tasks[0]["note"])

    # ── due_date_updates when task is already synced ───────────────────────

    def test_already_synced_task_with_changed_due_date_appears_in_updates(self):
        """Changed due date on already-synced task → entry in due_date_updates."""
        sid = make_vault_source_id(
            "Calendar/Daily/2026/05/2026-05-01.md", "Buy milk"
        )
        task_hash = compute_hash(sid)
        state = {
            task_hash: {
                "source_id": sid,
                "of_task_id": "OF-ID-1",
                "of_task_name": f"Buy milk ({task_hash})",
                "status": "open",
                "due_date": "2026-05-05",  # old date
            }
        }
        # Vault now shows new due date
        self._note(
            "2026-05-01.md",
            f"## Tasks\n- [ ] Buy milk ({task_hash}) 📅 2026-05-10\n",
        )
        tasks, due_date_updates = prepare_vault_tasks(self.vault, state)
        self.assertEqual(len(tasks), 0)  # already synced → not re-added
        self.assertEqual(len(due_date_updates), 1)
        upd = due_date_updates[0]
        self.assertEqual(upd["task_hash"], task_hash)
        self.assertEqual(upd["new_due_date"], "2026-05-10")
        self.assertEqual(upd["of_task_id"], "OF-ID-1")

    def test_already_synced_task_with_same_due_date_not_in_updates(self):
        """Same due date → NOT in due_date_updates."""
        sid = make_vault_source_id(
            "Calendar/Daily/2026/05/2026-05-01.md", "Buy milk"
        )
        task_hash = compute_hash(sid)
        state = {
            task_hash: {
                "source_id": sid,
                "of_task_id": "OF-ID-1",
                "of_task_name": f"Buy milk ({task_hash})",
                "status": "open",
                "due_date": "2026-05-10",  # same date as vault
            }
        }
        self._note(
            "2026-05-01.md",
            f"## Tasks\n- [ ] Buy milk ({task_hash}) 📅 2026-05-10\n",
        )
        tasks, due_date_updates = prepare_vault_tasks(self.vault, state)
        self.assertEqual(len(due_date_updates), 0)

    def test_already_synced_task_without_any_due_date_not_in_updates(self):
        """Synced task still has no due date in vault → no update emitted."""
        sid = make_vault_source_id(
            "Calendar/Daily/2026/05/2026-05-01.md", "Buy milk"
        )
        task_hash = compute_hash(sid)
        state = {
            task_hash: {
                "source_id": sid,
                "of_task_id": "OF-ID-1",
                "of_task_name": f"Buy milk ({task_hash})",
                "status": "open",
            }
        }
        self._note(
            "2026-05-01.md",
            f"## Tasks\n- [ ] Buy milk ({task_hash})\n",
        )
        _, due_date_updates = prepare_vault_tasks(self.vault, state)
        self.assertEqual(len(due_date_updates), 0)

    # ── OmniFocus container task exclusion ────────────────────────────────

    def test_omnifocus_container_task_excluded_by_detect_new_tasks(self):
        """scan_omnifocus_inbox: container task (name == parent_name) never reaches vault."""
        all_tasks = [
            {"id": "OF-1", "name": "あとでやる - Later",
             "parent_name": "あとでやる - Later", "due_date": None},
            {"id": "OF-2", "name": "Review emails",
             "parent_name": "あとでやる - Later", "due_date": None},
        ]
        new = detect_new_tasks(all_tasks, {})
        names = [t["name"] for t in new]
        self.assertNotIn("あとでやる - Later", names)  # container excluded
        self.assertIn("Review emails", names)           # real task kept

    def test_multiple_container_tasks_all_excluded(self):
        """Multiple OmniFocus container tasks across different projects are all skipped."""
        containers = [
            {"id": "OF-1", "name": "Later", "parent_name": "Later", "due_date": None},
            {"id": "OF-2", "name": "Someday", "parent_name": "Someday", "due_date": None},
            {"id": "OF-3", "name": "Pending", "parent_name": "Pending", "due_date": None},
        ]
        new = detect_new_tasks(containers, {})
        self.assertEqual(new, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
