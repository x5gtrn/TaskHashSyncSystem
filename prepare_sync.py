#!/usr/bin/env python3
"""
Prepare Tasks for OmniFocus Sync via MCP

Scans GitHub Issues and Vault tasks, generates hashes, and outputs
a JSON file ready for Claude to add via MCP tools.

This separates data preparation from the actual OmniFocus insertion,
making it more flexible and robust.
"""

import json
import subprocess
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any

from task_hash import (
    compute_hash,
    make_github_source_id,
    make_vault_source_id,
    append_hash,
    has_hash,
    extract_hash,
    remove_hash,
    clean_markdown_links,
    get_markdown_urls,
)

# Directories
SCRIPT_DIR = Path(__file__).parent
STATE_FILE = SCRIPT_DIR / "sync_state.json"
PREPARE_FILE = SCRIPT_DIR / "tasks_to_sync.json"  # Output file


def load_state() -> Dict[str, Any]:
    """Load sync state from JSON file."""
    if STATE_FILE.exists():
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {}


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


def prepare_github_tasks(owner: str, repo: str, state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Prepare GitHub tasks for sync."""
    tasks_to_add = []

    print(f"Fetching issues from {owner}/{repo}...")
    issues = fetch_github_issues(owner, repo)
    print(f"Found {len(issues)} open issues\n")

    for issue in issues:
        issue_num = issue['number']
        title = issue['title']
        url = issue['url']
        body = issue.get('body', '')

        # Remove hash from title if present (hash shouldn't be in source_id)
        title_without_hash = remove_hash(title)

        # Generate hash for the issue itself (using title without hash)
        source_id = make_github_source_id(owner, repo, issue_num, title_without_hash)
        hash_value = compute_hash(source_id)

        # Check if issue is already synced
        issue_already_synced = is_synced(hash_value, state)
        if not issue_already_synced:
            # Prepare task name with hash
            project_name = append_hash(title_without_hash, source_id)
            note = url  # URL only (hash tracks source)

            print(f"→ GitHub Issue #{issue_num}: {project_name}")

            # Add project task
            tasks_to_add.append({
                "type": "project",
                "name": project_name,
                "note": note,
                "hash": hash_value,
                "source_id": source_id
            })
        else:
            print(f"⊘ Issue #{issue_num}: {title_without_hash} - already synced")
            # Still use the project name for parent references in comments
            project_name = append_hash(title_without_hash, source_id)

        # Parse and add body subtasks first (only if issue is new)
        subtasks = parse_subtasks(body) if not issue_already_synced else []

        for subtask_name in subtasks:
            # Extract URLs from Markdown links and clean task name
            urls = get_markdown_urls(subtask_name)
            cleaned_subtask_name = clean_markdown_links(subtask_name)

            # Determine original task name and hash
            if has_hash(cleaned_subtask_name):
                subtask_hash = extract_hash(cleaned_subtask_name)
                subtask_original_name = cleaned_subtask_name[:-(len(subtask_hash) + 3)]
            else:
                subtask_original_name = cleaned_subtask_name
                subtask_source_id = make_github_source_id(owner, repo, issue_num, subtask_original_name)
                subtask_hash = compute_hash(subtask_source_id)

            # Check if already synced
            if is_synced(subtask_hash, state):
                print(f"  ⊘ Subtask: {cleaned_subtask_name} - already synced")
                continue

            # Create source_id and task name with hash
            subtask_source_id = make_github_source_id(owner, repo, issue_num, subtask_original_name)
            subtask_hash = compute_hash(subtask_source_id)
            subtask_name_with_hash = append_hash(subtask_original_name, subtask_source_id)

            print(f"  → Subtask: {subtask_name_with_hash}")

            # Build note with URLs only (source_id tracked via hash)
            note = "\n".join(urls) if urls else ""

            # Add subtask task
            subtask_dict = {
                "type": "task",
                "name": subtask_name_with_hash,
                "note": note,
                "projectName": project_name,  # Parent project
                "hash": subtask_hash,
                "source_id": subtask_source_id
            }
            tasks_to_add.append(subtask_dict)

        # Parse and add comment tasks
        comments = issue.get('comments', [])
        if comments:
            # Create a "Comments" parent task to hold all comment tasks
            comments_parent_name = f"Comments (from {len(comments)} comment{'s' if len(comments) != 1 else ''})"
            comments_source_id = make_github_source_id(owner, repo, issue_num, comments_parent_name)
            comments_hash = compute_hash(comments_source_id)

            # Only add comments parent if it doesn't already exist
            if not is_synced(comments_hash, state):
                comments_parent_name_with_hash = append_hash(comments_parent_name, comments_source_id)
                print(f"  → {comments_parent_name_with_hash}")

                tasks_to_add.append({
                    "type": "task",
                    "name": comments_parent_name_with_hash,
                    "note": "",  # Note tracked via hash
                    "projectName": project_name,  # Parent project
                    "hash": comments_hash,
                    "source_id": comments_source_id
                })

            # Add each comment's tasks as subtasks
            comment_tasks = parse_comment_tasks(comments)
            for comment_task_name, comment_idx, _ in comment_tasks:
                # Extract URLs from Markdown links and clean task name
                urls = get_markdown_urls(comment_task_name)
                cleaned_comment_task_name = clean_markdown_links(comment_task_name)

                # Determine original task name and hash
                if has_hash(cleaned_comment_task_name):
                    comment_task_hash = extract_hash(cleaned_comment_task_name)
                    comment_task_original_name = cleaned_comment_task_name[:-(len(comment_task_hash) + 3)]
                else:
                    comment_task_original_name = cleaned_comment_task_name
                    comment_task_source_id = make_github_source_id(
                        owner, repo, issue_num,
                        f"comment#{comment_idx}:{comment_task_original_name}"
                    )
                    comment_task_hash = compute_hash(comment_task_source_id)

                # Check if already synced
                if is_synced(comment_task_hash, state):
                    print(f"    ⊘ Comment task: {cleaned_comment_task_name} - already synced")
                    continue

                # Create source_id and task name with hash
                comment_task_source_id = make_github_source_id(
                    owner, repo, issue_num,
                    f"comment#{comment_idx}:{comment_task_original_name}"
                )
                comment_task_hash = compute_hash(comment_task_source_id)
                comment_task_name_with_hash = append_hash(comment_task_original_name, comment_task_source_id)

                print(f"    → Comment task: {comment_task_name_with_hash}")

                # Build note with URLs only (source_id tracked via hash)
                note = "\n".join(urls) if urls else ""

                # Add comment task - as subtask of the Comments parent (using TaskHash)
                comment_task_dict = {
                    "type": "task",
                    "name": comment_task_name_with_hash,
                    "note": note,
                    "hash": comment_task_hash,
                    "source_id": comment_task_source_id
                }

                # Link to Comments parent task using TaskHash
                comment_task_dict["parentTaskHash"] = comments_hash

                # Also link to the project for context
                comment_task_dict["projectName"] = project_name

                tasks_to_add.append(comment_task_dict)

    return tasks_to_add


def find_vault_files(vault_root: Path) -> List[Path]:
    """Find all markdown files in vault that should be scanned."""
    exclude_patterns = ["x/Templates", "x/Scripts", ".obsidian", "Example", "CLAUDE", "Task-Hash-Sync-System"]

    markdown_files = []
    for file_path in vault_root.rglob('*.md'):
        relative_path = file_path.relative_to(vault_root)
        path_str = str(relative_path)

        # Check exclusions
        skip = False
        for pattern in exclude_patterns:
            if pattern in path_str:
                skip = True
                break

        if not skip:
            markdown_files.append(relative_path)

    return sorted(markdown_files)


def extract_tasks(file_path: Path, file_content: str) -> List[tuple]:
    """Extract unchecked tasks from markdown file content with parent info."""
    tasks = []
    lines = file_content.split('\n')

    # Track parent tasks for hierarchy
    parent_stack = []  # Stack of (indent_level, task_name) tuples

    for line_num, line in enumerate(lines, start=1):
        # Detect indent level (tabs or spaces)
        indent_match = re.match(r'^(\t*| +)- \[ \]\s*(.+?)(?:\s*$)', line)
        if indent_match:
            indent_str = indent_match.group(1)
            task_name = indent_match.group(2).strip()

            if task_name:
                # Calculate indent level (each tab or 2 spaces = 1 level)
                if indent_str.startswith('\t'):
                    indent_level = len(indent_str)
                else:
                    indent_level = len(indent_str) // 2

                # Remove due date emoji and date from task name for hash generation
                task_name_for_hash = re.sub(r'\s+📅\s+\d{4}-\d{2}-\d{2}', '', task_name)
                task_name_for_hash = re.sub(r'\s+\[due::\s*\d{4}-\d{2}-\d{2}\]', '', task_name_for_hash)

                # Update parent stack based on indent level
                # Remove parents with same or higher indent level
                while parent_stack and parent_stack[-1][0] >= indent_level:
                    parent_stack.pop()

                # Get parent task (if any)
                parent_task = parent_stack[-1][1] if parent_stack else None

                # Add to stack for future children
                parent_stack.append((indent_level, task_name_for_hash))

                tasks.append((task_name_for_hash, line_num, indent_level, parent_task))

    return tasks


def prepare_vault_tasks(vault_root: Path, state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Prepare Vault tasks for sync."""
    tasks_to_add = []

    print(f"Scanning vault at {vault_root}...")
    vault_files = find_vault_files(vault_root)
    print(f"Found {len(vault_files)} markdown files\n")

    for file_path in vault_files:
        full_path = vault_root / file_path

        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"Warning: Could not read {file_path}: {e}", file=sys.stderr)
            continue

        tasks = extract_tasks(file_path, content)

        if not tasks:
            continue

        print(f"Found {len(tasks)} tasks in {file_path}")

        # First pass: Build a map of task names to their hash values for parent references
        task_name_to_hash = {}
        for task_name, line_num, indent_level, parent_task in tasks:
            cleaned_task_name = clean_markdown_links(task_name)
            # Remove due date
            cleaned_task_name = re.sub(r'\s+📅\s+\d{4}-\d{2}-\d{2}', '', cleaned_task_name)
            cleaned_task_name = re.sub(r'\s+\[due::\s*\d{4}-\d{2}-\d{2}\]', '', cleaned_task_name)

            if has_hash(cleaned_task_name):
                task_hash = extract_hash(cleaned_task_name)
            else:
                source_id = make_vault_source_id(str(file_path), cleaned_task_name)
                task_hash = compute_hash(source_id)

            task_name_to_hash[cleaned_task_name] = task_hash

        # Second pass: Process each task with parent references available
        for task_name, line_num, indent_level, parent_task in tasks:
            # Extract URLs from Markdown links and clean task name
            urls = get_markdown_urls(task_name)
            cleaned_task_name = clean_markdown_links(task_name)

            # Skip tasks that are part of OmniFocus Projects
            # (OmniFocus Projects correspond to GitHub Issues, not Vault tasks)
            # Tasks with a parent_task are part of a Project and should not be synced to Vault
            if parent_task:
                print(f"  ⊘ {cleaned_task_name} (part of OmniFocus Project - skip)")
                continue

            # Determine if already has hash
            if has_hash(cleaned_task_name):
                task_hash = extract_hash(cleaned_task_name)
                if task_hash and is_synced(task_hash, state):
                    print(f"  ⊘ {cleaned_task_name} - already synced")
                    continue
            else:
                source_id = make_vault_source_id(str(file_path), cleaned_task_name)
                task_hash = compute_hash(source_id)

                if is_synced(task_hash, state):
                    print(f"  ⊘ {cleaned_task_name} - already synced")
                    continue

                task_name_with_hash = append_hash(cleaned_task_name, source_id)

                print(f"  → {task_name_with_hash}")

                # Build note with URLs only (source_id tracked via hash)
                note = "\n".join(urls) if urls else ""

                # Prepare task dict (no parent reference for Vault tasks)
                task_dict = {
                    "type": "task",
                    "name": task_name_with_hash,
                    "note": note,
                    "hash": task_hash,
                    "source_id": source_id
                }

                # Add task
                tasks_to_add.append(task_dict)

    return tasks_to_add


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Prepare GitHub and Vault tasks for OmniFocus sync"
    )
    parser.add_argument(
        '--repo',
        required=False,
        default='x5gtrn/LIFE',
        help='GitHub repository (owner/repo format)'
    )
    parser.add_argument(
        '--vault-root',
        type=Path,
        default=Path('/Users/x5gtrn/Library/Mobile Documents/iCloud~md~obsidian/Documents/LIFE'),
        help='Path to vault root directory'
    )

    args = parser.parse_args()

    state = load_state()
    all_tasks = []

    # Prepare GitHub tasks
    if '/' in args.repo:
        owner, repo = args.repo.split('/', 1)
        github_tasks = prepare_github_tasks(owner, repo, state)
        all_tasks.extend(github_tasks)

    # Prepare Vault tasks
    if args.vault_root.exists():
        vault_tasks = prepare_vault_tasks(args.vault_root, state)
        all_tasks.extend(vault_tasks)

    # Save to file for Claude to process
    with open(PREPARE_FILE, 'w') as f:
        json.dump({
            "tasks": all_tasks,
            "prepared_at": datetime.now().isoformat(),
            "total_count": len(all_tasks)
        }, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Prepared {len(all_tasks)} tasks for sync")
    print(f"Output: {PREPARE_FILE}")
    print("\nNext: Ask Claude to sync these tasks to OmniFocus via MCP")


if __name__ == "__main__":
    main()
