#!/usr/bin/env python3
"""
Obsidian Vault to OmniFocus Sync (Updated)

Syncs tasks from Obsidian vault markdown files to OmniFocus Inbox.
Updates vault files with hash values after successful sync.
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
from omnifocus_applescript import (
    add_task_to_inbox,
    get_omnifocus_available,
)

# State file location
SCRIPT_DIR = Path(__file__).parent
STATE_FILE = SCRIPT_DIR / "sync_state.json"

# Files and patterns to exclude
EXCLUDE_PATTERNS = [
    "x/Templates",
    "x/Scripts",
    ".obsidian",
    "Example",
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
    """Check if a file should be skipped based on exclude patterns."""
    path_str = str(relative_path)

    for pattern in EXCLUDE_PATTERNS:
        if pattern in path_str:
            return True

    if not path_str.endswith('.md'):
        return True

    return False


def find_vault_files(vault_root: Path) -> List[Path]:
    """Find all markdown files in vault that should be scanned."""
    markdown_files = []

    for file_path in vault_root.rglob('*.md'):
        relative_path = file_path.relative_to(vault_root)

        if should_skip_file(relative_path):
            continue

        markdown_files.append(relative_path)

    return sorted(markdown_files)


def extract_tasks(file_path: Path, file_content: str) -> List[Tuple[str, int]]:
    """Extract unchecked tasks from markdown file content."""
    tasks = []
    lines = file_content.split('\n')

    for line_num, line in enumerate(lines, start=1):
        match = re.match(r'- \[ \]\s*(.+?)(?:\s*$)', line)
        if match:
            task_name = match.group(1).strip()
            if task_name:
                tasks.append((task_name, line_num))

    return tasks


def update_vault_file_with_hashes(
    file_path: Path,
    file_content: str,
    tasks_with_hashes: Dict[str, str]
) -> str:
    """
    Update vault file content to include hash values in task names.

    Args:
        file_path: Path to file (for logging)
        file_content: Original file content
        tasks_with_hashes: Map of original task name to hashed name

    Returns:
        Updated file content with hashes added
    """
    new_content = file_content

    # Replace each task line with hash-appended version
    for original_name, hashed_name in tasks_with_hashes.items():
        # Find the task line and replace it
        # Match "- [ ] TASKNAME" and replace with "- [ ] TASKNAME (HASH)"
        pattern = rf'(- \[ \]\s*){re.escape(original_name)}(?=\s*(?:\n|$))'
        replacement = rf'\1{hashed_name}'
        new_content = re.sub(pattern, replacement, new_content)

    return new_content


def sync_vault_tasks(
    vault_root: Path,
    dry_run: bool = False,
    verbose: bool = False
) -> None:
    """Main sync function for Vault tasks."""
    state = load_state()
    omnifocus_available = get_omnifocus_available()

    if not omnifocus_available and not dry_run:
        print("Warning: OmniFocus not available, tasks will be queued only")

    print(f"Scanning vault at {vault_root}...")
    vault_files = find_vault_files(vault_root)
    print(f"Found {len(vault_files)} markdown files\n")

    synced_count = 0
    skipped_count = 0
    total_tasks = 0
    files_to_update = {}  # Track files that need updating

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

        tasks_with_hashes = {}

        for task_name, line_num in tasks:
            if has_hash(task_name):
                task_hash = extract_hash(task_name)
                if task_hash and is_synced(task_hash, state):
                    if verbose:
                        print(f"  ⊘ {task_name} (line {line_num}) - already synced")
                    skipped_count += 1
                    continue
            else:
                source_id = make_vault_source_id(str(file_path), task_name)
                task_hash = compute_hash(source_id)
                task_hash_short = task_hash[:6]

                if is_synced(task_hash, state):
                    if verbose:
                        print(f"  ⊘ {task_name} (line {line_num}) - already synced")
                    skipped_count += 1
                    continue

                task_name_with_hash = append_hash(task_name, source_id)

                if verbose:
                    print(f"  → {task_name_with_hash} (line {line_num})")

                # Add task to OmniFocus
                if omnifocus_available and not dry_run:
                    task_id = add_task_to_inbox(
                        task_name_with_hash,
                        note=source_id
                    )
                elif dry_run:
                    print(f"    [DRY RUN] Would add task: {task_name_with_hash}")

                # Track for file update
                tasks_with_hashes[task_name] = task_name_with_hash

                state[task_hash] = {
                    "source_id": source_id,
                    "of_task_id": task_id if (omnifocus_available and not dry_run) else "pending",
                    "of_task_name": task_name_with_hash,
                    "status": "open",
                    "synced_at": datetime.now().isoformat()
                }

                synced_count += 1

        # Track file for update (if new tasks were synced)
        if tasks_with_hashes:
            files_to_update[file_path] = (content, tasks_with_hashes)

    # Update vault files with hashes (only if not dry-run)
    if files_to_update and not dry_run:
        for file_path, (original_content, tasks_with_hashes) in files_to_update.items():
            full_path = vault_root / file_path
            updated_content = update_vault_file_with_hashes(
                file_path,
                original_content,
                tasks_with_hashes
            )

            try:
                with open(full_path, 'w', encoding='utf-8') as f:
                    f.write(updated_content)
                if verbose:
                    print(f"✓ Updated {file_path} with hashes")
            except Exception as e:
                print(f"Warning: Could not update {file_path}: {e}", file=sys.stderr)

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

    if not args.vault_root.exists():
        print(f"Error: Vault root not found: {args.vault_root}", file=sys.stderr)
        sys.exit(1)

    sync_vault_tasks(args.vault_root, dry_run=args.dry_run, verbose=args.verbose)


if __name__ == "__main__":
    main()
