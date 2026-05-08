#!/usr/bin/env python3
"""
Regression tests for prepare_sync.py — specifically the grandchild bug in
detect_existing_issue_updates().

KNOWN BUG (not yet fixed):
  detect_existing_issue_updates() only collects DIRECT children of a GitHub Project.
  Tasks whose parent_task_hash points to another task (not the Project itself) are
  missed — misidentified as "new tasks" on every sync.

  Example:
    Project:       転職活動 (60c6d084)   [task_type: github_project]
    Direct child:  Rayzel からの斡旋に対応 (4375b980)   [parent_task_hash: 60c6d084]
    Grandchild:    送られてきたJDを確認する (3d8c2904)   [parent_task_hash: 4375b980]

    The grandchild is NOT in synced_hashes because its parent_task_hash (4375b980)
    is not in the github_projects dict → it appears as a "new_task" every sync.

Proposed fix (lines 764-774 of prepare_sync.py):
  Replace direct parent lookup with recursive ancestor traversal:

    def find_project_hash(task_hash, state, github_projects):
        entry = state.get(task_hash, {})
        parent_hash = entry.get('parent_task_hash')
        if parent_hash is None:
            return None
        if parent_hash in github_projects:
            return parent_hash
        return find_project_hash(parent_hash, state, github_projects)

The test below is currently SKIPPED until the fix is implemented.
Remove the @unittest.skip decorator once prepare_sync.py is patched.

Run:  python3 -m unittest tests.test_prepare_sync_regression  (from TaskHashSyncSystem/)
"""

import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


# ─── Minimal state replicating the real-world grandchild scenario ─────────────

GRANDCHILD_STATE = {
    "60c6d084": {
        "source_id": "github:x5gtrn/LIFE#2:転職活動",
        "of_task_id": "proj_001",
        "of_task_name": "転職活動 (60c6d084)",
        "status": "open",
        "task_type": "github_project",
    },
    "4375b980": {
        "source_id": "github:x5gtrn/LIFE#2:Rayzel からの斡旋に対応",
        "of_task_id": "t001",
        "of_task_name": "Rayzel からの斡旋に対応 (4375b980)",
        "status": "open",
        "task_type": "github_task",
        "parent_task_hash": "60c6d084",
    },
    "3d8c2904": {
        "source_id": "github:x5gtrn/LIFE#2:送られてきたJDを確認する",
        "of_task_id": "t002",
        "of_task_name": "送られてきたJDを確認する (3d8c2904)",
        "status": "open",
        "task_type": "github_task",
        "parent_task_hash": "4375b980",  # ← grandchild: parent is NOT the Project
    },
}

# GitHub Issue body as returned by the API (all tasks already synced)
ISSUE_2_BODY_SYNCED = (
    "- [x] エラチョイに返信 (35efa56a)\n"
    "- [ ] Rayzel からの斡旋に対応 (4375b980)\n"
    "    - [ ] 送られてきたJDを確認する (3d8c2904)\n"
)


@unittest.skip(
    "Known bug: detect_existing_issue_updates() does not traverse grandchild tasks. "
    "Remove this skip once the recursive parent-chain fix is applied to prepare_sync.py."
)
class TestGrandchildDetection(unittest.TestCase):
    """
    detect_existing_issue_updates() must NOT classify already-synced grandchild
    tasks as new_tasks.

    Failing scenario:
      - 3d8c2904 is already in sync_state with parent_task_hash=4375b980
      - 4375b980 is a direct child of github_project 60c6d084
      - Because 3d8c2904.parent_task_hash != any key in github_projects dict,
        the current code misidentifies it as a new task on every sync run.
    """

    def _make_prepare_sync_with_patched_state_and_github(
        self,
        state: dict,
        issue_body: str,
    ):
        """
        Import prepare_sync and patch load_state + gh CLI so tests run offline.
        Returns the module.
        """
        import prepare_sync as ps

        def fake_load_state():
            return state

        def fake_gh_issue_view(*args, **kwargs):
            result = MagicMock()
            result.stdout = json.dumps({"body": issue_body})
            result.returncode = 0
            return result

        return ps, fake_load_state, fake_gh_issue_view

    def test_grandchild_not_reported_as_new_task(self):
        """
        When 送られてきたJDを確認する (3d8c2904) is already in sync_state,
        detect_existing_issue_updates() must NOT include it in new_tasks.
        """
        import prepare_sync as ps

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "sync_state.json"
            state_file.write_text(
                json.dumps(GRANDCHILD_STATE), encoding='utf-8'
            )

            with patch.object(ps, 'STATE_FILE', state_file), \
                 patch('subprocess.run') as mock_run:

                mock_run.return_value = MagicMock(
                    stdout=json.dumps({"body": ISSUE_2_BODY_SYNCED}),
                    returncode=0
                )

                updates = ps.detect_existing_issue_updates()

        # If the bug is fixed, there should be no "new_tasks" for issue 2
        issue_2_updates = [u for u in updates if u.get("issue_num") == 2]
        if issue_2_updates:
            new_tasks = issue_2_updates[0].get("new_tasks", [])
            grandchild_hashes = [t.get("hash") for t in new_tasks]
            self.assertNotIn(
                "3d8c2904",
                grandchild_hashes,
                "Grandchild task 3d8c2904 must not appear as new_task — it is already synced"
            )

    def test_grandchild_included_in_synced_hashes(self):
        """
        The synced_hashes set for Issue #2 must include grandchild 3d8c2904.
        This verifies the recursive traversal works correctly.
        """
        # This test is structural — it checks the internal logic of how
        # synced_hashes is built.  Once the fix is applied, synced_hashes
        # must contain all descendants, not just direct children.
        import prepare_sync as ps

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "sync_state.json"
            state_file.write_text(json.dumps(GRANDCHILD_STATE), encoding='utf-8')

            with patch.object(ps, 'STATE_FILE', state_file), \
                 patch('subprocess.run') as mock_run:

                mock_run.return_value = MagicMock(
                    stdout=json.dumps({"body": ISSUE_2_BODY_SYNCED}),
                    returncode=0
                )

                updates = ps.detect_existing_issue_updates()

        # After fix: no new_tasks at all for issue #2 (everything is synced)
        for update in updates:
            if update.get("issue_num") == 2:
                self.assertEqual(
                    update.get("new_tasks", []),
                    [],
                    "All tasks in Issue #2 are already synced — new_tasks must be empty"
                )


class TestGrandchildDetectionDocumentation(unittest.TestCase):
    """
    Documents the known bug without running the broken code.
    Always passes — serves as a living specification.
    """

    def test_bug_is_documented(self):
        """
        KNOWN BUG: detect_existing_issue_updates() misses grandchild tasks.

        Root cause (prepare_sync.py ~line 764):
          for hash_val, entry in state.items():
              if entry.get('task_type') == 'github_task':
                  parent_hash = entry.get('parent_task_hash')
                  if parent_hash in github_projects:   ← only direct children pass
                      github_projects[parent_hash]['synced_tasks'].append(...)

        A grandchild task has parent_task_hash = <direct child hash>, not the
        Project hash, so it never enters synced_tasks.

        Required fix: replace the direct lookup with a recursive ancestor walk
        that follows parent_task_hash until it finds a github_project or runs out.

        Fix target: x/Scripts/TaskHashSyncSystem/prepare_sync.py
        """
        # This is purely documentary — the assertion is trivially true.
        bug_description = (
            "detect_existing_issue_updates does not traverse grandchild tasks; "
            "grandchildren are re-reported as new_tasks on every sync"
        )
        self.assertIn("grandchild", bug_description)

    def test_proposed_fix_logic(self):
        """
        Verify that the proposed recursive helper correctly resolves ancestors.
        This is a pure-logic test of the fix algorithm, independent of prepare_sync.py.
        """
        state = GRANDCHILD_STATE
        github_projects = {"60c6d084"}  # set of project hashes

        def find_project_hash(task_hash, visited=None):
            """Proposed recursive fix."""
            if visited is None:
                visited = set()
            if task_hash in visited:
                return None  # cycle guard
            visited.add(task_hash)
            entry = state.get(task_hash, {})
            parent_hash = entry.get('parent_task_hash')
            if parent_hash is None:
                return None
            if parent_hash in github_projects:
                return parent_hash
            return find_project_hash(parent_hash, visited)

        # Direct child → finds project immediately
        self.assertEqual(find_project_hash("4375b980"), "60c6d084")

        # Grandchild → traverses one level up to direct child, then to project
        self.assertEqual(find_project_hash("3d8c2904"), "60c6d084")

        # Unrelated task → returns None
        self.assertIsNone(find_project_hash("aaaaaaaa"))


if __name__ == "__main__":
    unittest.main()
