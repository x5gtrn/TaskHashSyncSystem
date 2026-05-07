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


def parse_omnifocus_dump(dump_text):
    """
    Parse OmniFocus dump text output into task list.

    Returns:
    {
      "tasks": [
        {
          "id": sequential_id,
          "name": task_name,
          "due_date": "YYYY-MM-DD" or null,
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

            # Skip container tasks (same name as parent project)
            # Container format: project name appears as first child with same name
            if current_project and extract_hash(clean_name) == extract_hash(current_project):
                # This is a container task, skip it
                continue

            # Determine parent based on indent level and context
            parent_name = None

            # First, check if this is a direct child of a project
            # Project's first direct child (indent_level 0 under P:) has the project as parent
            if current_project and indent_level == 0:
                # First task under project - might be container
                if current_project not in project_first_child:
                    project_first_child[current_project] = clean_name
                    # This is the first child (container), don't set parent to skip it later
                else:
                    # Subsequent children have the project as parent
                    parent_name = current_project
            elif indent_level == 0:
                # Top-level task in INBOX
                parent_name = None
            else:
                # Child task - parent is the last task at indent_level - 1
                for stack_indent, stack_task in current_task_stack:
                    if stack_indent == indent_level - 1:
                        parent_name = stack_task
                        break

            # Add task
            task_id += 1
            tasks.append({
                "id": str(task_id),
                "name": clean_name,
                "due_date": due_date,
                "parent_name": parent_name
            })

            # Update task stack for hierarchy tracking
            current_task_stack = [(i, n) for i, n in current_task_stack if i < indent_level]
            current_task_stack.append((indent_level, clean_name))
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
