#!/usr/bin/env python3
"""
Parse OmniFocus dump_database text output into all_tasks_raw.json format.

Handles:
- Project hierarchy (Folder → Project → Task)
- Task names with or without hashes
- Due dates in [DUE:M/D] format
- Parent task relationships via indentation
"""

import re
import json
import sys
from datetime import datetime


def parse_due_date(due_str, current_year=2026):
    """Parse due date from [DUE:M/D] format."""
    if not due_str:
        return None
    match = re.search(r'\[DUE:(\d+)/(\d+)\]', due_str)
    if match:
        month, day = int(match.group(1)), int(match.group(2))
        return f"{current_year:04d}-{month:02d}-{day:02d}"
    return None


def extract_hash(task_name):
    """Extract hash from task name (last 8-digit hex in parentheses)."""
    match = re.search(r'\(([0-9a-f]{8})\)$', task_name)
    return match.group(1) if match else None


def parse_omnifocus_dump(dump_text, sync_state=None):
    """
    Parse OmniFocus dump text output into task list.

    sync_state: optional dict loaded from sync_state.json.
      When provided, added_date is backfilled from the entry's synced_at field
      for tasks that are already tracked (has TaskHash). For new/hashless tasks,
      added_date remains null (scan_omnifocus_inbox.py falls back to today).

    Returns:
    {
      "tasks": [
        {
          "id": sequential_id,
          "name": task_name,
          "due_date": "YYYY-MM-DD" or null,
          "added_date": "YYYY-MM-DD" or null,
          "parent_name": parent_task_or_project_name or null
        },
        ...
      ]
    }
    """
    lines = dump_text.split('\n')
    tasks = []
    task_id = 0
    seen_tasks = set()  # Track duplicates

    # State tracking for hierarchy
    current_folder = None
    current_project = None
    current_task_stack = []  # Stack of (indent_level, task_name) tuples
    project_first_child = {}  # Track first child per project to identify containers

    for line in lines:
        # Skip empty lines and header lines
        if not line.strip() or line.startswith('FORMAT LEGEND') or line.startswith('# OMNIF'):
            continue
        if line.startswith('Dates:') or line.startswith('Status:'):
            continue

        # Determine indentation level
        indent = len(line) - len(line.lstrip())
        indent_level = indent // 3  # Each level is 3 spaces

        # Check what type of line this is
        if line.strip().startswith('F:'):
            # Folder line
            current_folder = re.sub(r'^F:\s*', '', line.strip())
            current_project = None
            current_task_stack = []
            project_first_child = {}
        elif line.strip().startswith('P:'):
            # Project line
            project_line = re.sub(r'^P:\s*', '', line.strip())
            current_project = project_line
            current_task_stack = []
            project_first_child = {}
        elif line.strip().startswith('•'):
            # Task line
            task_line = re.sub(r'^•\s*', '', line.strip())

            # Remove status indicators
            task_line = re.sub(r'\s*#\w+$', '', task_line)

            # Extract due date if present
            due_date = parse_due_date(task_line)

            # Clean task name (remove due date indicators and status)
            clean_name = re.sub(r'\s*\[DUE:[^\]]*\]', '', task_line).strip()

            # Check for duplicates
            task_key = (clean_name, current_project, indent_level)
            if task_key in seen_tasks:
                continue
            seen_tasks.add(task_key)

            # Determine parent based on indent level and context
            # IMPORTANT: Do this BEFORE checking for container, so hierarchy stack is updated
            parent_name = None

            # Parent determination logic:
            # 1. If this is the first direct child of a project (no siblings), parent is the project
            # 2. Otherwise, parent is the most recent task at indent_level - 1
            if current_project and indent_level > 0:
                # Under a project: check if this is a direct child (next indent level after project marker)
                # Find the most recent entry in stack at indent_level - 1
                found_parent = False
                for stack_indent, stack_task in reversed(current_task_stack):
                    if stack_indent == indent_level - 1:
                        parent_name = stack_task
                        found_parent = True
                        break
                # If no parent found in stack but we're directly under the project, parent is the project
                if not found_parent and current_project not in project_first_child:
                    parent_name = current_project
                    project_first_child[current_project] = clean_name
            elif indent_level > 0:
                # Not in a project, but has indent: find parent from task stack
                for stack_indent, stack_task in reversed(current_task_stack):
                    if stack_indent == indent_level - 1:
                        parent_name = stack_task
                        break

            # CRITICAL: Update task stack BEFORE checking for container skip
            # This ensures child tasks can find their parent even if container is skipped
            current_task_stack = [(i, n) for i, n in current_task_stack if i < indent_level]
            current_task_stack.append((indent_level, clean_name))

            # Skip container tasks (same name as parent project)
            # Container format: project name appears as first child with same name
            # NOTE: Stack is already updated above, so children will still find parent
            if current_project and extract_hash(clean_name) == extract_hash(current_project):
                # This is a container task, skip adding it to the task list
                continue

            # Backfill added_date from sync_state if task has a TaskHash
            added_date = None
            task_hash = extract_hash(clean_name)
            if task_hash and sync_state and task_hash in sync_state:
                synced_at = sync_state[task_hash].get("synced_at", "")
                if synced_at:
                    added_date = synced_at[:10]  # "YYYY-MM-DD" from ISO timestamp

            # Add task
            task_id += 1
            tasks.append({
                "id": str(task_id),
                "name": clean_name,
                "due_date": due_date,
                "added_date": added_date,
                "parent_name": parent_name
            })
        elif line.strip() == 'INBOX:':
            # Inbox marker
            current_project = None
            current_folder = None
            current_task_stack = []
            project_first_child = {}
        elif line.strip().startswith('F:') and ':' in line:
            # Folder with name
            current_folder = re.sub(r'^F:\s*', '', line.strip())
            current_project = None

    return {"tasks": tasks}


def main():
    """
    Main entry point.

    Usage:
        python3 parse_omnifocus_dump.py < omnifocus_dump.txt > all_tasks_raw.json
        python3 parse_omnifocus_dump.py --input omnifocus_dump.txt --output all_tasks_raw.json
    """
    import argparse

    parser = argparse.ArgumentParser(
        description='Parse OmniFocus dump_database output into all_tasks_raw.json'
    )
    parser.add_argument('--input', default=None, help='Input file (default: stdin)')
    parser.add_argument('--output', default=None, help='Output file (default: stdout)')

    args = parser.parse_args()

    # Read input
    if args.input:
        with open(args.input, 'r', encoding='utf-8') as f:
            dump_text = f.read()
    else:
        dump_text = sys.stdin.read()

    # Parse
    result = parse_omnifocus_dump(dump_text)

    # Write output
    output_json = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(output_json)
        print(f"✅ Parsed {len(result['tasks'])} tasks to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == '__main__':
    main()
