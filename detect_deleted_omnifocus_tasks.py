#!/usr/bin/env python3
"""
Detect Deleted OmniFocus Tasks — Clean up all locations

PURPOSE:
  Detect TaskHash-bearing tasks that EXIST in sync_state.json but NO LONGER
  EXIST in OmniFocus (user manually deleted them).

  For each deleted task, CASCADE the deletion to:
  1. GitHub Issue (if applicable)
  2. Vault Daily Notes
  3. sync_state.json

LOGIC:
  for each task in sync_state.json:
    if task has TaskHash AND is not found in OmniFocus:
      → Mark for deletion
      → Delete from GitHub Issue (if source_id is github:...)
      → Delete from Vault (if source_id is vault:...)
      → Remove from sync_state.json

USAGE:
  python3 detect_deleted_omnifocus_tasks.py --dump-file omnifocus_dump.txt [--dry-run] [--verbose]

AUTOMATION:
  Run after scan_omnifocus_inbox.py in STEP 3 of sync workflow.
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime

# State file location
SCRIPT_DIR = Path(__file__).parent
STATE_FILE = SCRIPT_DIR / "sync_state.json"
VAULT_ROOT = Path('/Users/x5gtrn/Library/Mobile Documents/iCloud~md~obsidian/Documents/LIFE')
REPO = "x5gtrn/LIFE"


def load_state() -> Dict[str, Any]:
    """Load sync state from JSON file."""
    if STATE_FILE.exists():
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_state(state: Dict[str, Any]) -> None:
    """Save sync state to JSON file."""
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def parse_omnifocus_dump(dump_file: str) -> List[str]:
    """
    Parse OmniFocus dump file and extract all task names (with hashes).

    Format:
      Project: Name
        - Task Name (hash)
      INBOX
        - Task Name (hash)

    Returns:
        List of task names found in OmniFocus
    """
    omnifocus_tasks = []

    try:
        with open(dump_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Extract all task names (including hashes)
        # Pattern: lines starting with "- " followed by task name
        pattern = r'^\s+-\s+(.+?)(?:\s*\n|$)'
        matches = re.findall(pattern, content, re.MULTILINE)

        for match in matches:
            task_name = match.strip()
            if task_name and not task_name.startswith('Task'):  # Skip headers
                omnifocus_tasks.append(task_name)

        return omnifocus_tasks
    except Exception as e:
        print(f"Error parsing OmniFocus dump: {e}")
        return []


def find_deleted_tasks(state: Dict[str, Any], omnifocus_tasks: List[str]) -> Dict[str, Dict]:
    """
    Find tasks that exist in sync_state but NOT in OmniFocus.

    Args:
        state: sync_state.json content
        omnifocus_tasks: List of task names from OmniFocus dump

    Returns:
        Dict mapping hash → task_info for deleted tasks
    """
    deleted_tasks = {}

    # Build set of OmniFocus task names (with and without hashes)
    of_task_set = set(omnifocus_tasks)

    # Check each task in sync_state
    for task_hash, task_info in state.items():
        of_task_name = task_info.get('of_task_name', '')

        # Skip tasks without TaskHash (not managed by sync system)
        if not of_task_name or not task_info.get('of_task_name', '').endswith(')'):
            continue

        # Check if task exists in OmniFocus
        if of_task_name not in of_task_set:
            # Task not found in OmniFocus → marked for deletion
            deleted_tasks[task_hash] = task_info

    return deleted_tasks


def delete_from_github_issue(owner: str, repo: str, issue_num: int, task_hash: str, dry_run: bool = False) -> bool:
    """
    Delete a task from GitHub Issue using update_issue_body.py.

    Args:
        owner: GitHub owner
        repo: GitHub repo
        issue_num: Issue number
        task_hash: Task hash to remove
        dry_run: If True, don't make changes

    Returns:
        True if successful, False otherwise
    """
    try:
        cmd = [
            'python3',
            str(SCRIPT_DIR / 'update_issue_body.py'),
            '--issue', str(issue_num),
            '--remove-task', task_hash,
        ]

        if dry_run:
            cmd.append('--dry-run')

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"  ✓ GitHub Issue #{issue_num}: Task ({task_hash}) deleted")
        return True

    except subprocess.CalledProcessError as e:
        print(f"  ✗ Error deleting from GitHub Issue #{issue_num}: {e.stderr}")
        return False
    except Exception as e:
        print(f"  ✗ Error deleting from GitHub Issue: {e}")
        return False


def delete_from_vault_file(vault_path: Path, task_name: str, task_hash: str, dry_run: bool = False) -> bool:
    """
    Delete a task line from Vault markdown file.

    Args:
        vault_path: Path relative to vault root
        task_name: Task name (without hash for matching)
        task_hash: Task hash for verification
        dry_run: If True, don't make changes

    Returns:
        True if successful, False otherwise
    """
    full_path = VAULT_ROOT / vault_path

    try:
        if not full_path.exists():
            print(f"  ⚠️  Vault file not found: {vault_path}")
            return False

        # Read file
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Pattern to match task line with this hash
        # Handles: "- [ ] Task (hash)" or "- [x] Task (hash)" with optional metadata
        pattern = rf'^\s*-\s+\[[x\s]\]\s+.+?\s+\({task_hash}\).*?$'

        # Check if task exists
        if not re.search(pattern, content, re.MULTILINE):
            print(f"  ⚠️  Task ({task_hash}) not found in {vault_path}")
            return False

        if dry_run:
            print(f"  [DRY RUN] Would delete from {vault_path}")
            return True

        # Remove the task line
        new_content = re.sub(pattern + '\n?', '', content, flags=re.MULTILINE)

        # Write back
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        print(f"  ✓ Vault file: Task ({task_hash}) deleted from {vault_path}")
        return True

    except Exception as e:
        print(f"  ✗ Error deleting from Vault: {e}")
        return False


def cascade_delete(deleted_tasks: Dict[str, Dict], state: Dict[str, Any], dry_run: bool = False, verbose: bool = False) -> Tuple[int, int]:
    """
    Cascade delete tasks from GitHub and Vault when deleted from OmniFocus.

    Args:
        deleted_tasks: Dict of tasks that were deleted from OmniFocus
        state: Full sync_state content
        dry_run: If True, don't make changes
        verbose: If True, show detailed information

    Returns:
        Tuple of (successful_deletions, failed_deletions)
    """
    successful = 0
    failed = 0

    for task_hash, task_info in deleted_tasks.items():
        source_id = task_info.get('source_id', '')
        of_task_name = task_info.get('of_task_name', '')

        if verbose:
            print(f"\n→ Cascade delete: {of_task_name}")
            print(f"  Source: {source_id}")
            print(f"  Hash: {task_hash}")

        # Remove hash from task name to get original name
        original_name = of_task_name
        if of_task_name.endswith(f' ({task_hash})'):
            original_name = of_task_name[:-len(task_hash)-3]

        deletion_success = True

        # Handle GitHub Issue deletion
        if source_id.startswith('github:'):
            match = re.match(r'github:([^/]+)/([^#]+)#(\d+):(.+)', source_id)
            if match:
                owner, repo, issue_num, _ = match.groups()
                success = delete_from_github_issue(owner, repo, int(issue_num), task_hash, dry_run)
                if not success:
                    deletion_success = False
            else:
                print(f"  ✗ Invalid GitHub source_id format: {source_id}")
                deletion_success = False

        # Handle Vault deletion
        elif source_id.startswith('vault:'):
            match = re.match(r'vault:([^:]+):(.+)', source_id)
            if match:
                vault_path_str, _ = match.groups()
                vault_path = Path(vault_path_str)
                success = delete_from_vault_file(vault_path, original_name, task_hash, dry_run)
                if not success:
                    deletion_success = False
            else:
                print(f"  ✗ Invalid Vault source_id format: {source_id}")
                deletion_success = False

        if deletion_success:
            successful += 1
        else:
            failed += 1

    return successful, failed


def update_sync_state_deletion(deleted_tasks: Dict[str, Dict], state: Dict[str, Any], dry_run: bool = False) -> None:
    """
    Remove deleted tasks from sync_state.json.

    Args:
        deleted_tasks: Dict of tasks to remove
        state: Full sync_state content
        dry_run: If True, don't make changes
    """
    if dry_run:
        print(f"\n[DRY RUN] Would remove {len(deleted_tasks)} task(s) from sync_state.json")
        return

    for task_hash in deleted_tasks.keys():
        if task_hash in state:
            del state[task_hash]

    save_state(state)
    print(f"\n✓ Removed {len(deleted_tasks)} task(s) from sync_state.json")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Detect and cascade-delete tasks that were removed from OmniFocus"
    )
    parser.add_argument(
        '--dump-file',
        type=str,
        required=True,
        help='OmniFocus dump file (from dump_database)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be deleted without making changes'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed information'
    )

    args = parser.parse_args()

    # Load state
    state = load_state()

    # Parse OmniFocus dump
    print("=" * 70)
    print("DETECTING OMNIFOCUS DELETIONS")
    print("=" * 70 + "\n")

    omnifocus_tasks = parse_omnifocus_dump(args.dump_file)
    print(f"✓ Found {len(omnifocus_tasks)} tasks in OmniFocus")

    # Find deleted tasks
    deleted_tasks = find_deleted_tasks(state, omnifocus_tasks)

    if not deleted_tasks:
        print("\n✓ No tasks found that were deleted from OmniFocus")
        return

    print(f"\n⚠️  Found {len(deleted_tasks)} task(s) that were deleted from OmniFocus:\n")
    for task_hash, task_info in deleted_tasks.items():
        print(f"  • {task_info.get('of_task_name', 'Unknown')} ({task_hash})")
        print(f"    Source: {task_info.get('source_id', 'unknown')}")

    # Cascade delete
    print("\n" + "-" * 70)
    print("CASCADE DELETION")
    print("-" * 70 + "\n")

    successful, failed = cascade_delete(deleted_tasks, state, args.dry_run, args.verbose)

    # Update sync_state
    if successful > 0 or failed == 0:
        update_sync_state_deletion(deleted_tasks, state, args.dry_run)

    # Summary
    print("\n" + "=" * 70)
    print(f"DELETION COMPLETE")
    print("=" * 70)
    print(f"✓ Successfully deleted: {successful}")
    print(f"✗ Failed to delete: {failed}")

    if args.dry_run:
        print("(Dry run - no changes made)")


if __name__ == "__main__":
    main()
