#!/usr/bin/env python3
"""
update_issue_body.py — Safe atomic operations on GitHub Issue body.

PURPOSE:
  Claude MUST use this script instead of calling `gh issue edit --body` directly.
  Direct body construction by Claude risks mixing tasks from different Issues.
  This script fetches the current body and applies ONLY the specified diff operations.

OPERATIONS:
  --add-task          "Task Name (hash)"
  --add-child         "Parent Name (hash)" "Child Name (hash)"
  --remove-task       "hash_value"   (removes the line containing this hash)
  --check-task        "hash_value"   (marks [ ] → [x])
  --uncheck-task      "hash_value"   (marks [x] → [ ])

SAFETY:
  1. Fetches current body from GitHub before any modification
  2. Applies ONLY the requested diff — no other lines are touched
  3. Prints before/after diff and the resulting body for verification
  4. Aborts with error if hash not found (for --remove/--check/--uncheck)
  5. --dry-run flag previews changes without writing

USAGE EXAMPLES:
  # Add a new top-level task
  python3 update_issue_body.py --issue 3 --add-task "新機能実装 (a1b2c3d4)"

  # Add a child task under a parent
  python3 update_issue_body.py --issue 3 \\
      --add-child "バグフィックス (251383dc)" "画面崩れを修正 (e5f6a7b8)"

  # Mark a task as complete
  python3 update_issue_body.py --issue 2 --check-task "3d8c2904"

  # Remove a task by hash
  python3 update_issue_body.py --issue 3 --remove-task "c329bc12"

  # Preview without writing
  python3 update_issue_body.py --issue 3 --remove-task "c329bc12" --dry-run

FORBIDDEN:
  Do NOT call `gh issue edit --body "..."` with a manually constructed body string.
  Always use this script so that only the intended lines are changed.
"""

import argparse
import json
import re
import subprocess
import sys
from typing import Optional


REPO = "x5gtrn/LIFE"
HASH_RE = re.compile(r'\(([a-f0-9]{8})\)')


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

def fetch_body(issue_num: int) -> str:
    result = subprocess.run(
        ['gh', 'issue', 'view', str(issue_num), '--repo', REPO, '--json', 'body'],
        capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout).get('body', '') or ''


def push_body(issue_num: int, new_body: str, dry_run: bool) -> None:
    if dry_run:
        print("[dry-run] Would call: gh issue edit", issue_num, "--body <new_body>")
        return
    subprocess.run(
        ['gh', 'issue', 'edit', str(issue_num), '--repo', REPO, '--body', new_body],
        check=True
    )


# ---------------------------------------------------------------------------
# Body manipulation — all operate on list-of-lines
# ---------------------------------------------------------------------------

def find_line_index(lines: list[str], hash_val: str) -> Optional[int]:
    """Return the index of the line containing (hash_val), or None."""
    for i, line in enumerate(lines):
        if f'({hash_val})' in line:
            return i
    return None


def detect_indent(lines: list[str], parent_hash: str) -> str:
    """Return the indentation of the parent line + 4 spaces for children."""
    for line in lines:
        if f'({parent_hash})' in line:
            m = re.match(r'^(\s*)', line)
            parent_indent = m.group(1) if m else ''
            return parent_indent + '    '
    return '    '


def op_add_task(lines: list[str], task_name: str) -> list[str]:
    """Append a new top-level unchecked task at the end of the body."""
    new_line = f'- [ ] {task_name}'
    lines.append(new_line)
    print(f"  + Added (top-level): {new_line}")
    return lines


def op_add_child(lines: list[str], parent_spec: str, child_name: str) -> list[str]:
    """Insert a child task immediately after the parent line (and its existing children)."""
    # Extract parent hash
    m = HASH_RE.search(parent_spec)
    if not m:
        sys.exit(f"ERROR: No hash found in parent spec: {parent_spec!r}")
    parent_hash = m.group(1)

    parent_idx = find_line_index(lines, parent_hash)
    if parent_idx is None:
        sys.exit(f"ERROR: Parent task hash ({parent_hash}) not found in Issue body.")

    child_indent = detect_indent(lines, parent_hash)
    new_line = f'{child_indent}- [ ] {child_name}'

    # Insert after the parent and all its existing children
    insert_at = parent_idx + 1
    while insert_at < len(lines):
        line = lines[insert_at]
        m_indent = re.match(r'^(\s*)', line)
        line_indent = m_indent.group(1) if m_indent else ''
        # If this line is indented at least as deep as child_indent, it's still a child
        if line.strip() == '' or len(line_indent) >= len(child_indent):
            insert_at += 1
        else:
            break

    lines.insert(insert_at, new_line)
    print(f"  + Added (child of {parent_hash}): {new_line.strip()}")
    return lines


def op_remove_task(lines: list[str], hash_val: str) -> list[str]:
    """Remove the line containing (hash_val). Aborts if not found."""
    idx = find_line_index(lines, hash_val)
    if idx is None:
        sys.exit(f"ERROR: Hash ({hash_val}) not found in Issue body — nothing removed.")
    removed = lines.pop(idx)
    print(f"  - Removed: {removed.strip()}")
    return lines


def op_check_task(lines: list[str], hash_val: str) -> list[str]:
    """Mark [ ] → [x] for the line containing (hash_val)."""
    idx = find_line_index(lines, hash_val)
    if idx is None:
        sys.exit(f"ERROR: Hash ({hash_val}) not found in Issue body.")
    old = lines[idx]
    new = re.sub(r'- \[ \]', '- [x]', old, count=1)
    if old == new:
        print(f"  ~ Already checked: {old.strip()}")
    else:
        lines[idx] = new
        print(f"  ✓ Checked: {new.strip()}")
    return lines


def op_uncheck_task(lines: list[str], hash_val: str) -> list[str]:
    """Mark [x] → [ ] for the line containing (hash_val)."""
    idx = find_line_index(lines, hash_val)
    if idx is None:
        sys.exit(f"ERROR: Hash ({hash_val}) not found in Issue body.")
    old = lines[idx]
    new = re.sub(r'- \[x\]', '- [ ]', old, count=1)
    if old == new:
        print(f"  ~ Already unchecked: {old.strip()}")
    else:
        lines[idx] = new
        print(f"  ○ Unchecked: {new.strip()}")
    return lines


# ---------------------------------------------------------------------------
# Diff display
# ---------------------------------------------------------------------------

def print_diff(before: str, after: str) -> None:
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    print("\n=== DIFF (before → after) ===")
    all_lines = set(before_lines) | set(after_lines)
    for line in before_lines:
        if line not in after_lines:
            print(f"  - {line}")
    for line in after_lines:
        if line not in before_lines:
            print(f"  + {line}")
    if before == after:
        print("  (no changes)")
    print("=== END DIFF ===\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Safe atomic operations on GitHub Issue body.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--issue', type=int, required=True, help='GitHub Issue number')
    parser.add_argument('--add-task', metavar='TASK_NAME',
                        help='Add a new top-level task')
    parser.add_argument('--add-child', nargs=2, metavar=('PARENT_SPEC', 'CHILD_NAME'),
                        help='Add a child task under PARENT_SPEC')
    parser.add_argument('--remove-task', metavar='HASH',
                        help='Remove task by hash value')
    parser.add_argument('--check-task', metavar='HASH',
                        help='Mark task as complete ([ ] → [x])')
    parser.add_argument('--uncheck-task', metavar='HASH',
                        help='Mark task as incomplete ([x] → [ ])')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview changes without writing to GitHub')
    args = parser.parse_args()

    # Require at least one operation
    ops = [args.add_task, args.add_child, args.remove_task,
           args.check_task, args.uncheck_task]
    if not any(ops):
        parser.error("Specify at least one operation (--add-task, --add-child, "
                     "--remove-task, --check-task, --uncheck-task)")

    # Fetch current body
    print(f"Fetching Issue #{args.issue} body from GitHub...")
    original_body = fetch_body(args.issue)
    lines = original_body.splitlines()

    print(f"  Current body ({len(lines)} lines):")
    for l in lines:
        print(f"    {l}")
    print()

    # Apply operations in order
    if args.add_task:
        lines = op_add_task(lines, args.add_task)
    if args.add_child:
        lines = op_add_child(lines, args.add_child[0], args.add_child[1])
    if args.remove_task:
        lines = op_remove_task(lines, args.remove_task)
    if args.check_task:
        lines = op_check_task(lines, args.check_task)
    if args.uncheck_task:
        lines = op_uncheck_task(lines, args.uncheck_task)

    new_body = '\n'.join(lines)

    # Show diff
    print_diff(original_body, new_body)

    print("=== RESULTING BODY ===")
    for l in lines:
        print(f"  {l}")
    print("=== END BODY ===\n")

    # Write
    push_body(args.issue, new_body, args.dry_run)
    if not args.dry_run:
        print(f"✓ Issue #{args.issue} updated successfully.")
    else:
        print("[dry-run] No changes written.")


if __name__ == '__main__':
    main()
