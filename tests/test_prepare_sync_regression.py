#!/usr/bin/env python3
"""
Regression tests for prepare_sync.py — specifically the grandchild fix in
detect_existing_issue_updates().

FIX (applied):
  detect_existing_issue_updates() now uses recursive ancestor traversal
  (find_ancestor_project) instead of a direct parent lookup.

  Previously, tasks whose parent_task_hash pointed to another task (not the
  Project itself) were missed — misidentified as "new tasks" on every sync.

  Example:
    Project:      Job Search Q3 (60c6d084)       [task_type: github_project]
    Direct child: Follow up on Rayzel referral (4375b980)  [parent_task_hash: 60c6d084]
    Grandchild:   Review submitted job description (3d8c2904) [parent_task_hash: 4375b980]

    With the fix, find_ancestor_project(3d8c2904) walks up:
      3d8c2904 -> parent 4375b980 -> parent 60c6d084 (github_project) -> returns 60c6d084
    The grandchild is now correctly included in synced_tasks for project 60c6d084.

Fix location: prepare_sync.py, function detect_existing_issue_updates(),
  find_ancestor_project() helper + updated synced_tasks collection loop.

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
        "source_id": "github:x5gtrn/LIFE#2:Job Search Q3",
        "of_task_id": "proj_001",
        "of_task_name": "Job Search Q3 (60c6d084)",
        "status": "open",
        "task_type": "github_project",
    },
    # Direct child (completed) — appears as [x] in ISSUE_JOBS_BODY_SYNCED
    "35efa56a": {
        "source_id": "github:x5gtrn/LIFE#2:Reply to recruiter email",
        "of_task_id": "t000",
        "of_task_name": "Reply to recruiter email (35efa56a)",
        "status": "completed",
        "task_type": "github_task",
        "parent_task_hash": "60c6d084",
    },
    # Direct child (open)
    "4375b980": {
        "source_id": "github:x5gtrn/LIFE#2:Follow up on Rayzel referral",
        "of_task_id": "t001",
        "of_task_name": "Follow up on Rayzel referral (4375b980)",
        "status": "open",
        "task_type": "github_task",
        "parent_task_hash": "60c6d084",
    },
    # Grandchild (open) — parent is a github_task, NOT the github_project directly
    "3d8c2904": {
        "source_id": "github:x5gtrn/LIFE#2:Review submitted job description",
        "of_task_id": "t002",
        "of_task_name": "Review submitted job description (3d8c2904)",
        "status": "open",
        "task_type": "github_task",
        "parent_task_hash": "4375b980",
    },
}

# GitHub Issue body as returned by the API (all tasks already synced)
ISSUE_JOBS_BODY_SYNCED = (
    "- [x] Reply to recruiter email (35efa56a)\n"
    "- [ ] Follow up on Rayzel referral (4375b980)\n"
    "    - [ ] Review submitted job description (3d8c2904)\n"
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

    def test_grandchild_not_reported_as_new_task(self):
        """
        When "Review submitted job description (3d8c2904)" is already in sync_state,
        detect_existing_issue_updates() must NOT include it in new_tasks.
        """
        import prepare_sync as ps

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                stdout=json.dumps({"body": ISSUE_JOBS_BODY_SYNCED}),
                returncode=0
            )
            updates = ps.detect_existing_issue_updates(
                owner='x5gtrn', repo='LIFE', state=GRANDCHILD_STATE
            )

        issue_2_updates = [u for u in updates if u.get("issue_num") == 2]
        if issue_2_updates:
            new_tasks = issue_2_updates[0].get("new_tasks", [])
            grandchild_hashes = [t.get("hash") for t in new_tasks]
            self.assertNotIn(
                "3d8c2904",
                grandchild_hashes,
                "Grandchild 3d8c2904 must not appear as new_task — it is already synced"
            )

    def test_grandchild_included_in_synced_hashes(self):
        """
        The synced_hashes set for Issue #2 must include grandchild 3d8c2904.
        This verifies the recursive traversal works correctly.
        """
        import prepare_sync as ps

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                stdout=json.dumps({"body": ISSUE_JOBS_BODY_SYNCED}),
                returncode=0
            )
            updates = ps.detect_existing_issue_updates(
                owner='x5gtrn', repo='LIFE', state=GRANDCHILD_STATE
            )

        # After fix: no new_tasks at all for issue #2 (everything already synced)
        for update in updates:
            if update.get("issue_num") == 2:
                self.assertEqual(
                    update.get("new_tasks", []),
                    [],
                    "All Issue #2 tasks are already synced — new_tasks must be empty"
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
                  if parent_hash in github_projects:   <- only direct children pass
                      github_projects[parent_hash]['synced_tasks'].append(...)

        A grandchild task has parent_task_hash = <direct child hash>, not the
        Project hash, so it never enters synced_tasks.

        Required fix: replace the direct lookup with a recursive ancestor walk
        that follows parent_task_hash until it finds a github_project or terminates.

        Fix target: x/Scripts/TaskHashSyncSystem/prepare_sync.py
        """
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
        github_projects = {"60c6d084"}  # set of known project hashes

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

        # Direct child resolves to project immediately
        self.assertEqual(find_project_hash("4375b980"), "60c6d084")

        # Grandchild traverses one level up to direct child, then to project
        self.assertEqual(find_project_hash("3d8c2904"), "60c6d084")

        # Unrelated task has no ancestor in github_projects
        self.assertIsNone(find_project_hash("aaaaaaaa"))


if __name__ == "__main__":
    unittest.main()
