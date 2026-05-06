#!/usr/bin/env python3
"""
Reverse Sync: OmniFocus → GitHub/Vault

Reflects completed tasks from OmniFocus back to their original sources.
Updates checkboxes in GitHub Issues and Vault markdown files.
"""

import json
import subprocess
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any

from task_hash import extract_hash

# State file location
SCRIPT_DIR = Path(__file__).parent
STATE_FILE = SCRIPT_DIR / "sync_state.json"
VAULT_ROOT = Path('/Users/x5gtrn/Library/Mobile Documents/iCloud~md~obsidian/Documents/LIFE')


def load_state() -> Dict[str, Any]:
    """Load sync state from JSON file."""
    if STATE_FILE.exists():
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_state(state: Dict[str, Any]) -> None:
    """Save sync state to JSON file."""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def get_completed_tasks_from_omnifocus() -> List[str]:
    """
    Get completed task names from OmniFocus.

    This is a stub - in actual use, this would be called via:
    - OmniFocus MCP filter_tasks with taskStatus=['Completed']
    - Or by asking Claude to run the MCP query

    Returns:
        List of completed task names (should include hashes)
    """
    # This would be populated by Claude via MCP
    # For now, return empty - caller will provide this
    return []


def find_completed_tasks_in_state(state: Dict[str, Any], omnifocus_task_data: List) -> Dict[str, Dict]:
    """
    Find completed tasks by comparing OmniFocus task data with sync_state.

    Args:
        state: sync_state.json content
        omnifocus_task_data: List of tasks from OmniFocus (can be strings or dicts with hash/name/project/due_date)

    Returns:
        Dict mapping hash to task info (enhanced with project and due_date info if available)
    """
    completed = {}

    # Build a lookup map: hash -> omnifocus_task
    omnifocus_tasks_map = {}
    for task in omnifocus_task_data:
        if isinstance(task, dict):
            # New format: {"hash": "...", "name": "...", "project": "...", "due_date": "..."}
            hash_val = task.get('hash') or task.get('of_task_name', '').split('(')[-1].rstrip(')')
            omnifocus_tasks_map[hash_val] = task
        elif isinstance(task, str):
            # Old format: "TaskName (hash)"
            # Extract hash from end of string
            if '(' in task and task.endswith(')'):
                hash_val = task.split('(')[-1].rstrip(')')
                omnifocus_tasks_map[hash_val] = {'name': task, 'project': None}

    # Find matching tasks in state
    for hash_val, task_info in state.items():
        if hash_val in omnifocus_tasks_map:
            # Task is completed, add project and due_date info if available
            completed[hash_val] = task_info
            omnifocus_task = omnifocus_tasks_map[hash_val]

            if isinstance(omnifocus_task, dict):
                if 'project' in omnifocus_task:
                    completed[hash_val]['project_name'] = omnifocus_task['project']
                if 'due_date' in omnifocus_task:
                    completed[hash_val]['due_date_from_of'] = omnifocus_task['due_date']

    return completed


def update_github_issue_checkbox(
    owner: str,
    repo: str,
    issue_num: int,
    task_name: str,
    completed_date: str = None,
    due_date: str = None,
    dry_run: bool = False
) -> bool:
    """
    Update a checkbox in a GitHub issue from unchecked to checked.

    Args:
        owner: GitHub owner
        repo: GitHub repo
        issue_num: Issue number
        task_name: Task name (without hash)
        completed_date: Completion date in YYYY-MM-DD format (optional)
        due_date: Due date in YYYY-MM-DD format (optional)
        dry_run: If True, only show what would be done

    Returns:
        True if successful, False otherwise
    """
    if dry_run:
        print(f"  [DRY RUN] Would update GitHub Issue #{issue_num}")
        print(f"            Task: {task_name}")
        if due_date:
            print(f"            Due date: 📅 {due_date}")
        if completed_date:
            print(f"            Completion date: ✅ {completed_date}")
        return True

    try:
        # Get current issue
        cmd_get = [
            'gh', 'issue', 'view', str(issue_num),
            '--repo', f'{owner}/{repo}',
            '--json', 'body'
        ]
        result_get = subprocess.run(cmd_get, capture_output=True, text=True, check=True)
        issue_data = json.loads(result_get.stdout)
        body = issue_data['body']

        # Pattern to match task: both unchecked and checked boxes
        # Handles: "- [ ] TASK" or "- [x] TASK" with optional leading whitespace
        # Also handle task names that already have hashes appended (e.g., "TASK (abc123)")
        # Pattern allows for optional completion date and trailing whitespace
        pattern = rf'^\s*- \[[x\s]\]\s*{re.escape(task_name)}(?:\s*\([a-f0-9]+\))?(?:\s*✅\s*\d{{4}}-\d{{2}}-\d{{2}})?(?:\s*)$'

        # Get the matched text
        match = re.search(pattern, body, re.MULTILINE)
        if match:
            matched_text = match.group(0)
            # Replace [ ] with [x] if needed (in case it was unchecked)
            updated_text = matched_text.replace('[ ]', '[x]')

            # Append completion date if provided and not already present
            if completed_date and not re.search(r'✅\s*\d{4}-\d{2}-\d{2}', updated_text):
                updated_text += f' ✅ {completed_date}'

            new_body = re.sub(pattern, updated_text, body)
        else:
            new_body = body

        # Only update if something changed
        if new_body == body:
            print(f"  ✗ Task '{task_name}' not found in issue #{issue_num}")
            return False

        # Update issue
        cmd_update = [
            'gh', 'issue', 'edit', str(issue_num),
            '--repo', f'{owner}/{repo}',
            '--body', new_body
        ]
        subprocess.run(cmd_update, capture_output=True, text=True, check=True)
        if completed_date:
            print(f"  ✓ Updated GitHub Issue #{issue_num}: {task_name} ✅ {completed_date}")
        else:
            print(f"  ✓ Updated GitHub Issue #{issue_num}: {task_name}")
        return True

    except subprocess.CalledProcessError as e:
        print(f"  ✗ Error updating GitHub: {e.stderr}")
        return False


def update_vault_file_checkbox(
    vault_path: Path,
    task_name: str,
    completed_date: str = None,
    due_date: str = None,
    dry_run: bool = False
) -> bool:
    """
    Update a checkbox in a Vault markdown file from unchecked to checked.

    Args:
        vault_path: Path relative to vault root
        task_name: Task name (without hash)
        completed_date: Completion date in YYYY-MM-DD format (optional)
        due_date: Due date in YYYY-MM-DD format (optional, will update date in file)
        dry_run: If True, only show what would be done

    Returns:
        True if successful, False otherwise
    """
    full_path = VAULT_ROOT / vault_path

    if dry_run:
        print(f"  [DRY RUN] Would update Vault file: {vault_path}")
        print(f"            Task: {task_name}")
        if due_date:
            print(f"            Due date: 📅 {due_date}")
        if completed_date:
            print(f"            Completion date: ✅ {completed_date}")
        return True

    try:
        # Read file
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Pattern to match task: both unchecked and checked boxes
        # Handles: "- [ ] TASK" or "- [x] TASK" with optional leading whitespace (tabs/spaces)
        # Also handle task names that already have hashes appended (e.g., "TASK (abc123)")
        # Pattern allows for optional due date and completion date and trailing whitespace
        pattern = rf'^\s*- \[[x\s]\]\s*{re.escape(task_name)}(?:\s*\([a-f0-9]+\))?(?:\s*📅\s*\d{{4}}-\d{{2}}-\d{{2}})?(?:\s*✅\s*\d{{4}}-\d{{2}}-\d{{2}})?(?:\s*)$'

        # Get the matched text
        match = re.search(pattern, content, re.MULTILINE)
        if match:
            matched_text = match.group(0)

            # Check if completion date is already present
            has_completion_date = re.search(r'✅\s*\d{4}-\d{2}-\d{2}', matched_text)

            # Replace [ ] with [x] if needed (in case it was unchecked)
            updated_text = matched_text.replace('[ ]', '[x]')

            # Handle due date: update/add/remove as needed
            # First, remove any existing due date
            updated_text = re.sub(r'\s*📅\s*\d{4}-\d{2}-\d{2}', '', updated_text)

            # Add new due date if provided (before completion date)
            if due_date:
                # Insert due date before completion date (if present) or before trailing whitespace
                if re.search(r'\s*✅\s*\d{4}-\d{2}-\d{2}', updated_text):
                    # Has completion date, insert due date before it
                    updated_text = re.sub(r'(\s+✅)', f' 📅 {due_date}\\1', updated_text)
                else:
                    # No completion date, add due date at end before any trailing space
                    updated_text = updated_text.rstrip() + f' 📅 {due_date}'

            # Append completion date if provided and not already present
            if completed_date and not has_completion_date:
                updated_text = updated_text.rstrip() + f' ✅ {completed_date}'

            new_content = re.sub(pattern, updated_text, content, flags=re.MULTILINE)
        else:
            new_content = content
            matched_text = None

        # Only update if something changed (or task found but already has correct dates)
        if new_content == content:
            if matched_text:
                # Task found, check if it already has the correct dates
                has_correct_due_date = (due_date and re.search(rf'📅\s*{re.escape(due_date)}', matched_text)) or \
                                       (not due_date and not re.search(r'📅\s*\d{4}-\d{2}-\d{2}', matched_text))
                if has_correct_due_date:
                    # Task found and already has correct dates - this is success
                    print(f"  ✓ Already synced: {vault_path}")
                    if due_date:
                        print(f"      Due: 📅 {due_date}")
                    if completed_date:
                        print(f"      Completed: ✅ {completed_date}")
                    return True

            # Task truly not found
            print(f"  ✗ Task '{task_name}' not found in {vault_path}")
            return False

        # Write file
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        print(f"  ✓ Updated Vault file: {vault_path}")
        if due_date:
            print(f"      Due: 📅 {due_date}")
        if completed_date:
            print(f"      Completed: ✅ {completed_date}")
        return True

    except Exception as e:
        print(f"  ✗ Error updating Vault: {e}")
        return False


def project_has_task_hash(project_name: str, state: Dict[str, Any]) -> bool:
    """
    Check if a project has a TaskHash (i.e., was created from GitHub Issue).

    Args:
        project_name: Name of the project (e.g., "Later", "Someday")
        state: sync_state.json content

    Returns:
        True if project has a TaskHash, False otherwise
    """
    # Look for a project task (task_type == "project") with matching name
    for hash_val, task_info in state.items():
        if task_info.get('task_type') == 'project':
            of_task_name = task_info.get('of_task_name', '')
            # Extract project name from task name (remove hash)
            if of_task_name.endswith(f' ({hash_val})'):
                name_without_hash = of_task_name[:-len(hash_val)-3]
                if name_without_hash == project_name:
                    return True
    return False


def reflect_completions(
    completed_tasks: Dict[str, Dict],
    state: Dict[str, Any],
    dry_run: bool = False,
    verbose: bool = False
) -> Tuple[int, int]:
    """
    Reflect completed tasks back to GitHub and Vault.

    Args:
        completed_tasks: Dict of completed tasks from sync_state
        state: sync_state.json content (for project hash checking)
        dry_run: If True, only show what would be done
        verbose: If True, show detailed information

    Returns:
        Tuple of (successful_updates, failed_updates)
    """
    successful = 0
    failed = 0

    for hash_val, task_info in completed_tasks.items():
        source_id = task_info.get('source_id', '')
        of_task_name = task_info.get('of_task_name', '')
        completed_at = task_info.get('completed_at', '')
        project_name = task_info.get('project_name')
        due_date_from_of = task_info.get('due_date_from_of')

        # Extract date from completed_at ISO timestamp (format: YYYY-MM-DDTHH:MM:SS.ffffff)
        # Fall back to today's date if completed_at is missing from sync_state
        if not completed_at:
            completed_at = datetime.now().isoformat()
        completed_date = completed_at.split('T')[0] if 'T' in completed_at else completed_at[:10]

        # Remove hash from task name to get original name
        original_name = of_task_name
        if of_task_name.endswith(f' ({hash_val})'):
            original_name = of_task_name[:-len(hash_val)-3]

        if verbose:
            print(f"\n→ Reflecting completion: {of_task_name}")
            print(f"  Source: {source_id}")
            if project_name:
                print(f"  Project: {project_name}")
            if due_date_from_of:
                print(f"  Due: 📅 {due_date_from_of}")
            if completed_date:
                print(f"  Completed: {completed_date}")

        # Determine source type and update accordingly
        # Special case: TaskHash-less projects (like "Later") → treat as Vault/Inbox
        if project_name and not project_has_task_hash(project_name, state):
            if verbose:
                print(f"  → Treating as Vault task (TaskHash-less project)")
            # Find vault source for this task (may not exist if not originally from vault)
            vault_source = None
            for hash_in_state, task_in_state in state.items():
                if hash_in_state == hash_val:
                    src_id = task_in_state.get('source_id', '')
                    if src_id.startswith('vault:'):
                        vault_source = src_id
                    break

            if vault_source:
                match = re.match(r'vault:([^:]+):(.+)', vault_source)
                if match:
                    vault_path_str, _ = match.groups()
                    vault_path = Path(vault_path_str)
                    success = update_vault_file_checkbox(
                        vault_path, original_name, completed_date, due_date_from_of, dry_run
                    )
                    if success:
                        successful += 1
                    else:
                        failed += 1
            else:
                if verbose:
                    print(f"  ✗ No vault source found for TaskHash-less project task")
                failed += 1

        elif source_id.startswith('github:'):
            # Parse GitHub source_id: github:owner/repo#issue:task_name
            match = re.match(r'github:([^/]+)/([^#]+)#(\d+):(.+)', source_id)
            if match:
                owner, repo, issue_num, _ = match.groups()
                success = update_github_issue_checkbox(
                    owner, repo, int(issue_num), original_name, completed_date, due_date_from_of, dry_run
                )
                if success:
                    successful += 1
                else:
                    failed += 1

        elif source_id.startswith('vault:'):
            # Parse Vault source_id: vault:relative/path/file.md:task_name
            match = re.match(r'vault:([^:]+):(.+)', source_id)
            if match:
                vault_path_str, _ = match.groups()
                vault_path = Path(vault_path_str)
                success = update_vault_file_checkbox(
                    vault_path, original_name, completed_date, due_date_from_of, dry_run
                )
                if success:
                    successful += 1
                else:
                    failed += 1

    return successful, failed


def update_sync_state_completion(
    completed_tasks: Dict[str, Dict],
    state: Dict[str, Any],
    dry_run: bool = False
) -> None:
    """
    Update sync_state.json to mark tasks as completed.

    Args:
        completed_tasks: Dict of completed tasks
        state: Full sync_state content
        dry_run: If True, don't save
    """
    for hash_val in completed_tasks.keys():
        if hash_val in state:
            state[hash_val]['status'] = 'completed'
            state[hash_val]['completed_at'] = datetime.now().isoformat()

    if not dry_run:
        save_state(state)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Reverse sync: Reflect completed OmniFocus tasks to GitHub/Vault"
    )
    parser.add_argument(
        '--completed-tasks',
        type=str,
        help='JSON file with completed task names (from OmniFocus MCP)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be updated without making changes'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed information'
    )

    args = parser.parse_args()

    state = load_state()

    # Get completed tasks
    completed_task_names = []
    if args.completed_tasks:
        try:
            with open(args.completed_tasks, 'r') as f:
                data = json.load(f)
            # Accept multiple formats:
            #   {"completed_tasks": ["Task (hash)", ...]}
            #   [{"name": "Task (hash)", ...}, ...]
            #   ["Task (hash)", ...]
            if isinstance(data, dict):
                completed_task_names = data.get('completed_tasks', [])
            elif isinstance(data, list):
                completed_task_names = data
        except Exception as e:
            print(f"Error reading completed tasks file: {e}")
            return
    else:
        print("No completed tasks provided.")
        print("Usage: python3 reverse_sync.py --completed-tasks <file>")
        print("\nNote: Get completed tasks from OmniFocus via MCP filter_tasks")
        return

    if not completed_task_names:
        print("No completed tasks to process")
        return

    print(f"Found {len(completed_task_names)} completed tasks\n")

    # Find completed tasks in state
    completed_tasks = find_completed_tasks_in_state(state, completed_task_names)

    if not completed_tasks:
        print("No synced tasks found in completed tasks")
        return

    print(f"Found {len(completed_tasks)} completed synced tasks\n")

    # Reflect completions to sources
    print("Reflecting completions to GitHub/Vault:")
    print("─" * 60)
    successful, failed = reflect_completions(completed_tasks, state, args.dry_run, args.verbose)

    # Update sync state
    if not args.dry_run:
        update_sync_state_completion(completed_tasks, state)

    print("\n" + "=" * 60)
    print(f"Results: {successful} updated, {failed} failed")
    if args.dry_run:
        print("(Dry run - no changes made)")


if __name__ == "__main__":
    main()
