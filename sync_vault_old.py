#!/usr/bin/env python3
"""
Obsidian Vault to OmniFocus Sync

Syncs tasks from Obsidian vault markdown files to OmniFocus Inbox.
Each task gets a unique hash for cross-system identification.
"""

import json
import subprocess
import argparse
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any

from task_hash import (
    compute_hash,
    make_vault_source_id,
    append_hash,
    has_hash,
    extract_hash,
)

# State file location
SCRIPT_DIR = Path(__file__).parent
STATE_FILE = SCRIPT_DIR / "sync_state.json"

# Files and patterns to exclude
EXCLUDE_PATTERNS = [
    "x/Templates",
    "x/Scripts",
    ".obsidian",
    "Example",  # Files with Example in name
]


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


def should_skip_file(relative_path: Path) -> bool:
    """
    Check if a file should be skipped based on exclude patterns.

    Args:
        relative_path: Path relative to vault root

    Returns:
        True if file should be skipped, False otherwise
    """
    path_str = str(relative_path)

    for pattern in EXCLUDE_PATTERNS:
        if pattern in path_str:
            return True

    # Also skip files that don't end in .md
    if not path_str.endswith('.md'):
        return True

    return False


def find_vault_files(vault_root: Path) -> List[Path]:
    """
    Find all markdown files in vault that should be scanned.

    Args:
        vault_root: Path to vault root directory

    Returns:
        List of markdown file paths (relative to vault root)
    """
    markdown_files = []

    for file_path in vault_root.rglob('*.md'):
        relative_path = file_path.relative_to(vault_root)

        if should_skip_file(relative_path):
            continue

        markdown_files.append(relative_path)

    return sorted(markdown_files)


def extract_tasks(file_path: Path, file_content: str) -> List[Tuple[str, int]]:
    """
    Extract unchecked tasks from markdown file content.

    Args:
        file_path: Path to file (for logging)
        file_content: File content string

    Returns:
        List of (task_name, line_number) tuples
    """
    tasks = []
    lines = file_content.split('\n')

    for line_num, line in enumerate(lines, start=1):
        # Match "- [ ] TASK_NAME" (unchecked) but skip "- [x]" (completed)
        match = re.match(r'- \[ \]\s*(.+?)(?:\s*$)', line)
        if match:
            task_name = match.group(1).strip()
            if task_name:  # Skip empty tasks
                tasks.append((task_name, line_num))

    return tasks


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


def sync_vault_tasks(
    vault_root: Path,
    dry_run: bool = False,
    verbose: bool = False
) -> None:
    """
    Main sync function for Vault tasks.

    Args:
        vault_root: Path to vault root directory
        dry_run: If True, only show what would be synced
        verbose: If True, show detailed information
    """
    state = load_state()

    print(f"Scanning vault at {vault_root}...")
    vault_files = find_vault_files(vault_root)
    print(f"Found {len(vault_files)} markdown files\n")

    synced_count = 0
    skipped_count = 0
    total_tasks = 0

    for file_path in vault_files:
        full_path = vault_root / file_path


        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"Warning: Could not read {file_path}: {e}", file=sys.stderr)
            continue

        tasks = extract_tasks(file_path, content)
        total_tasks += len(tasks)

        if not tasks:
            continue

        if verbose:
            print(f"Found {len(tasks)} tasks in {file_path}")

        for task_name, line_num in tasks:
            # Check if task already has hash (manual add)
            if has_hash(task_name):
                task_hash = extract_hash(task_name)
                if task_hash and is_synced(task_hash, state):
                    if verbose:
                        print(f"  ⊘ {task_name} (line {line_num}) - already synced")
                    skipped_count += 1
                    continue
            else:
                # Create new hash for task
                source_id = make_vault_source_id(str(file_path), task_name)
                task_hash = compute_hash(source_id)

                if is_synced(task_hash, state):
                    if verbose:
                        print(f"  ⊘ {task_name} (line {line_num}) - already synced")
                    skipped_count += 1
                    continue

                task_name_with_hash = append_hash(task_name, source_id)

                if verbose:
                    print(f"  → {task_name_with_hash} (line {line_num})")

                task_id = add_omnifocus_task(
                    task_name_with_hash,
                    note=source_id,
                    dry_run=dry_run
                )

                state[task_hash] = {
                    "source_id": source_id,
                    "of_task_id": task_id or "pending",
                    "of_task_name": task_name_with_hash,
                    "status": "open",
                    "synced_at": datetime.now().isoformat()
                }

                synced_count += 1

    # Save updated state
    if not dry_run:
        save_state(state)

    print(f"\nResults: {synced_count} new, {skipped_count} skipped")
    print(f"Total tasks scanned: {total_tasks}")
    if dry_run:
        print("(Dry run - no changes made)")


def main():
    parser = argparse.ArgumentParser(
        description="Sync Obsidian Vault tasks to OmniFocus"
    )
    parser.add_argument(
        '--vault-root',
        type=Path,
        default=Path.cwd(),
        help='Path to vault root directory (default: current directory)'
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

    # Verify vault root exists
    if not args.vault_root.exists():
        print(f"Error: Vault root not found: {args.vault_root}", file=sys.stderr)
        sys.exit(1)

    sync_vault_tasks(args.vault_root, dry_run=args.dry_run, verbose=args.verbose)


if __name__ == "__main__":
    main()
