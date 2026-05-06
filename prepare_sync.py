#!/usr/bin/env python3
"""
Prepare Tasks for OmniFocus Sync via MCP

SCOPE:
  - GitHub Issues: Scans all open issues (full content)
  - Vault Tasks: Scans ONLY the Calendar/ folder
    (Daily Notes, time-based notes, etc.)

Generates TaskHash for each task and outputs a JSON file ready for
Claude to add via MCP tools.

This separates data preparation from the actual OmniFocus insertion,
making it more flexible and robust.

Excluded:
  - Atlas/ (knowledge notes, MOCs, references)
  - Efforts/ (project metadata)
  - x/ (scripts, templates, AI-generated content)
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


def process_missing_taskhash_issues(owner: str, repo: str, state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    SECTION 3.5: Automatically detect and process GitHub Issues missing TaskHash.

    This is the MANDATORY pre-sync step that ensures all GitHub Issues have:
    1. TaskHash in the issue title
    2. TaskHash for all body tasks

    Process:
    1. Scan all GitHub Issues
    2. For each Issue without TaskHash in title:
       - Generate TaskHash for title
       - Generate TaskHash for all body tasks
       - Update GitHub Issue with hashes appended
    3. Return Issue info for OmniFocus Project creation

    Returns:
        List of Issues that were processed (empty if all already have hashes)
    """
    print("\n[SECTION 3.5: Automatic GitHub Issue Processing]")
    print("Detecting issues without TaskHash in title...\n")

    try:
        # Get all open issues
        cmd = [
            'gh', 'issue', 'list',
            '--repo', f'{owner}/{repo}',
            '--state', 'open',
            '--json', 'number,title,body'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        issues = json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error fetching GitHub issues: {e.stderr}", file=sys.stderr)
        return []

    processed_issues = []

    for issue in issues:
        issue_num = issue['number']
        title = issue['title']
        body = issue.get('body', '')

        # Check if title has TaskHash
        if has_hash(title):
            print(f"✓ Issue #{issue_num}: {title} (already has TaskHash)")
            continue

        # MISSING HASH - Process this issue
        print(f"\n⚠️  Issue #{issue_num}: {title} (MISSING TaskHash)")

        # Generate TaskHash for issue title
        source_id = make_github_source_id(owner, repo, issue_num, title)
        issue_hash = compute_hash(source_id)
        new_title = append_hash(title, source_id)

        print(f"   Generated hash: {issue_hash}")
        print(f"   New title: {new_title}")

        # Process body tasks - add hashes to unchecked tasks
        updated_body = body
        if body:
            # Find all checkbox tasks
            task_pattern = r'^(\s*- \[[x\s]\]\s+)([^\n(]+?)(?:\s+\([0-9a-f]{8}\))?(\s*)$'

            def add_hash_to_task(match):
                prefix = match.group(1)  # "- [ ] " or "- [x] "
                task_name = match.group(2).strip()

                # Skip if already has hash
                if has_hash(match.group(0)):
                    return match.group(0)

                # Generate hash for this task
                task_source_id = make_github_source_id(owner, repo, issue_num, task_name)
                task_hash = compute_hash(task_source_id)

                return f"{prefix}{task_name} ({task_hash})"

            updated_body = re.sub(task_pattern, add_hash_to_task, body, flags=re.MULTILINE)

        # Update GitHub Issue
        try:
            # Update title
            subprocess.run(
                ['gh', 'issue', 'edit', str(issue_num),
                 '--repo', f'{owner}/{repo}',
                 '--title', new_title],
                check=True,
                capture_output=True
            )
            print(f"   ✓ Updated Issue title")

            # Update body if changed
            if updated_body != body:
                subprocess.run(
                    ['gh', 'issue', 'edit', str(issue_num),
                     '--repo', f'{owner}/{repo}',
                     '--body', updated_body],
                    check=True,
                    capture_output=True
                )
                print(f"   ✓ Updated Issue body with task hashes")

            processed_issues.append({
                'number': issue_num,
                'title': new_title,
                'body': updated_body,
                'hash': issue_hash
            })

        except subprocess.CalledProcessError as e:
            print(f"   ✗ Error updating Issue #{issue_num}: {e.stderr}", file=sys.stderr)
            continue

    if processed_issues:
        print(f"\n✓ Processed {len(processed_issues)} Issue(s) - added missing TaskHashes")
    else:
        print("\n✓ All Issues already have TaskHash")

    return processed_issues


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
            # FIRST: Check if comments contain actual tasks (- [ ] format)
            comment_tasks = parse_comment_tasks(comments)

            # ONLY create Comments parent metadata if there are actual tasks to add
            if comment_tasks:
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
    """Find all markdown files in Calendar folder only.

    IMPORTANT: Only syncs Calendar folder (Daily Notes, etc.).
    Excludes: Atlas, Efforts, x/ (except designated sync folders)
    """
    # Only scan Calendar folder
    calendar_path = vault_root / "Calendar"

    if not calendar_path.exists():
        print(f"⚠️  Calendar folder not found at {calendar_path}")
        return []

    markdown_files = []
    for file_path in calendar_path.rglob('*.md'):
        relative_path = file_path.relative_to(vault_root)
        markdown_files.append(relative_path)

    return sorted(markdown_files)


def is_section_header_line(line: str) -> bool:
    """
    Check if a line is a markdown section header (not a task).

    Examples of headers:
    - # Title
    - ## Projects
    - ### Subsection

    Should NOT match:
    - - [ ] Task with ## in the middle
    """
    # Only match if line STARTS with # (after optional whitespace)
    return re.match(r'^\s*#{1,6}\s+\S', line) is not None


def extract_tasks(file_path: Path, file_content: str) -> List[tuple]:
    """Extract unchecked tasks from markdown file content with parent info."""
    tasks = []
    lines = file_content.split('\n')

    # Track parent tasks for hierarchy
    parent_stack = []  # Stack of (indent_level, task_name) tuples

    for line_num, line in enumerate(lines, start=1):
        # SKIP section headers (##, ###, etc.) - not real tasks
        if is_section_header_line(line):
            # Clear parent stack when entering new section
            # This helps with section-based grouping
            if line.startswith('#'):
                parent_stack = []
            continue

        # Detect indent level (tabs or spaces)
        # Updated regex: more specific about task format
        indent_match = re.match(r'^(\t*| {0,8})- \[ \]\s+(.+?)(?:\s*$)', line)
        if indent_match:
            indent_str = indent_match.group(1)
            task_name = indent_match.group(2).strip()

            # Skip empty tasks or metadata-only lines
            if not task_name or task_name.startswith('(') or task_name.startswith('['):
                continue

            # Skip lines that look like metadata (e.g., "Projects (no TaskHash) - excluded from sync:")
            if 'TaskHash なし' in task_name or '同期対象外' in task_name \
                    or 'no TaskHash' in task_name or 'excluded from sync' in task_name:
                continue

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


def is_project_name_task(task_name: str, content: str, file_path: Path) -> bool:
    """
    Check if a task is a Project name (TaskHashless Project top-level task).

    Project name tasks:
    - Are top-level (no parent)
    - Match OmniFocus Project names (Later, Someday, etc.)
    - Should NOT be synced (they are Project containers, not real tasks)
    - Listed in a "## Projects" or "## New Single Action Projects" section

    Args:
        task_name: Clean task name
        content: File content
        file_path: File path

    Returns:
        True if this task is a Project name (should be skipped)
    """
    # Look for section headers that indicate Project names
    project_sections = [
        r"^##\s+Projects\s*$",
        r"^##\s+New Single Action Projects\s*$",
        r"^##\s+Inbox Projects\s*$",
    ]

    # Split by sections
    sections = re.split(r"^(##\s+.*?)$", content, flags=re.MULTILINE)

    for i in range(1, len(sections), 2):
        section_header = sections[i]
        section_content = sections[i + 1] if i + 1 < len(sections) else ""

        # Check if this section is a Project section
        is_project_section = any(re.match(pattern, section_header) for pattern in project_sections)

        if is_project_section:
            # Check if the task appears in this section
            task_pattern = re.escape(task_name)
            if re.search(f"^\\s*-\\s+\\[\\s*[\\sx]\\s*\\]\\s+{task_pattern}", section_content, re.MULTILINE):
                return True

    return False


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
        # Track Project container names so their children are also skipped
        skipped_containers: set = set()

        for task_name, line_num, indent_level, parent_task in tasks:
            # Extract URLs from Markdown links and clean task name
            urls = get_markdown_urls(task_name)
            cleaned_task_name = clean_markdown_links(task_name)

            # Skip Project name tasks (TaskHashless Project top-level containers)
            # These are managed in OmniFocus as Projects, not as individual tasks
            if indent_level == 0 and is_project_name_task(cleaned_task_name, content, file_path):
                print(f"  ⊘ {cleaned_task_name} (Project name - not a task, skip)")
                skipped_containers.add(task_name)  # Track to propagate skip to children
                continue

            # Skip children of Project containers (e.g., tasks inside "Later", "Someday")
            # Regular nested Vault tasks (children of real tasks) ARE synced with parentTaskHash
            if parent_task:
                # Normalize parent name for comparison (strip dates/hashes)
                parent_normalized = clean_markdown_links(parent_task)
                parent_normalized = re.sub(r'\s+📅\s+\d{4}-\d{2}-\d{2}', '', parent_normalized).strip()
                parent_normalized = re.sub(r'\s+\[due::\s*\d{4}-\d{2}-\d{2}\]', '', parent_normalized).strip()
                if parent_normalized in skipped_containers or parent_task in skipped_containers:
                    print(f"  ⊘ {cleaned_task_name} (child of Project container - skip)")
                    skipped_containers.add(task_name)  # Propagate to grandchildren
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

                # Prepare task dict — include parentTaskHash for nested Vault tasks
                task_dict = {
                    "type": "task",
                    "name": task_name_with_hash,
                    "note": note,
                    "hash": task_hash,
                    "source_id": source_id
                }

                # Resolve parent task hash for hierarchical Vault tasks
                if parent_task:
                    parent_cleaned = clean_markdown_links(parent_task)
                    parent_cleaned = re.sub(r'\s+📅\s+\d{4}-\d{2}-\d{2}', '', parent_cleaned).strip()
                    parent_cleaned = re.sub(r'\s+\[due::\s*\d{4}-\d{2}-\d{2}\]', '', parent_cleaned).strip()
                    parent_hash = task_name_to_hash.get(parent_cleaned)
                    if parent_hash:
                        task_dict["parentTaskHash"] = parent_hash

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

    print("=" * 70)
    print("TASK SYNC PREPARATION - Full Workflow")
    print("=" * 70)

    # STEP 0: Process missing GitHub Issue TaskHashes (SECTION 3.5)
    # This MUST run before prepare_github_tasks to ensure all Issues have hashes
    if '/' in args.repo:
        owner, repo = args.repo.split('/', 1)
        print("\n[STEP 0: Automatic GitHub Issue Processing (Section 3.5)]")
        processed = process_missing_taskhash_issues(owner, repo, state)
        # Reload state after processing
        state = load_state()

    # STEP 1: Prepare GitHub tasks
    if '/' in args.repo:
        owner, repo = args.repo.split('/', 1)
        print("\n[STEP 1: Scanning GitHub Issues]")
        github_tasks = prepare_github_tasks(owner, repo, state)
        all_tasks.extend(github_tasks)

    # STEP 2: Prepare Vault tasks
    if args.vault_root.exists():
        print("\n[STEP 2: Scanning Vault Files]")
        vault_tasks = prepare_vault_tasks(args.vault_root, state)
        all_tasks.extend(vault_tasks)

    # Save to file for Claude to process
    with open(PREPARE_FILE, 'w') as f:
        json.dump({
            "tasks": all_tasks,
            "prepared_at": datetime.now().isoformat(),
            "total_count": len(all_tasks)
        }, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 70)
    print(f"✓ Prepared {len(all_tasks)} tasks for sync")
    print(f"Output: {PREPARE_FILE}")
    print("=" * 70)
    print("\nNext: Ask Claude to sync these tasks to OmniFocus via MCP")


if __name__ == "__main__":
    main()
