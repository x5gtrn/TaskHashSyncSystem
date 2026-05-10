#!/usr/bin/env python3
"""
Tests for scan_omnifocus_inbox.py — routing, hash generation, Daily Note I/O,
added_date routing, and due-date sync.

Run:  python3 -m unittest tests.test_scan_omnifocus_inbox  (from TaskHashSyncSystem/)
  or: python3 -m unittest discover -s tests
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import scan_omnifocus_inbox as soi
from scan_omnifocus_inbox import (
    classify_task_by_parent,
    detect_new_tasks,
    generate_vault_task_hashes,
    insert_tasks_into_daily_note,
    _read_vault_due_date,
    _find_file_containing_hash,
    sync_due_dates_to_vault,
    get_daily_note_relative_path,
    get_daily_note_path,
    create_daily_note_content,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────
#
# SAMPLE_STATE models a job-search GitHub project (Issue #2) with:
#   - 60c6d084: the project itself ("Job Search Q3")
#   - 4375b980: a direct child task ("Follow up on Rayzel referral")
#   - aaaaaaaa: an unrelated vault task already tracked

SAMPLE_STATE = {
    "60c6d084": {
        "source_id": "github:x5gtrn/LIFE#2:Job Search Q3",
        "of_task_id": "proj_001",
        "of_task_name": "Job Search Q3 (60c6d084)",
        "status": "open",
        "task_type": "github_project",
    },
    "4375b980": {
        "source_id": "github:x5gtrn/LIFE#2:Follow up on Rayzel referral",
        "of_task_id": "task_001",
        "of_task_name": "Follow up on Rayzel referral (4375b980)",
        "status": "open",
        "task_type": "github_task",
        "parent_task_hash": "60c6d084",
    },
    "aaaaaaaa": {
        "source_id": "vault:Calendar/Daily/2026/05/2026-05-01.md:Buy coffee beans",
        "of_task_id": "task_vault_01",
        "of_task_name": "Buy coffee beans (aaaaaaaa)",
        "status": "open",
        "task_type": "vault_task",
    },
}


# ─── classify_task_by_parent ──────────────────────────────────────────────────

class TestClassifyTaskByParent(unittest.TestCase):

    def test_inbox_task_no_parent_is_vault_task(self):
        task = {"id": "t1", "name": "Buy milk", "parent_name": None}
        result = classify_task_by_parent(task, SAMPLE_STATE)
        self.assertEqual(result["classification"], "vault_task")
        self.assertIsNone(result["parent_hash"])
        self.assertIsNone(result["issue_number"])

    def test_task_under_github_project_is_github_issue_child(self):
        task = {
            "id": "t2",
            "name": "Send resume to Acme Corp",
            "parent_name": "Job Search Q3 (60c6d084)",
        }
        result = classify_task_by_parent(task, SAMPLE_STATE)
        self.assertEqual(result["classification"], "github_issue_child")
        self.assertEqual(result["parent_hash"], "60c6d084")
        self.assertEqual(result["issue_number"], 2)

    def test_task_under_native_project_no_hash_is_vault_task(self):
        task = {
            "id": "t3",
            "name": "Clean the desk",
            "parent_name": "Later",  # no TaskHash
        }
        result = classify_task_by_parent(task, SAMPLE_STATE)
        self.assertEqual(result["classification"], "vault_task")
        self.assertIsNone(result["parent_hash"])

    def test_task_under_unknown_hash_is_vault_task(self):
        # Parent has a hash, but that hash is not in state
        task = {
            "id": "t4",
            "name": "Orphan task",
            "parent_name": "Unknown Project (deadbeef)",
        }
        result = classify_task_by_parent(task, SAMPLE_STATE)
        self.assertEqual(result["classification"], "vault_task")

    def test_parent_name_stored_in_result(self):
        task = {"id": "t5", "name": "Some task", "parent_name": "Later"}
        result = classify_task_by_parent(task, SAMPLE_STATE)
        self.assertEqual(result["parent_name"], "Later")

    def test_task_under_vault_task_type_project_is_not_github_child(self):
        # Even if parent has a hash, task_type != github_project -> vault_task
        state = {
            "bbbbbbbb": {
                "source_id": "vault:Calendar/Daily/2026/05/2026-05-01.md:Parent",
                "task_type": "vault_task",
            }
        }
        task = {"id": "t6", "name": "Child task", "parent_name": "Parent (bbbbbbbb)"}
        result = classify_task_by_parent(task, state)
        self.assertEqual(result["classification"], "vault_task")


# ─── detect_new_tasks ─────────────────────────────────────────────────────────

class TestDetectNewTasks(unittest.TestCase):

    def test_skips_tasks_with_existing_hash(self):
        tasks = [{"id": "t1", "name": "Done task (c0cb8277)", "parent_name": None}]
        result = detect_new_tasks(tasks, SAMPLE_STATE)
        self.assertEqual(len(result), 0)

    def test_detects_hashless_task(self):
        tasks = [{"id": "t2", "name": "New task without hash", "parent_name": None}]
        result = detect_new_tasks(tasks, SAMPLE_STATE)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "New task without hash")

    def test_skips_already_tracked_by_base_name(self):
        # "Buy coffee beans" is in SAMPLE_STATE source_id
        tasks = [{"id": "t3", "name": "Buy coffee beans", "parent_name": None}]
        result = detect_new_tasks(tasks, SAMPLE_STATE)
        self.assertEqual(len(result), 0)

    def test_skips_container_task_same_name_as_parent(self):
        # OmniFocus native project container: task name == parent name
        tasks = [{"id": "t4", "name": "Later", "parent_name": "Later"}]
        result = detect_new_tasks(tasks, SAMPLE_STATE)
        self.assertEqual(len(result), 0)

    def test_skips_container_task_with_hash_in_parent(self):
        # Container pattern: project name appears as both task and parent
        tasks = [
            {
                "id": "t5",
                "name": "Job Search Q3 (60c6d084)",
                "parent_name": "Job Search Q3 (60c6d084)",
            }
        ]
        result = detect_new_tasks(tasks, SAMPLE_STATE)
        self.assertEqual(len(result), 0)

    def test_empty_name_skipped(self):
        tasks = [{"id": "t6", "name": "", "parent_name": None}]
        result = detect_new_tasks(tasks, {})
        self.assertEqual(len(result), 0)

    def test_multiple_tasks_mixed(self):
        tasks = [
            {"id": "t1", "name": "Buy coffee beans", "parent_name": None},  # tracked
            {"id": "t2", "name": "Existing hash (aaaaaaaa)", "parent_name": None},  # has hash
            {"id": "t3", "name": "Truly new task", "parent_name": None},  # new
        ]
        result = detect_new_tasks(tasks, SAMPLE_STATE)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Truly new task")


# ─── insert_tasks_into_daily_note ─────────────────────────────────────────────

class TestInsertTasksIntoDailyNote(unittest.TestCase):

    MINIMAL_NOTE = "---\ntags: [daily]\n---\n\n## Tasks\n\n## Projects\n"

    def _make_task(self, name, hash_val, due_date=None):
        return {
            "new_name": f"{name} ({hash_val})",
            "original_name": name,
            "task_hash": hash_val,
            "due_date": due_date,
        }

    def test_inserts_under_tasks_section(self):
        result = insert_tasks_into_daily_note(
            self.MINIMAL_NOTE,
            [self._make_task("Buy milk", "aaaaaaaa")]
        )
        self.assertIn("- [ ] Buy milk (aaaaaaaa)", result)

    def test_inserted_before_projects_section(self):
        result = insert_tasks_into_daily_note(
            self.MINIMAL_NOTE,
            [self._make_task("Buy milk", "aaaaaaaa")]
        )
        lines = result.splitlines()
        task_idx = next(i for i, l in enumerate(lines) if "Buy milk" in l)
        proj_idx = next(i for i, l in enumerate(lines) if l.strip() == "## Projects")
        self.assertLess(task_idx, proj_idx)

    def test_due_date_appended_when_present(self):
        """Regression: due_date must be written to Vault when a task is inserted."""
        result = insert_tasks_into_daily_note(
            self.MINIMAL_NOTE,
            [self._make_task("Pay monthly rent", "bbbbbbbb", due_date="2026-05-20")]
        )
        self.assertIn("- [ ] Pay monthly rent (bbbbbbbb) 📅 2026-05-20", result)

    def test_no_due_date_when_none(self):
        result = insert_tasks_into_daily_note(
            self.MINIMAL_NOTE,
            [self._make_task("Call accountant", "cccccccc", due_date=None)]
        )
        task_line = next(l for l in result.splitlines() if "Call accountant" in l)
        self.assertNotIn("📅", task_line)

    def test_idempotent_no_duplicate(self):
        result1 = insert_tasks_into_daily_note(
            self.MINIMAL_NOTE,
            [self._make_task("Water the plants", "dddddddd")]
        )
        result2 = insert_tasks_into_daily_note(
            result1,
            [self._make_task("Water the plants", "dddddddd")]
        )
        # Should appear exactly once
        self.assertEqual(result2.count("Water the plants"), 1)

    def test_creates_tasks_section_if_missing(self):
        note_without_section = "---\ntags: [daily]\n---\n\nSome freeform content\n"
        result = insert_tasks_into_daily_note(
            note_without_section,
            [self._make_task("Orphan task", "eeeeeeee")]
        )
        self.assertIn("## Tasks", result)
        self.assertIn("Orphan task", result)

    def test_multiple_tasks_all_inserted(self):
        tasks = [
            self._make_task("Order office supplies", "11111111"),
            self._make_task("Pay monthly rent", "22222222", due_date="2026-06-01"),
            self._make_task("Schedule team standup", "33333333"),
        ]
        result = insert_tasks_into_daily_note(self.MINIMAL_NOTE, tasks)
        self.assertIn("Order office supplies", result)
        self.assertIn("Pay monthly rent (22222222) 📅 2026-06-01", result)
        self.assertIn("Schedule team standup", result)

    def test_existing_tasks_not_overwritten(self):
        note_with_task = (
            "---\ntags: [daily]\n---\n\n## Tasks\n"
            "- [x] Old completed task (ffffffff)\n\n## Projects\n"
        )
        result = insert_tasks_into_daily_note(
            note_with_task,
            [self._make_task("New incoming task", "00000001")]
        )
        self.assertIn("- [x] Old completed task (ffffffff)", result)
        self.assertIn("- [ ] New incoming task (00000001)", result)


# ─── _read_vault_due_date ─────────────────────────────────────────────────────

class TestReadVaultDueDate(unittest.TestCase):

    def _write_temp(self, content: str) -> Path:
        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False, encoding='utf-8'
        )
        tmp.write(content)
        tmp.flush()
        return Path(tmp.name)

    def test_reads_due_date_when_present(self):
        p = self._write_temp("- [ ] Pay monthly rent (aaaaaaaa) 📅 2026-05-20\n")
        self.assertEqual(_read_vault_due_date(p, "aaaaaaaa"), "2026-05-20")

    def test_returns_none_when_no_due_date(self):
        p = self._write_temp("- [ ] Pay monthly rent (aaaaaaaa)\n")
        self.assertIsNone(_read_vault_due_date(p, "aaaaaaaa"))

    def test_returns_none_when_hash_not_in_file(self):
        p = self._write_temp("- [ ] Some other task (bbbbbbbb)\n")
        self.assertIsNone(_read_vault_due_date(p, "aaaaaaaa"))

    def test_returns_none_when_file_missing(self):
        self.assertIsNone(_read_vault_due_date(Path("/nonexistent/path.md"), "aaaaaaaa"))

    def test_reads_due_date_from_completed_task(self):
        p = self._write_temp(
            "- [x] Pay monthly rent (aaaaaaaa) 📅 2026-05-20 ✅ 2026-05-21\n"
        )
        self.assertEqual(_read_vault_due_date(p, "aaaaaaaa"), "2026-05-20")

    def test_handles_multiple_tasks_picks_correct_one(self):
        content = (
            "- [ ] Pay monthly rent (aaaaaaaa) 📅 2026-05-10\n"
            "- [ ] Submit tax return (bbbbbbbb) 📅 2026-06-01\n"
        )
        p = self._write_temp(content)
        self.assertEqual(_read_vault_due_date(p, "aaaaaaaa"), "2026-05-10")
        self.assertEqual(_read_vault_due_date(p, "bbbbbbbb"), "2026-06-01")


# ─── _find_file_containing_hash ───────────────────────────────────────────────

class TestFindFileContainingHash(unittest.TestCase):

    def test_finds_file_in_temp_calendar_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_root = Path(tmpdir)
            cal_dir = vault_root / "Calendar" / "Daily" / "2026" / "05"
            cal_dir.mkdir(parents=True)
            note = cal_dir / "2026-05-08.md"
            note.write_text("- [ ] Pay monthly rent (deadbeef)\n", encoding='utf-8')

            with patch.object(soi, 'VAULT_ROOT', vault_root):
                result = _find_file_containing_hash("deadbeef")

        self.assertIsNotNone(result)
        self.assertEqual(result.name, "2026-05-08.md")

    def test_returns_none_when_hash_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_root = Path(tmpdir)
            cal_dir = vault_root / "Calendar" / "Daily" / "2026" / "05"
            cal_dir.mkdir(parents=True)
            (cal_dir / "2026-05-08.md").write_text(
                "- [ ] Some task (aaaaaaaa)\n", encoding='utf-8'
            )

            with patch.object(soi, 'VAULT_ROOT', vault_root):
                result = _find_file_containing_hash("00000000")

        self.assertIsNone(result)

    def test_returns_none_when_calendar_dir_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_root = Path(tmpdir)
            # Calendar/ directory does not exist
            with patch.object(soi, 'VAULT_ROOT', vault_root):
                result = _find_file_containing_hash("aaaaaaaa")
        self.assertIsNone(result)


# ─── sync_due_dates_to_vault ──────────────────────────────────────────────────

class TestSyncDueDatesToVault(unittest.TestCase):
    """
    Tests for the OmniFocus -> Vault due-date sync logic.
    Uses a temporary directory to avoid touching the real vault.
    """

    def _setup_vault(self, note_content: str, rel_path: str):
        """Create a temp vault with a single note. Returns (vault_root, abs_note_path)."""
        tmpdir = tempfile.mkdtemp()
        abs_path = Path(tmpdir) / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(note_content, encoding='utf-8')
        return Path(tmpdir), abs_path

    def test_adds_due_date_when_of_has_date_and_vault_has_none(self):
        rel = "Calendar/Daily/2026/05/2026-05-08.md"
        note = "- [ ] Pay monthly rent (aaaaaaaa)\n"
        vault_root, abs_path = self._setup_vault(note, rel)

        state = {
            "aaaaaaaa": {
                "source_id": f"vault:{rel}:Pay monthly rent",
                "task_type": "vault_task",
                "status": "open",
            }
        }
        all_tasks = [{"name": "Pay monthly rent (aaaaaaaa)", "due_date": "2026-05-20"}]

        with patch.object(soi, 'VAULT_ROOT', vault_root):
            count = sync_due_dates_to_vault(all_tasks, state, dry_run=False)

        self.assertEqual(count, 1)
        updated = abs_path.read_text(encoding='utf-8')
        self.assertIn("📅 2026-05-20", updated)

    def test_removes_due_date_when_of_has_none_and_vault_has_date(self):
        rel = "Calendar/Daily/2026/05/2026-05-08.md"
        note = "- [ ] Pay monthly rent (aaaaaaaa) 📅 2026-05-20\n"
        vault_root, abs_path = self._setup_vault(note, rel)

        state = {
            "aaaaaaaa": {
                "source_id": f"vault:{rel}:Pay monthly rent",
                "task_type": "vault_task",
                "status": "open",
            }
        }
        all_tasks = [{"name": "Pay monthly rent (aaaaaaaa)", "due_date": None}]

        with patch.object(soi, 'VAULT_ROOT', vault_root):
            count = sync_due_dates_to_vault(all_tasks, state, dry_run=False)

        self.assertEqual(count, 1)
        updated = abs_path.read_text(encoding='utf-8')
        self.assertNotIn("📅", updated)

    def test_updates_due_date_when_both_differ(self):
        rel = "Calendar/Daily/2026/05/2026-05-08.md"
        note = "- [ ] Pay monthly rent (aaaaaaaa) 📅 2026-05-10\n"
        vault_root, abs_path = self._setup_vault(note, rel)

        state = {
            "aaaaaaaa": {
                "source_id": f"vault:{rel}:Pay monthly rent",
                "task_type": "vault_task",
                "status": "open",
            }
        }
        all_tasks = [{"name": "Pay monthly rent (aaaaaaaa)", "due_date": "2026-06-01"}]

        with patch.object(soi, 'VAULT_ROOT', vault_root):
            count = sync_due_dates_to_vault(all_tasks, state, dry_run=False)

        self.assertEqual(count, 1)
        updated = abs_path.read_text(encoding='utf-8')
        self.assertIn("📅 2026-06-01", updated)
        self.assertNotIn("📅 2026-05-10", updated)

    def test_no_change_when_dates_already_match(self):
        rel = "Calendar/Daily/2026/05/2026-05-08.md"
        note = "- [ ] Pay monthly rent (aaaaaaaa) 📅 2026-05-20\n"
        vault_root, abs_path = self._setup_vault(note, rel)

        state = {
            "aaaaaaaa": {
                "source_id": f"vault:{rel}:Pay monthly rent",
                "task_type": "vault_task",
                "status": "open",
            }
        }
        all_tasks = [{"name": "Pay monthly rent (aaaaaaaa)", "due_date": "2026-05-20"}]

        with patch.object(soi, 'VAULT_ROOT', vault_root):
            count = sync_due_dates_to_vault(all_tasks, state, dry_run=False)

        self.assertEqual(count, 0)

    def test_skips_completed_tasks(self):
        rel = "Calendar/Daily/2026/05/2026-05-08.md"
        note = "- [x] Pay monthly rent (aaaaaaaa)\n"
        vault_root, abs_path = self._setup_vault(note, rel)

        state = {
            "aaaaaaaa": {
                "source_id": f"vault:{rel}:Pay monthly rent",
                "task_type": "vault_task",
                "status": "completed",
            }
        }
        all_tasks = [{"name": "Pay monthly rent (aaaaaaaa)", "due_date": "2026-05-20"}]

        with patch.object(soi, 'VAULT_ROOT', vault_root):
            count = sync_due_dates_to_vault(all_tasks, state, dry_run=False)

        self.assertEqual(count, 0)

    def test_skips_github_tasks(self):
        rel = "Calendar/Daily/2026/05/2026-05-08.md"
        note = "- [ ] Pay monthly rent (aaaaaaaa)\n"
        vault_root, abs_path = self._setup_vault(note, rel)

        state = {
            "aaaaaaaa": {
                "source_id": "github:x5gtrn/LIFE#2:Pay monthly rent",
                "task_type": "github_task",
                "status": "open",
            }
        }
        all_tasks = [{"name": "Pay monthly rent (aaaaaaaa)", "due_date": "2026-05-20"}]

        with patch.object(soi, 'VAULT_ROOT', vault_root):
            count = sync_due_dates_to_vault(all_tasks, state, dry_run=False)

        self.assertEqual(count, 0)

    def test_dry_run_does_not_write_file(self):
        rel = "Calendar/Daily/2026/05/2026-05-08.md"
        note = "- [ ] Pay monthly rent (aaaaaaaa)\n"
        vault_root, abs_path = self._setup_vault(note, rel)

        state = {
            "aaaaaaaa": {
                "source_id": f"vault:{rel}:Pay monthly rent",
                "task_type": "vault_task",
                "status": "open",
            }
        }
        all_tasks = [{"name": "Pay monthly rent (aaaaaaaa)", "due_date": "2026-05-20"}]

        with patch.object(soi, 'VAULT_ROOT', vault_root):
            count = sync_due_dates_to_vault(all_tasks, state, dry_run=True)

        self.assertEqual(count, 1)  # change is detected and reported
        unchanged = abs_path.read_text(encoding='utf-8')
        self.assertNotIn("📅", unchanged)  # but file is NOT modified

    def test_fallback_finds_file_when_source_id_path_wrong(self):
        """
        Regression: when source_id points to a non-existent file, the function
        must search Calendar/ for the actual file that contains the hash.
        """
        wrong_rel = "Calendar/Daily/2026/05/2026-05-09.md"  # does not exist
        real_rel  = "Calendar/Daily/2026/05/2026-05-07.md"

        with tempfile.TemporaryDirectory() as tmpdir:
            vault_root = Path(tmpdir)
            real_dir = vault_root / "Calendar" / "Daily" / "2026" / "05"
            real_dir.mkdir(parents=True)
            (real_dir / "2026-05-07.md").write_text(
                "- [ ] Pay monthly rent (aaaaaaaa)\n", encoding='utf-8'
            )

            state = {
                "aaaaaaaa": {
                    "source_id": f"vault:{wrong_rel}:Pay monthly rent",  # wrong path
                    "task_type": "vault_task",
                    "status": "open",
                }
            }
            all_tasks = [{"name": "Pay monthly rent (aaaaaaaa)", "due_date": "2026-05-14"}]

            with patch.object(soi, 'VAULT_ROOT', vault_root):
                count = sync_due_dates_to_vault(all_tasks, state, dry_run=False)

            self.assertEqual(count, 1)
            updated = (real_dir / "2026-05-07.md").read_text(encoding='utf-8')
            self.assertIn("📅 2026-05-14", updated)

    def test_updates_sync_state_due_date_in_memory(self):
        rel = "Calendar/Daily/2026/05/2026-05-08.md"
        note = "- [ ] Pay monthly rent (aaaaaaaa)\n"
        vault_root, _ = self._setup_vault(note, rel)

        state = {
            "aaaaaaaa": {
                "source_id": f"vault:{rel}:Pay monthly rent",
                "task_type": "vault_task",
                "status": "open",
            }
        }
        all_tasks = [{"name": "Pay monthly rent (aaaaaaaa)", "due_date": "2026-05-25"}]

        with patch.object(soi, 'VAULT_ROOT', vault_root):
            sync_due_dates_to_vault(all_tasks, state, dry_run=False)

        self.assertEqual(state["aaaaaaaa"].get("due_date"), "2026-05-25")

    def test_deletes_due_date_from_sync_state_when_of_removes_it(self):
        rel = "Calendar/Daily/2026/05/2026-05-08.md"
        note = "- [ ] Pay monthly rent (aaaaaaaa) 📅 2026-05-20\n"
        vault_root, _ = self._setup_vault(note, rel)

        state = {
            "aaaaaaaa": {
                "source_id": f"vault:{rel}:Pay monthly rent",
                "task_type": "vault_task",
                "status": "open",
                "due_date": "2026-05-20",
            }
        }
        all_tasks = [{"name": "Pay monthly rent (aaaaaaaa)", "due_date": None}]

        with patch.object(soi, 'VAULT_ROOT', vault_root):
            sync_due_dates_to_vault(all_tasks, state, dry_run=False)

        self.assertNotIn("due_date", state["aaaaaaaa"])


# ─── path helpers ─────────────────────────────────────────────────────────────

class TestPathHelpers(unittest.TestCase):

    def test_daily_note_relative_path(self):
        self.assertEqual(
            get_daily_note_relative_path("2026-05-08"),
            "Calendar/Daily/2026/05/2026-05-08.md"
        )

    def test_daily_note_path_is_absolute(self):
        p = get_daily_note_path("2026-05-08")
        self.assertTrue(p.is_absolute())
        self.assertTrue(str(p).endswith("2026-05-08.md"))

    def test_create_daily_note_has_required_sections(self):
        content = create_daily_note_content("2026-05-08")
        self.assertIn("## Tasks", content)
        self.assertIn("## Projects", content)
        self.assertIn("---", content)


# ─── added_date routing ───────────────────────────────────────────────────────

class TestAddedDateRouting(unittest.TestCase):
    """
    generate_vault_task_hashes() must route each task to the Daily Note that
    corresponds to the task's OmniFocus creation date (added_date), not today.

    When added_date is absent or null, the fallback_date is used instead.
    """

    # ── helpers ──────────────────────────────────────────────────────────────

    def _make_vault_item(self, name: str, added_date=None, due_date=None):
        """Build a classify_task_by_parent()-style dict for a vault_task."""
        task = {
            "id": "of_" + name.replace(" ", "_"),
            "name": name,
            "due_date": due_date,
            "parent_name": None,
        }
        if added_date is not None:
            task["added_date"] = added_date
        return {
            "task": task,
            "classification": "vault_task",
            "parent_name": None,
            "parent_hash": None,
            "parent_source_id": None,
            "issue_number": None,
        }

    # ── target_date selection ─────────────────────────────────────────────

    def test_added_date_used_as_target_date(self):
        """Task with added_date='2026-05-01' must target 2026-05-01 Daily Note."""
        items = [self._make_vault_item("Book dentist appointment", added_date="2026-05-01")]
        enriched = generate_vault_task_hashes(items, fallback_date="2026-05-10")
        self.assertEqual(enriched[0]["target_date"], "2026-05-01")

    def test_null_added_date_falls_back_to_fallback(self):
        """Task with added_date=null must use fallback_date."""
        items = [self._make_vault_item("Buy printer paper", added_date=None)]
        enriched = generate_vault_task_hashes(items, fallback_date="2026-05-10")
        self.assertEqual(enriched[0]["target_date"], "2026-05-10")

    def test_absent_added_date_falls_back_to_fallback(self):
        """Task dict with no added_date key at all must use fallback_date."""
        # _make_vault_item without added_date kwarg omits the key entirely
        item = self._make_vault_item("Pick up dry cleaning")
        # Confirm the key is absent
        self.assertNotIn("added_date", item["task"])
        enriched = generate_vault_task_hashes([item], fallback_date="2026-05-09")
        self.assertEqual(enriched[0]["target_date"], "2026-05-09")

    def test_added_date_different_from_fallback(self):
        """added_date must take precedence over fallback_date when both differ."""
        items = [self._make_vault_item("File expense report", added_date="2026-04-30")]
        enriched = generate_vault_task_hashes(items, fallback_date="2026-05-10")
        self.assertNotEqual(enriched[0]["target_date"], "2026-05-10")
        self.assertEqual(enriched[0]["target_date"], "2026-04-30")

    # ── source_id encodes correct date ────────────────────────────────────

    def test_source_id_encodes_added_date_path(self):
        """source_id must embed the added_date Daily Note path, not today."""
        items = [self._make_vault_item("Review lease agreement", added_date="2026-05-03")]
        enriched = generate_vault_task_hashes(items, fallback_date="2026-05-10")
        self.assertIn("Calendar/Daily/2026/05/2026-05-03.md", enriched[0]["source_id"])
        self.assertNotIn("2026-05-10", enriched[0]["source_id"])

    def test_source_id_encodes_fallback_date_when_no_added_date(self):
        """source_id must embed the fallback date path when added_date is absent."""
        items = [self._make_vault_item("Return library books")]
        enriched = generate_vault_task_hashes(items, fallback_date="2026-05-10")
        self.assertIn("Calendar/Daily/2026/05/2026-05-10.md", enriched[0]["source_id"])

    # ── hash stability ────────────────────────────────────────────────────

    def test_hash_differs_by_date(self):
        """Same task name on different dates must produce different TaskHashes."""
        name = "Fold and store laundry"
        item_a = self._make_vault_item(name, added_date="2026-05-01")
        item_b = self._make_vault_item(name, added_date="2026-05-02")
        enriched_a = generate_vault_task_hashes([item_a], fallback_date="2026-05-10")
        enriched_b = generate_vault_task_hashes([item_b], fallback_date="2026-05-10")
        self.assertNotEqual(enriched_a[0]["task_hash"], enriched_b[0]["task_hash"])

    def test_hash_is_stable_for_same_date(self):
        """Same task name on the same date always produces the same TaskHash."""
        name = "Pay monthly rent"
        item = self._make_vault_item(name, added_date="2026-05-08")
        enriched_1 = generate_vault_task_hashes([item], fallback_date="2026-05-10")
        enriched_2 = generate_vault_task_hashes([item], fallback_date="2026-05-10")
        self.assertEqual(enriched_1[0]["task_hash"], enriched_2[0]["task_hash"])

    # ── multi-date grouping (integration with insert_tasks_into_daily_note) ─

    def test_tasks_on_different_dates_produce_different_target_dates(self):
        """Tasks with different added_dates must have distinct target_dates."""
        items = [
            self._make_vault_item("Schedule eye exam", added_date="2026-05-01"),
            self._make_vault_item("Buy coffee beans",   added_date="2026-05-03"),
            self._make_vault_item("Call landlord",      added_date="2026-05-03"),
        ]
        enriched = generate_vault_task_hashes(items, fallback_date="2026-05-10")
        dates = {t["target_date"] for t in enriched}
        self.assertEqual(dates, {"2026-05-01", "2026-05-03"})

    def test_tasks_grouped_by_target_date_write_to_correct_daily_note(self):
        """
        Integration: tasks are written to separate Daily Notes based on target_date.
        Verifies that a task created on 2026-05-01 does NOT appear in 2026-05-10.md.
        """
        from collections import defaultdict

        items = [
            self._make_vault_item("Schedule eye exam", added_date="2026-05-01"),
            self._make_vault_item("Buy coffee beans",  added_date="2026-05-10"),
        ]
        enriched = generate_vault_task_hashes(items, fallback_date="2026-05-10")

        # Group by target_date (mirrors main() logic)
        vault_by_date = defaultdict(list)
        for t in enriched:
            vault_by_date[t["target_date"]].append(t)

        with tempfile.TemporaryDirectory() as tmpdir:
            vault_root = Path(tmpdir)
            # Write each group to its Daily Note
            written_notes = {}
            for note_date, tasks_for_date in vault_by_date.items():
                note_path = vault_root / "Calendar" / "Daily" / note_date[:4] / note_date[5:7] / f"{note_date}.md"
                content = create_daily_note_content(note_date)
                updated = insert_tasks_into_daily_note(content, tasks_for_date)
                note_path.parent.mkdir(parents=True, exist_ok=True)
                note_path.write_text(updated, encoding="utf-8")
                written_notes[note_date] = updated

        # 2026-05-01 note contains eye exam but NOT coffee beans
        note_0501 = written_notes["2026-05-01"]
        self.assertIn("Schedule eye exam", note_0501)
        self.assertNotIn("Buy coffee beans", note_0501)

        # 2026-05-10 note contains coffee beans but NOT eye exam
        note_0510 = written_notes["2026-05-10"]
        self.assertIn("Buy coffee beans", note_0510)
        self.assertNotIn("Schedule eye exam", note_0510)

    def test_fallback_used_when_all_tasks_lack_added_date(self):
        """All tasks without added_date must go to the same fallback Daily Note."""
        items = [
            self._make_vault_item("Task Alpha"),
            self._make_vault_item("Task Beta"),
        ]
        enriched = generate_vault_task_hashes(items, fallback_date="2026-05-10")
        dates = {t["target_date"] for t in enriched}
        self.assertEqual(dates, {"2026-05-10"})

    def test_due_date_preserved_after_added_date_routing(self):
        """due_date must be preserved in enriched output regardless of added_date."""
        items = [self._make_vault_item("Submit tax return", added_date="2026-04-28", due_date="2026-05-31")]
        enriched = generate_vault_task_hashes(items, fallback_date="2026-05-10")
        self.assertEqual(enriched[0]["due_date"], "2026-05-31")
        self.assertEqual(enriched[0]["target_date"], "2026-04-28")


if __name__ == "__main__":
    unittest.main()
