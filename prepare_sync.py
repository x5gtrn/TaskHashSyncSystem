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


def parse_subtasks_with_state(body: Optional[str]) -> List[tuple]:
    """
    Parse subtasks from issue body with checkbox state.

    Returns:
        List of tuples: (is_completed, task_name)
        is_completed: True if [x], False if [ ]
    """
    if not body:
        return []
    tasks = []
    pattern = r'- \[([x ])\]\s*(.+?)(?:\n|$)'
    matches = re.findall(pattern, body)
    for checkbox, task_name in matches:
        is_completed = checkbox == 'x'
        tasks.append((is_completed, task_name.strip()))
    return tasks


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


def update_vault_files_with_hashes(vault_root: Path, vault_tasks: List[Dict[str, Any]]) -> None:
    """
    Update Vault Daily Note files by appending TaskHash to newly-scanned tasks.

    Purpose: Ensure Vault and OmniFocus stay synchronized with TaskHash in task names.
    Also preserves due dates in the correct format.

    Process:
    1. Build map of file_path → [(task_name, hash, due_date), ...]
    2. For each file, find tasks without hash and append it (preserving due date)
    3. Write updated content back to file (idempotent)
    """
    # Build file update map from vault_tasks
    file_updates = {}

    for task in vault_tasks:
        source_id = task.get('source_id', '')
        task_hash = task.get('hash')
        due_date = task.get('dueDate')

        if source_id.startswith('vault:') and task_hash:
            # Parse source_id: vault:relative/path.md:task_name
            parts = source_id.split(':', 2)
            if len(parts) >= 3:
                file_rel_path = parts[1]
                task_name_clean = parts[2]

                if file_rel_path not in file_updates:
                    file_updates[file_rel_path] = []
                file_updates[file_rel_path].append((task_name_clean, task_hash, due_date))

    if not file_updates:
        return  # No updates needed

    # Update each file
    for file_rel_path, updates in file_updates.items():
        full_path = vault_root / file_rel_path

        if not full_path.exists():
            continue

        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"⚠️  Could not read {file_rel_path} for hash update: {e}", file=sys.stderr)
            continue

        # Track if file was modified
        original_content = content

        # For each task, append hash at END (after all metadata including due dates)
        for task_name_clean, task_hash, due_date in updates:
            # Build pattern to find task line and append hash at END
            # Escape task name for regex
            task_pattern = re.escape(task_name_clean)

            # Pattern explanation:
            # - Match: - [ ] {task_name} {optional due_date}
            # - Ensure hash is not already present
            # - Append hash at the very end of the line
            # Example input:  - [ ] 明日8日...準備を📅 2026-05-08
            # Example output: - [ ] 明日8日...準備を📅 2026-05-08 (a1c1433e)

            # Build replacement with due date preservation
            due_date_part = f' 📅 {due_date}' if due_date else ''

            pattern = f'(- \\[ \\] {task_pattern})(?:\\s+📅\\s+\\d{{4}}-\\d{{2}}-\\d{{2}})?(?:\\s+\\[due::\\s*\\d{{4}}-\\d{{2}}-\\d{{2}}\\])?(\\s*)$'

            # Only replace if hash not already at end
            if re.search(pattern, content, re.MULTILINE):
                replacement = f'\\1{due_date_part} ({task_hash})'
                content = re.sub(
                    pattern,
                    replacement,
                    content,
                    flags=re.MULTILINE
                )
                # Remove duplicate hash if somehow present
                content = re.sub(
                    f'(- \\[ \\] {task_pattern}.*)\\s+\\({task_hash}\\)\\s+\\({task_hash}\\)',
                    f'\\1 ({task_hash})',
                    content
                )

        # Write back if modified
        if content != original_content:
            try:
                with open(full_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f"  ✓ Updated {file_rel_path} with TaskHashes")
            except Exception as e:
                print(f"⚠️  Could not write {file_rel_path}: {e}", file=sys.stderr)


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


def extract_due_date(task_name: str) -> tuple:
    """
    Extract due date from task name.

    Returns: (task_name_without_date, due_date_string)

    Formats supported:
    - 📅 YYYY-MM-DD
    - [due:: YYYY-MM-DD]

    Example:
        Input:  "Buy milk 📅 2026-05-10"
        Output: ("Buy milk", "2026-05-10")
    """
    # Try emoji format first: 📅 YYYY-MM-DD
    emoji_match = re.search(r'\s+📅\s+(\d{4}-\d{2}-\d{2})', task_name)
    if emoji_match:
        date_str = emoji_match.group(1)
        clean_name = task_name[:emoji_match.start()] + task_name[emoji_match.end():]
        return (clean_name.strip(), date_str)

    # Try bracket format: [due:: YYYY-MM-DD]
    bracket_match = re.search(r'\s+\[due::\s*(\d{4}-\d{2}-\d{2})\]', task_name)
    if bracket_match:
        date_str = bracket_match.group(1)
        clean_name = task_name[:bracket_match.start()] + task_name[bracket_match.end():]
        return (clean_name.strip(), date_str)

    return (task_name, None)


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
    """
    Extract unchecked tasks from markdown file content with parent info and due dates.

    Returns: List of (task_name_clean, line_num, indent_level, parent_task, due_date)
    """
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

            # Skip empty tasks or metadata-only lines.
            # Note: do NOT skip tasks that start with '[' — they may be valid Markdown
            # link tasks like "[Buy Groceries](https://store.com)".  The URL is extracted
            # later by get_markdown_urls / clean_markdown_links.
            if not task_name or task_name.startswith('('):
                continue
            # Skip lines that are *solely* a bracket-metadata annotation (no link URL)
            if task_name.startswith('[') and not re.search(r'\]\s*\(', task_name):
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

            # Extract due date from task name
            task_name_clean, due_date = extract_due_date(task_name)

            # Use clean name (without date) for hash generation
            task_name_for_hash = task_name_clean

            # Update parent stack based on indent level
            # Remove parents with same or higher indent level
            while parent_stack and parent_stack[-1][0] >= indent_level:
                parent_stack.pop()

            # Get parent task (if any)
            parent_task = parent_stack[-1][1] if parent_stack else None

            # Add to stack for future children
            parent_stack.append((indent_level, task_name_for_hash))

            tasks.append((task_name_for_hash, line_num, indent_level, parent_task, due_date))

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


def detect_existing_issue_updates(owner: str, repo: str, state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    STEP 0.5: Detect changes in existing synced GitHub Issues.

    This function:
    1. Finds all github_project entries in sync_state
    2. Fetches current Issue content from GitHub
    3. Compares with synced task state
    4. Detects new tasks, deleted tasks, completion state changes
    5. Generates update instructions for OmniFocus

    Returns:
        List of update instructions for existing Issues
    """
    print("Detecting changes in existing synced GitHub Issues...")

    if not state:
        return []

    # Find all github_project entries
    # Key by hash (not issue_num) so parent_task_hash lookups work
    github_projects = {}
    for hash_val, entry in state.items():
        if entry.get('task_type') == 'github_project':
            source_id = entry.get('source_id', '')
            # source_id format: github:owner/repo#issue_num:Issue Title
            match = re.search(r'github:.+?#(\d+):', source_id)
            if match:
                issue_num = int(match.group(1))
                github_projects[hash_val] = {  # Key by hash, not issue_num
                    'hash': hash_val,
                    'issue_num': issue_num,
                    'entry': entry,
                    'synced_tasks': []
                }

    if not github_projects:
        print("No existing GitHub projects found")
        return []


    # Collect synced child tasks for each project
    for hash_val, entry in state.items():
        if entry.get('task_type') == 'github_task':
            parent_hash = entry.get('parent_task_hash')
            # Skip debug output
            if parent_hash in github_projects:
                github_projects[parent_hash]['synced_tasks'].append({
                    'hash': hash_val,
                    'name': entry.get('of_task_name', ''),
                    'status': entry.get('status')
                })

    all_updates = []

    # Check each project for updates
    for project_hash, project_info in github_projects.items():
        issue_num = project_info['issue_num']
        try:
            # Fetch current Issue content
            cmd = [
                'gh', 'issue', 'view', str(issue_num),
                '--repo', f'{owner}/{repo}',
                '--json', 'body'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            issue_data = json.loads(result.stdout)
            current_body = issue_data.get('body', '')

            # Parse current tasks from Issue body WITH checkbox state
            current_tasks_with_state = parse_subtasks_with_state(current_body)

            # Extract hashes from synced tasks
            synced_hashes = {}  # hash -> {name, status}
            for task in project_info['synced_tasks']:
                hash_match = re.search(r'\(([a-f0-9]{8})\)', task['name'])
                if hash_match:
                    task_hash = hash_match.group(1)
                    synced_hashes[task_hash] = {
                        'name': task['name'],
                        'status': task['status']
                    }

            # Extract hashes from current tasks with completion state
            current_hashes = {}  # hash -> {is_completed, task_text}
            tasks_without_hash = []  # Track tasks that don't have hashes
            for is_completed, task_text in current_tasks_with_state:
                hash_match = re.search(r'\(([a-f0-9]{8})\)', task_text)
                if hash_match:
                    task_hash = hash_match.group(1)
                    current_hashes[task_hash] = {
                        'is_completed': is_completed,
                        'task_text': task_text
                    }
                else:
                    # Track tasks without hashes for new task generation
                    tasks_without_hash.append({
                        'is_completed': is_completed,
                        'task_text': task_text
                    })

            # Detect changes
            new_hashes = set(current_hashes.keys()) - set(synced_hashes.keys())
            deleted_hashes = set(synced_hashes.keys()) - set(current_hashes.keys())

            # Detect completion state changes for existing tasks
            completion_changes = []
            for task_hash in synced_hashes:
                if task_hash in current_hashes:
                    synced_status = synced_hashes[task_hash]['status']
                    is_completed_now = current_hashes[task_hash]['is_completed']

                    # Check if completion state changed
                    was_completed = synced_status == 'completed'
                    if is_completed_now != was_completed:
                        completion_changes.append({
                            'hash': task_hash,
                            'previous_status': synced_status,
                            'new_status': 'completed' if is_completed_now else 'incomplete'
                        })

            total_new_tasks = len(new_hashes) + len(tasks_without_hash)
            if total_new_tasks or deleted_hashes or completion_changes:
                print(f"\n✓ Issue #{issue_num}: {total_new_tasks} new tasks, {len(deleted_hashes)} deleted, {len(completion_changes)} completion state changes")

                project_hash = project_info['hash']

                # Generate update instruction
                update_info = {
                    'issue_num': issue_num,
                    'project_hash': project_hash,
                    'new_tasks': [],
                    'deleted_tasks': list(deleted_hashes),
                    'completion_changes': completion_changes,
                    'current_body': current_body
                }

                # Process new tasks with hashes
                for new_hash in new_hashes:
                    task_text = current_hashes[new_hash]['task_text']
                    task_name = clean_markdown_links(task_text)
                    task_name = task_name.replace(f'({new_hash})', '').strip()

                    # Check if task needs a new hash (if it doesn't have one yet in current form)
                    if not re.search(r'\([a-f0-9]{8}\)', task_text):
                        # Generate hash for new task
                        source_id = make_github_source_id(owner, repo, issue_num, task_name)
                        hash_val = compute_hash(source_id)
                        task_name = append_hash(task_name, hash_val)
                    else:
                        # Task already has hash
                        hash_val = new_hash

                    update_info['new_tasks'].append({
                        'name': task_name,
                        'hash': hash_val,
                        'source_id': make_github_source_id(owner, repo, issue_num, task_name.replace(f'({hash_val})', '').strip())
                    })

                # Process tasks without any hash yet (completely new)
                for task_info in tasks_without_hash:
                    task_text = task_info['task_text']
                    # Extract URLs before cleaning link syntax
                    urls = get_markdown_urls(task_text)
                    note = "\n".join(urls) if urls else ""
                    task_name = clean_markdown_links(task_text)

                    # Generate new hash for this task
                    source_id = make_github_source_id(owner, repo, issue_num, task_name)
                    hash_val = compute_hash(source_id)
                    task_name_with_hash = append_hash(task_name, hash_val)

                    update_info['new_tasks'].append({
                        'name': task_name_with_hash,
                        'hash': hash_val,
                        'source_id': source_id,
                        'note': note,
                    })

                all_updates.append(update_info)

        except subprocess.CalledProcessError as e:
            print(f"Warning: Could not fetch Issue #{issue_num}: {e.stderr}", file=sys.stderr)
            continue

    if all_updates:
        print(f"\nFound updates in {len(all_updates)} existing GitHub Issues")

    return all_updates


def prepare_vault_tasks(
    vault_root: Path, state: Dict[str, Any]
) -> tuple:
    """Prepare Vault tasks for sync.

    Returns:
        (tasks_to_add, due_date_updates) where due_date_updates is a list of
        dicts for already-synced tasks whose due date changed in the Vault.
    """
    tasks_to_add = []
    due_date_updates: List[Dict[str, Any]] = []

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
        for task_name, line_num, indent_level, parent_task, due_date in tasks:
            cleaned_task_name = clean_markdown_links(task_name)
            # Note: due_date already extracted by extract_tasks, task_name is clean

            if has_hash(cleaned_task_name):
                task_hash = extract_hash(cleaned_task_name)
            else:
                source_id = make_vault_source_id(str(file_path), cleaned_task_name)
                task_hash = compute_hash(source_id)

            task_name_to_hash[cleaned_task_name] = task_hash

        # Second pass: Process each task with parent references available
        # Track Project container names so their children are also skipped
        skipped_containers: set = set()

        for task_name, line_num, indent_level, parent_task, due_date in tasks:
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
                    existing = state[task_hash]
                    synced_due = existing.get("due_date")
                    if due_date and due_date != synced_due:
                        due_date_updates.append({
                            "task_hash": task_hash,
                            "of_task_id": existing.get("of_task_id", ""),
                            "of_task_name": existing.get("of_task_name", ""),
                            "new_due_date": due_date,
                        })
                    print(f"  ⊘ {cleaned_task_name} - already synced")
                    continue
                # BUG FIX: Hash present in Vault but NOT in sync_state.
                # This happens when a previous prepare_sync run wrote the hash
                # to the Vault file but crashed (or was interrupted) before
                # updating sync_state.json.  Reuse the existing hash so the
                # Vault file stays unchanged; treat the task as new.
                clean_name = remove_hash(cleaned_task_name).strip()
                source_id = make_vault_source_id(str(file_path), clean_name)
                if not task_hash:
                    task_hash = compute_hash(source_id)
                task_name_with_hash = cleaned_task_name  # hash already in Vault
                print(f"  → {task_name_with_hash} (hash in Vault but missing from sync_state)")
            else:
                source_id = make_vault_source_id(str(file_path), cleaned_task_name)
                task_hash = compute_hash(source_id)

                if is_synced(task_hash, state):
                    existing = state[task_hash]
                    synced_due = existing.get("due_date")
                    if due_date and due_date != synced_due:
                        due_date_updates.append({
                            "task_hash": task_hash,
                            "of_task_id": existing.get("of_task_id", ""),
                            "of_task_name": existing.get("of_task_name", ""),
                            "new_due_date": due_date,
                        })
                    print(f"  ⊘ {cleaned_task_name} - already synced")
                    continue

                task_name_with_hash = append_hash(cleaned_task_name, source_id)
                print(f"  → {task_name_with_hash}")

            # ── Shared path: add task to the output list ──────────────────────
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

            # Add due date if present
            if due_date:
                task_dict["dueDate"] = due_date

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

    return tasks_to_add, due_date_updates


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
    existing_issue_updates = []

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

    # STEP 0.5: Detect changes in existing synced GitHub Issues
    if '/' in args.repo:
        owner, repo = args.repo.split('/', 1)
        print("\n[STEP 0.5: Detecting Changes in Existing GitHub Issues]")
        existing_issue_updates = detect_existing_issue_updates(owner, repo, state)
        # Reload state after processing
        state = load_state()

    # STEP 1: Prepare GitHub tasks
    if '/' in args.repo:
        owner, repo = args.repo.split('/', 1)
        print("\n[STEP 1: Scanning GitHub Issues]")
        github_tasks = prepare_github_tasks(owner, repo, state)
        all_tasks.extend(github_tasks)

    # STEP 2: Prepare Vault tasks
    vault_tasks = []
    due_date_updates: List[Dict[str, Any]] = []
    if args.vault_root.exists():
        print("\n[STEP 2: Scanning Vault Files]")
        vault_tasks, due_date_updates = prepare_vault_tasks(args.vault_root, state)
        all_tasks.extend(vault_tasks)

        # STEP 2.5: Update Vault files with generated TaskHashes
        # This writes TaskHash back to the original Daily Note files
        if vault_tasks:
            print("\n[STEP 2.5: Writing TaskHashes back to Vault Files]")
            update_vault_files_with_hashes(args.vault_root, vault_tasks)

        if due_date_updates:
            print(f"\n[STEP 2.6: Due Date Updates Detected ({len(due_date_updates)} task(s))]")
            for upd in due_date_updates:
                print(f"  ↻ {upd['of_task_name']} → dueDate: {upd['new_due_date']}")

    # Save to file for Claude to process
    with open(PREPARE_FILE, 'w') as f:
        json.dump({
            "tasks": all_tasks,
            "existing_issue_updates": existing_issue_updates,
            "due_date_updates": due_date_updates,
            "prepared_at": datetime.now().isoformat(),
            "total_count": len(all_tasks),
            "update_count": len(existing_issue_updates),
            "due_date_update_count": len(due_date_updates),
        }, f, indent=2, ensure_ascii=False)

    # Also save existing issue updates to separate file for clarity
    if existing_issue_updates:
        updates_file = SCRIPT_DIR / "existing_issue_updates.json"
        with open(updates_file, 'w') as f:
            json.dump({
                "updates": existing_issue_updates,
                "prepared_at": datetime.now().isoformat(),
                "total_updates": len(existing_issue_updates)
            }, f, indent=2, ensure_ascii=False)
        print(f"\n✓ Existing Issue Updates: {updates_file}")

    print("\n" + "=" * 70)
    print(f"✓ Prepared {len(all_tasks)} new tasks for sync")
    print(f"✓ Detected {len(existing_issue_updates)} existing Issues with updates")
    print(f"✓ Detected {len(due_date_updates)} due date change(s) for already-synced tasks")
    print(f"Output: {PREPARE_FILE}")
    print("=" * 70)
    if existing_issue_updates:
        print("\n⚠️  ACTION REQUIRED: Review existing_issue_updates.json")
        print("   These Issues have been updated and need sync to OmniFocus")
    print("\nNext: Ask Claude to sync tasks to OmniFocus via MCP")


if __name__ == "__main__":
    main()
