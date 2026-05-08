#!/usr/bin/env python3
"""
Tests for reverse_sync.py — OmniFocus → Vault/GitHub completion reflection.

Network-dependent functions (update_github_issue_checkbox) and functions that
require the real vault (reflect_completions) are tested with mocks or via dry-run.
Pure logic functions are tested directly.

Run:  python3 -m unittest tests.test_reverse_sync  (from TaskHashSyncSystem/)
  or: python3 -m unittest discover -s tests
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import reverse_sync as rs
from reverse_sync import (
    find_completed_tasks_in_state,
    update_vault_file_checkbox,
    project_has_task_hash,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

SAMPLE_STATE = {
    "aaaaaaaa": {
        "source_id": "vault:Calendar/Daily/2026/05/2026-05-01.md:Buy coffee",
        "of_task_id": "t001",
        "of_task_name": "Buy coffee (aaaaaaaa)",
        "status": "open",
        "task_type": "vault_task",
    },
    "bbbbbbbb": {
        "source_id": "github:x5gtrn/LIFE#2:Submit application",
        "of_task_id": "t002",
        "of_task_name": "Submit application (bbbbbbbb)",
        "status": "open",
        "task_type": "github_task",
    },
    "cccccccc": {
        "source_id": "vault:Calendar/Daily/2026/05/2026-05-03.md:Call dentist",
        "of_task_id": "t003",
        "of_task_name": "Call dentist (cccccccc)",
        "status": "completed",
        "task_type": "vault_task",
    },
    "60c6d084": {
        "source_id": "github:x5gtrn/LIFE#2:転職活動",
        "of_task_id": "proj_001",
        "of_task_name": "転職活動 (60c6d084)",
        "status": "open",
        "task_type": "github_project",
    },
}


# ─── find_completed_tasks_in_state ────────────────────────────────────────────

class TestFindCompletedTasksInState(unittest.TestCase):

    def test_old_string_format_matches(self):
        """Legacy format: list of 'Task Name (hash)' strings."""
        completed = find_completed_tasks_in_state(
            SAMPLE_STATE,
            ["Buy coffee (aaaaaaaa)"]
        )
        self.assertIn("aaaaaaaa", completed)

    def test_new_dict_format_matches(self):
        """New format: list of {'hash': '...', 'name': '...'}."""
        completed = find_completed_tasks_in_state(
            SAMPLE_STATE,
            [{"hash": "aaaaaaaa", "name": "Buy coffee (aaaaaaaa)"}]
        )
        self.assertIn("aaaaaaaa", completed)

    def test_github_task_matches(self):
        completed = find_completed_tasks_in_state(
            SAMPLE_STATE,
            ["Submit application (bbbbbbbb)"]
        )
        self.assertIn("bbbbbbbb", completed)

    def test_unknown_hash_not_returned(self):
        completed = find_completed_tasks_in_state(
            SAMPLE_STATE,
            ["Unknown task (00000000)"]
        )
        self.assertNotIn("00000000", completed)

    def test_empty_completed_list(self):
        completed = find_completed_tasks_in_state(SAMPLE_STATE, [])
        self.assertEqual(completed, {})

    def test_multiple_completions(self):
        completed = find_completed_tasks_in_state(
            SAMPLE_STATE,
            ["Buy coffee (aaaaaaaa)", "Submit application (bbbbbbbb)"]
        )
        self.assertIn("aaaaaaaa", completed)
        self.assertIn("bbbbbbbb", completed)

    def test_already_completed_task_still_returned(self):
        # Even if status=completed in state, we return it (caller decides what to do)
        completed = find_completed_tasks_in_state(
            SAMPLE_STATE,
            ["Call dentist (cccccccc)"]
        )
        self.assertIn("cccccccc", completed)

    def test_project_task_not_matched_if_hash_not_in_of_name(self):
        # Malformed string without parenthesised hash at end → no match
        completed = find_completed_tasks_in_state(
            SAMPLE_STATE,
            ["Buy coffee no hash"]
        )
        self.assertEqual(completed, {})


# ─── update_vault_file_checkbox ───────────────────────────────────────────────

class TestUpdateVaultFileCheckbox(unittest.TestCase):

    def _write_temp(self, content: str) -> Path:
        f = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False, encoding='utf-8'
        )
        f.write(content)
        f.flush()
        return Path(f.name)

    # -- basic checkbox update --

    def test_marks_unchecked_as_checked(self):
        p = self._write_temp("- [ ] Buy coffee (aaaaaaaa)\n")
        rel = Path(p.name)
        with patch.object(rs, 'VAULT_ROOT', Path("/")):
            # VAULT_ROOT / rel = /tmp/... → use absolute path directly
            with patch.object(rs, 'VAULT_ROOT', p.parent):
                result = update_vault_file_checkbox(
                    Path(p.name), "Buy coffee", dry_run=False
                )
        updated = p.read_text(encoding='utf-8')
        self.assertTrue(result)
        self.assertIn("- [x]", updated)

    def test_already_checked_returns_true(self):
        p = self._write_temp("- [x] Buy coffee (aaaaaaaa)\n")
        with patch.object(rs, 'VAULT_ROOT', p.parent):
            result = update_vault_file_checkbox(
                Path(p.name), "Buy coffee", dry_run=False
            )
        self.assertTrue(result)

    def test_task_not_found_returns_false(self):
        p = self._write_temp("- [ ] Other task (bbbbbbbb)\n")
        with patch.object(rs, 'VAULT_ROOT', p.parent):
            result = update_vault_file_checkbox(
                Path(p.name), "Nonexistent task", dry_run=False
            )
        self.assertFalse(result)

    # -- completion date --

    def test_appends_completion_date(self):
        p = self._write_temp("- [ ] Buy coffee (aaaaaaaa)\n")
        with patch.object(rs, 'VAULT_ROOT', p.parent):
            update_vault_file_checkbox(
                Path(p.name), "Buy coffee",
                completed_date="2026-05-08", dry_run=False
            )
        updated = p.read_text(encoding='utf-8')
        self.assertIn("✅ 2026-05-08", updated)

    def test_does_not_duplicate_existing_completion_date(self):
        p = self._write_temp("- [x] Buy coffee (aaaaaaaa) ✅ 2026-05-07\n")
        with patch.object(rs, 'VAULT_ROOT', p.parent):
            update_vault_file_checkbox(
                Path(p.name), "Buy coffee",
                completed_date="2026-05-08", dry_run=False
            )
        updated = p.read_text(encoding='utf-8')
        # Original date preserved, new date NOT added
        self.assertIn("✅ 2026-05-07", updated)
        self.assertNotIn("✅ 2026-05-08", updated)

    # -- due date --

    def test_adds_due_date_before_completion_date(self):
        p = self._write_temp("- [ ] Task (aaaaaaaa)\n")
        with patch.object(rs, 'VAULT_ROOT', p.parent):
            update_vault_file_checkbox(
                Path(p.name), "Task",
                completed_date="2026-05-08",
                due_date="2026-05-07",
                dry_run=False
            )
        updated = p.read_text(encoding='utf-8')
        # 📅 must appear before ✅
        due_pos = updated.find("📅")
        done_pos = updated.find("✅")
        self.assertGreater(due_pos, 0)
        self.assertGreater(done_pos, 0)
        self.assertLess(due_pos, done_pos)

    def test_updates_existing_due_date(self):
        p = self._write_temp("- [ ] Task (aaaaaaaa) 📅 2026-05-05\n")
        with patch.object(rs, 'VAULT_ROOT', p.parent):
            update_vault_file_checkbox(
                Path(p.name), "Task",
                due_date="2026-06-01",
                dry_run=False
            )
        updated = p.read_text(encoding='utf-8')
        self.assertIn("📅 2026-06-01", updated)
        self.assertNotIn("📅 2026-05-05", updated)

    # -- dry run --

    def test_dry_run_does_not_modify_file(self):
        original = "- [ ] Buy coffee (aaaaaaaa)\n"
        p = self._write_temp(original)
        with patch.object(rs, 'VAULT_ROOT', p.parent):
            result = update_vault_file_checkbox(
                Path(p.name), "Buy coffee",
                completed_date="2026-05-08", dry_run=True
            )
        self.assertTrue(result)
        self.assertEqual(p.read_text(encoding='utf-8'), original)

    # -- indented (nested) tasks --

    def test_updates_indented_task(self):
        content = (
            "- [ ] Parent (11111111)\n"
            "    - [ ] Child task (22222222)\n"
        )
        p = self._write_temp(content)
        with patch.object(rs, 'VAULT_ROOT', p.parent):
            result = update_vault_file_checkbox(
                Path(p.name), "Child task", dry_run=False
            )
        updated = p.read_text(encoding='utf-8')
        self.assertTrue(result)
        self.assertIn("    - [x] Child task", updated)
        self.assertIn("- [ ] Parent", updated)  # parent untouched

    # -- Japanese task names --

    def test_japanese_task_name(self):
        p = self._write_temp("- [ ] 服畳んでしまう (68f15567)\n")
        with patch.object(rs, 'VAULT_ROOT', p.parent):
            result = update_vault_file_checkbox(
                Path(p.name), "服畳んでしまう",
                completed_date="2026-05-08", dry_run=False
            )
        updated = p.read_text(encoding='utf-8')
        self.assertTrue(result)
        self.assertIn("- [x] 服畳んでしまう", updated)
        self.assertIn("✅ 2026-05-08", updated)


# ─── project_has_task_hash ────────────────────────────────────────────────────

class TestProjectHasTaskHash(unittest.TestCase):

    def test_returns_true_for_github_project_in_state(self):
        state = {
            "60c6d084": {
                "task_type": "project",
                "of_task_name": "転職活動 (60c6d084)",
            }
        }
        self.assertTrue(project_has_task_hash("転職活動", state))

    def test_returns_false_for_native_project_not_in_state(self):
        self.assertFalse(project_has_task_hash("Later", SAMPLE_STATE))

    def test_returns_false_for_empty_state(self):
        self.assertFalse(project_has_task_hash("Anything", {}))

    def test_returns_false_for_non_project_task_type(self):
        state = {
            "aaaaaaaa": {
                "task_type": "vault_task",
                "of_task_name": "Some task (aaaaaaaa)",
            }
        }
        self.assertFalse(project_has_task_hash("Some task", state))


if __name__ == "__main__":
    unittest.main()
