#!/usr/bin/env python3
"""
GitHub Issues to OmniFocus Sync

Syncs GitHub Issues as OmniFocus projects with subtasks.
Each issue and subtask gets a unique hash for cross-system identification.
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

# State file location (relative to script directory)
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
    """
    Fetch open GitHub issues using gh CLI.

    Args:
        owner: GitHub repository owner
        repo: GitHub repository name

    Returns:
        List of issue dictionaries
    """
    try:
        cmd = [
            'gh', 'issue', 'list',
            '--repo', f'{owner}/{repo}',
            '--state', 'open',
            '--json', 'number,title,body,url'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error fetching GitHub issues: {e.stderr}", file=sys.stderr)
        sys.exit(1)


def parse_subtasks(body: Optional[str]) -> List[str]:
    """
    Parse subtasks from issue body using - [ ] format.

    Args:
        body: Issue body text

    Returns:
        List of subtask names
    """
    if not body:
        return []

    subtasks = []
    # Match "- [ ] TASK_NAME" or "- [x] TASK_NAME" patterns
    pattern = r'- \[[ x]\]\s*(.+?)(?:\n|$)'
    matches = re.findall(pattern, body)
    return [match.strip() for match in matches]


def add_omnifocus_project(
    name: str,
    note: str,
    dry_run: bool = False
) -> Optional[str]:
    """
    Add a project to OmniFocus.

    Args:
        name: Project name
        note: Project note (typically GitHub URL and source_id)
        dry_run: If True, only print what would be done

    Returns:
        OmniFocus task ID if successful, None otherwise
    """
    if dry_run:
        print(f"  [DRY RUN] Would add project: {name}")
        print(f"            Note: {note}")
        return None

    try:
        cmd = ['omnifocus', 'add', '--type', 'project', '--name', name, '--note', note]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        # Parse task ID from output (format varies by omnifocus version)
        # This is a placeholder - adjust based on actual omnifocus CLI output
        task_id = result.stdout.strip().split()[-1] if result.stdout else None
        return task_id
    except FileNotFoundError:
        print(f"  ⊘ OmniFocus CLI not available (will be queued for later sync)")
        return "pending"
    except subprocess.CalledProcessError as e:
        print(f"Error adding project to OmniFocus: {e.stderr}", file=sys.stderr)
        return None


def add_omnifocus_task(
    name: str,
    note: str = "",
    dry_run: bool = False
) -> Optional[str]:
    """
    Add a task to OmniFocus Inbox.

    Args:
        name: Task name
        note: Task note (typically source_id)
        dry_run: If True, only print what would be done

    Returns:
        OmniFocus task ID if successful, None otherwise
    """
    if dry_run:
        print(f"  [DRY RUN] Would add task: {name}")
        if note:
            print(f"           Note: {note}")
        return None

    try:
        cmd = ['omnifocus', 'add', '--name', name]
        if note:
            cmd.extend(['--note', note])
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        # Parse task ID from output
        task_id = result.stdout.strip().split()[-1] if result.stdout else None
        return task_id
    except FileNotFoundError:
        # OmniFocus CLI not available, but record for later sync
        return "pending"
    except subprocess.CalledProcessError as e:
        print(f"Error adding task to OmniFocus: {e.stderr}", file=sys.stderr)
        return None


def sync_github_issues(
    owner: str,
    repo: str,
    dry_run: bool = False,
    verbose: bool = False
) -> None:
    """
    Main sync function for GitHub Issues.

    Args:
        owner: GitHub repository owner
        repo: GitHub repository name
        dry_run: If True, only show what would be synced
        verbose: If True, show detailed information
    """
    state = load_state()

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

        # Check if already synced
        if is_synced(hash_value, state):
            if verbose:
                print(f"⊘ Issue #{issue_num}: {title} ({hash_value}) - already synced")
            skipped_count += 1
            continue

        # Add issue as OmniFocus project
        project_name = append_hash(title, source_id)
        note = f"GitHub: {url}\n{source_id}"

        if verbose:
            print(f"→ Adding issue #{issue_num}: {project_name}")

        task_id = add_omnifocus_project(project_name, note, dry_run=dry_run)

        # Record in state
        state[hash_value] = {
            "source_id": source_id,
            "of_task_id": task_id or "pending",
            "of_task_name": project_name,
            "status": "open",
            "synced_at": datetime.now().isoformat()
        }

        synced_count += 1

        # Parse and add subtasks
        subtasks = parse_subtasks(body)
        for subtask_name in subtasks:
            if has_hash(subtask_name):
                # Extract hash from subtask (already processed)
                subtask_hash = extract_hash(subtask_name)
                if subtask_hash and is_synced(subtask_hash, state):
                    if verbose:
                        print(f"  ⊘ Subtask: {subtask_name} - already synced")
                    skipped_count += 1
                    continue
            else:
                # Create new hash for subtask
                subtask_source_id = make_github_source_id(owner, repo, issue_num, subtask_name)
                subtask_hash = compute_hash(subtask_source_id)

                if is_synced(subtask_hash, state):
                    if verbose:
                        print(f"  ⊘ Subtask: {subtask_name} - already synced")
                    skipped_count += 1
                    continue

                subtask_name_with_hash = append_hash(subtask_name, subtask_source_id)

                if verbose:
                    print(f"  → Adding subtask: {subtask_name_with_hash}")

                subtask_task_id = add_omnifocus_task(subtask_name_with_hash, subtask_source_id, dry_run=dry_run)

                state[subtask_hash] = {
                    "source_id": subtask_source_id,
                    "of_task_id": subtask_task_id or "pending",
                    "of_task_name": subtask_name_with_hash,
                    "status": "open",
                    "synced_at": datetime.now().isoformat()
                }
                synced_count += 1

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

    # Parse owner and repo
    if '/' not in args.repo:
        print("Error: --repo must be in format owner/repo", file=sys.stderr)
        sys.exit(1)

    owner, repo = args.repo.split('/', 1)

    sync_github_issues(owner, repo, dry_run=args.dry_run, verbose=args.verbose)


if __name__ == "__main__":
    main()
