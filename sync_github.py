#!/usr/bin/env python3
"""
GitHub Issues to OmniFocus Sync (Updated)

Syncs GitHub Issues to OmniFocus as projects with subtasks.
Updates GitHub Issues with hash values after successful sync.
"""

import json
import subprocess
import argparse
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any

from task_hash import (
    compute_hash,
    make_github_source_id,
    append_hash,
    has_hash,
    extract_hash,
)
# MCP tools will be called directly in the sync function

# State file location
SCRIPT_DIR = Path(__file__).parent
STATE_FILE = SCRIPT_DIR / "sync_state.json"


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


def is_synced(hash_value: str, state: Dict[str, Any]) -> bool:
    """Check if a task hash is already synced."""
    return hash_value in state


def fetch_github_issues(owner: str, repo: str) -> List[Dict[str, Any]]:
    """Fetch open GitHub issues with comments using gh CLI."""
    try:
        cmd = [
            'gh', 'issue', 'list',
            '--repo', f'{owner}/{repo}',
            '--state', 'open',
            '--json', 'number,title,body,url'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        issues = json.loads(result.stdout)

        # Fetch comments for each issue
        for issue in issues:
            issue_num = issue['number']
            try:
                cmd_comments = [
                    'gh', 'issue', 'view', str(issue_num),
                    '--repo', f'{owner}/{repo}',
                    '--json', 'comments'
                ]
                result_comments = subprocess.run(cmd_comments, capture_output=True, text=True, check=True)
                comments_data = json.loads(result_comments.stdout)
                issue['comments'] = comments_data.get('comments', [])
            except subprocess.CalledProcessError:
                issue['comments'] = []

        return issues
    except subprocess.CalledProcessError as e:
        print(f"Error fetching GitHub issues: {e.stderr}", file=sys.stderr)
        sys.exit(1)


def parse_subtasks(body: Optional[str]) -> List[str]:
    """Parse subtasks from issue body using - [ ] format."""
    if not body:
        return []
    subtasks = []
    pattern = r'- \[[ x]\]\s*(.+?)(?:\n|$)'
    matches = re.findall(pattern, body)
    return [match.strip() for match in matches]


def parse_comment_tasks(comments: List[Dict[str, Any]]) -> List[tuple]:
    """
    Parse tasks from issue comments.

    Returns:
        List of tuples: (task_name, comment_index, body_text)
    """
    tasks = []
    pattern = r'- \[[ x]\]\s*(.+?)(?:\n|$)'

    for comment_idx, comment in enumerate(comments):
        body = comment.get('body', '')
        if not body:
            continue

        matches = re.findall(pattern, body)
        for match in matches:
            task_name = match.strip()
            if task_name:
                tasks.append((task_name, comment_idx, body))

    return tasks


def update_github_issue_body(
    owner: str,
    repo: str,
    issue_num: int,
    new_body: str
) -> bool:
    """Update GitHub Issue body with new content."""
    try:
        cmd = [
            'gh', 'issue', 'edit',
            f'{issue_num}',
            '--repo', f'{owner}/{repo}',
            '--body', new_body
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error updating GitHub issue: {e.stderr}", file=sys.stderr)
        return False


def add_hash_to_issue_body(body: str, subtasks_with_hashes: Dict[str, str]) -> str:
    """
    Update issue body to include hash values in task names.

    Args:
        body: Original issue body
        subtasks_with_hashes: Map of original task name to hashed name

    Returns:
        Updated body with hashes added
    """
    new_body = body

    # Replace each subtask line with hash-appended version
    for original_name, hashed_name in subtasks_with_hashes.items():
        # Find the task line and replace it
        pattern = rf'- \[[ x]\]\s*{re.escape(original_name)}(?=\n|$)'
        replacement = f'- [ ] {hashed_name}'
        new_body = re.sub(pattern, replacement, new_body)

    return new_body


def sync_github_issues(
    owner: str,
    repo: str,
    dry_run: bool = False,
    verbose: bool = False
) -> None:
    """Main sync function for GitHub Issues."""
    state = load_state()
    omnifocus_available = get_omnifocus_available()

    if not omnifocus_available and not dry_run:
        print("Warning: OmniFocus not available, tasks will be queued only")

    print(f"Fetching issues from {owner}/{repo}...")
    issues = fetch_github_issues(owner, repo)
    print(f"Found {len(issues)} open issues\n")

    synced_count = 0
    skipped_count = 0

    for issue in issues:
        issue_num = issue['number']
        title = issue['title']
        url = issue['url']
        body = issue.get('body', '')

        # Generate hash for the issue itself
        source_id = make_github_source_id(owner, repo, issue_num, title)
        hash_value = compute_hash(source_id)
        hash_short = hash_value[:6]  # First 6 characters

        # Check if already synced
        if is_synced(hash_value, state):
            if verbose:
                print(f"⊘ Issue #{issue_num}: {title} ({hash_value}) - already synced")
            skipped_count += 1
            continue

        # Prepare task name with hash
        project_name = append_hash(title, source_id)
        note = f"GitHub: {url}\n{source_id}"

        if verbose:
            print(f"→ Adding issue #{issue_num}: {project_name}")

        # Add project to OmniFocus
        project_id = None
        if omnifocus_available and not dry_run:
            project_id = add_project_to_omnifocus(project_name, note)
        elif dry_run:
            print(f"  [DRY RUN] Would add project: {project_name}")

        # Record in state
        state[hash_value] = {
            "source_id": source_id,
            "of_task_id": project_id or "pending",
            "of_task_name": project_name,
            "status": "open",
            "synced_at": datetime.now().isoformat()
        }

        synced_count += 1

        # Parse and add subtasks
        subtasks = parse_subtasks(body)
        subtasks_with_hashes = {}

        for subtask_name in subtasks:
            # Determine original task name and hash
            if has_hash(subtask_name):
                # Subtask already has hash, extract it
                subtask_hash = extract_hash(subtask_name)
                subtask_original_name = subtask_name[:-(len(subtask_hash) + 3)]  # Remove " (HASH)"
            else:
                # Subtask needs hash
                subtask_original_name = subtask_name
                subtask_source_id = make_github_source_id(owner, repo, issue_num, subtask_original_name)
                subtask_hash = compute_hash(subtask_source_id)

            # Check if already synced
            if is_synced(subtask_hash, state):
                if verbose:
                    print(f"  ⊘ Subtask: {subtask_name} - already synced")
                skipped_count += 1
                continue

            # Create source_id and task name with hash
            subtask_source_id = make_github_source_id(owner, repo, issue_num, subtask_original_name)
            subtask_hash = compute_hash(subtask_source_id)
            subtask_name_with_hash = append_hash(subtask_original_name, subtask_source_id)

            if verbose:
                print(f"  → Adding subtask: {subtask_name_with_hash}")

            # Add subtask to OmniFocus
            if omnifocus_available and not dry_run and project_id:
                task_id = add_subtask_to_project(project_id, subtask_name_with_hash, subtask_source_id)
            elif dry_run:
                print(f"    [DRY RUN] Would add task: {subtask_name_with_hash}")
                task_id = None
            else:
                task_id = None

            # Track for issue body update (only if hash not already present)
            if not has_hash(subtask_name):
                subtasks_with_hashes[subtask_original_name] = subtask_name_with_hash

            state[subtask_hash] = {
                "source_id": subtask_source_id,
                "of_task_id": task_id if (omnifocus_available and not dry_run and project_id) else "pending",
                "of_task_name": subtask_name_with_hash,
                "status": "open",
                "synced_at": datetime.now().isoformat()
            }

            synced_count += 1

        # Update GitHub Issue body with hashes (only if new subtasks were added)
        if subtasks_with_hashes and not dry_run:
            new_body = add_hash_to_issue_body(body, subtasks_with_hashes)
            if update_github_issue_body(owner, repo, issue_num, new_body):
                if verbose:
                    print(f"  ✓ Updated GitHub issue #{issue_num} with hashes")

    # Save updated state
    if not dry_run:
        save_state(state)

    print(f"\nResults: {synced_count} new, {skipped_count} skipped")
    if dry_run:
        print("(Dry run - no changes made)")


def main():
    parser = argparse.ArgumentParser(
        description="Sync GitHub Issues to OmniFocus"
    )
    parser.add_argument(
        '--repo',
        required=True,
        help='GitHub repository (owner/repo format, e.g., x5gtrn/LIFE)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be synced without making changes'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed information'
    )

    args = parser.parse_args()

    if '/' not in args.repo:
        print("Error: --repo must be in format owner/repo", file=sys.stderr)
        sys.exit(1)

    owner, repo = args.repo.split('/', 1)

    sync_github_issues(owner, repo, dry_run=args.dry_run, verbose=args.verbose)


if __name__ == "__main__":
    main()
