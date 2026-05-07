#!/usr/bin/env python3
"""
scan_omnifocus_inbox.py - OmniFocus All-Tasks → Vault/GitHub Sync

Scans ALL OmniFocus tasks (Inbox + all Projects) for TaskHash-less tasks
and routes them to the correct destination based on parent Project info:

  1. Extract all tasks without a TaskHash from the full OmniFocus database
  2. For each hashless task, inspect its parent Project:
     - Parent Project HAS a TaskHash (= GitHub Issue Project)
       → classify as github_issue_child → add to GitHub Issue body
     - Parent Project has NO TaskHash (= native OmniFocus project like "Later")
       OR task has no parent (= Inbox task)
       → classify as vault_task → add to today's Vault Daily Note
  3. Generate TaskHash for each classified task
  4. Write sync_state.json, inbox_rename_requests.json, github_issue_additions.json

Usage:
  python3 scan_omnifocus_inbox.py --tasks all_tasks_raw.json [--date YYYY-MM-DD] [--dry-run] [--verbose]
  python3 scan_omnifocus_inbox.py --inbox-tasks inbox_tasks_raw.json  # deprecated alias

Input (all_tasks_raw.json) is created by Claude from mcp__omnifocus-local-server__dump_database.
Claude normalizes the raw dump into the following format:
  {
    "fetched_at": "2026-05-06T12:00:00",
    "tasks": [
      {
        "id": "OFTaskID123",
        "name": "Buy groceries",
        "note": "",
        "due_date": null,
        "parent_name": "Later"
      }
    ]
  }
  parent_name = name of the containing Project (omit or null for true Inbox tasks)

Output:
  - inbox_rename_requests.json: edit_item calls for Claude to rename OmniFocus tasks
  - github_issue_additions.json: tasks to be added to GitHub Issue bodies
  - sync_state.json: updated with new entries
"""

import argparse
import json
import sys
import subprocess
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

# Resolve imports relative to this script's directory
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from task_hash import compute_hash, make_vault_source_id, make_github_source_id, has_hash, remove_hash, extract_hash

# ─── Constants ────────────────────────────────────────────────────────────────

VAULT_ROOT = Path("/Users/x5gtrn/Library/Mobile Documents/iCloud~md~obsidian/Documents/LIFE")
STATE_FILE = SCRIPT_DIR / "sync_state.json"
RENAME_REQUESTS_FILE = SCRIPT_DIR / "inbox_rename_requests.json"
GITHUB_ADDITIONS_FILE = SCRIPT_DIR / "github_issue_additions.json"
ALL_TASKS_FILE = SCRIPT_DIR / "all_tasks_raw.json"

# GitHub config
GITHUB_OWNER = "x5gtrn"
GITHUB_REPO = "LIFE"


# ─── State I/O ────────────────────────────────────────────────────────────────

def load_state() -> Dict[str, Any]:
    """Load sync_state.json or return empty dict."""
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: Dict[str, Any]) -> None:
    """Write sync_state.json with pretty formatting."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ─── Input Loading ────────────────────────────────────────────────────────────

def load_tasks(path: Path) -> List[Dict]:
    """Load OmniFocus tasks from all_tasks_raw.json (or inbox_tasks_raw.json).

    Claude normalizes dump_database() output into this format before calling the script:
      {"tasks": [{"id": "...", "name": "...", "due_date": null, "parent_name": "ProjectName"}, ...]}

    Also accepts a plain list:
      [{"id": "...", "name": "...", ...}, ...]
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Tasks file not found: {path}\n"
            "Create it by calling mcp__omnifocus-local-server__dump_database,\n"
            "normalizing all incomplete tasks with parent_name, and saving as all_tasks_raw.json."
        )
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Accept dict wrapper or plain list
    if isinstance(data, dict):
        tasks = data.get("tasks", [])
    elif isinstance(data, list):
        tasks = data
    else:
        tasks = []
    return tasks


# Keep deprecated name as alias for backward compatibility
def load_inbox_tasks(path: Path) -> List[Dict]:
    """Deprecated: use load_tasks() instead."""
    return load_tasks(path)


# ─── Parent Task Detection ────────────────────────────────────────────────────

def classify_task_by_parent(
    task: Dict[str, Any],
    state: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Classify a TaskHash-less task based on its parent.

    Returns dict with:
      {
        "task": original task dict,
        "classification": "github_issue_child" | "vault_task",
        "parent_name": str or None,
        "parent_hash": str or None,
        "parent_source_id": str or None,
        "issue_number": int or None  (if github_issue_child)
      }
    """
    parent_id = task.get("parent_id")
    parent_name = task.get("parent_name")

    result = {
        "task": task,
        "classification": "vault_task",
        "parent_name": parent_name,
        "parent_hash": None,
        "parent_source_id": None,
        "issue_number": None,
    }

    # If no parent info, return as vault_task
    if not parent_name:
        return result

    # Extract hash from parent name if present
    parent_hash = extract_hash(parent_name)
    result["parent_hash"] = parent_hash

    # Check if parent hash is a GitHub Issue Project
    if parent_hash and parent_hash in state:
        parent_entry = state[parent_hash]
        source_id = parent_entry.get("source_id", "")
        task_type = parent_entry.get("task_type", "")

        # If parent is a github_project, classify this task as github_issue_child
        if task_type == "github_project" and source_id.startswith("github:"):
            result["classification"] = "github_issue_child"
            result["parent_source_id"] = source_id

            # Extract issue number from source_id
            # Format: github:owner/repo#issue_num:title
            try:
                parts = source_id.split("#")
                if len(parts) >= 2:
                    issue_str = parts[1].split(":")[0]
                    result["issue_number"] = int(issue_str)
            except (ValueError, IndexError):
                pass

    return result


# ─── Task Detection ───────────────────────────────────────────────────────────

def detect_new_tasks(inbox_tasks: List[Dict], state: Dict[str, Any]) -> List[Dict]:
    """
    Filter inbox tasks to only those that need processing:
      - No TaskHash in name (has_hash returns False)
      - Not yet tracked in sync_state.json as a source_id

    Returns list of unprocessed tasks.
    """
    # Build a set of base task names already tracked in state
    tracked_names = set()
    for entry in state.values():
        source_id = entry.get("source_id", "")
        # source_id format: "vault:path/to/file.md:task_name" or "github:..."
        parts = source_id.split(":")
        if len(parts) >= 3:
            tracked_names.add(parts[-1].strip())

    new_tasks = []
    for task in inbox_tasks:
        name = task.get("name", "").strip()
        if not name:
            continue

        # Skip if already has a TaskHash in the name
        if has_hash(name):
            continue

        # Skip Project container tasks (OmniFocus pattern: task name == project name).
        # Every OmniFocus Project has an identically-named first child that acts as a
        # container; it must NEVER receive a TaskHash or appear in the Vault Daily Note.
        # Detection: remove_hash(task_name).strip() == remove_hash(parent_name).strip()
        parent_name = task.get("parent_name", "")
        if parent_name:
            task_clean = remove_hash(name).strip()
            parent_clean = remove_hash(parent_name).strip()
            if task_clean == parent_clean:
                continue  # This is a container task, not real work

        # Skip if base name is already tracked in state
        clean_name = remove_hash(name).strip()
        if clean_name in tracked_names:
            continue

        new_tasks.append(task)

    return new_tasks


# ─── Classification & Routing ─────────────────────────────────────────────────

def classify_and_route_tasks(
    new_tasks: List[Dict],
    state: Dict[str, Any],
    daily_note_relative_path: str
) -> Tuple[List[Dict], List[Dict]]:
    """
    Classify TaskHash-less tasks and route them to either GitHub or Vault.

    Returns:
      (github_tasks, vault_tasks)
      where each is enriched with classification and routing info.
    """
    github_tasks = []
    vault_tasks = []

    for task in new_tasks:
        classification = classify_task_by_parent(task, state)

        if classification["classification"] == "github_issue_child":
            github_tasks.append(classification)
        else:
            vault_tasks.append(classification)

    return github_tasks, vault_tasks


# ─── Hash Generation ──────────────────────────────────────────────────────────

def generate_github_task_hashes(
    github_tasks: List[Dict],
) -> List[Dict]:
    """
    Generate TaskHash for GitHub Issue child tasks.

    Each result contains:
      - classification info (parent, issue_number, etc.)
      - task_hash, source_id, new_name
    """
    enriched = []
    for item in github_tasks:
        task = item["task"]
        original_name = task["name"].strip()
        issue_num = item["issue_number"]

        # Generate source_id for this GitHub task
        source_id = make_github_source_id(GITHUB_OWNER, GITHUB_REPO, issue_num, original_name)
        task_hash = compute_hash(source_id)
        new_name = f"{original_name} ({task_hash})"

        enriched.append({
            **item,  # Keep classification info
            "original_name": original_name,
            "new_name": new_name,
            "task_hash": task_hash,
            "source_id": source_id,
            "of_task_id": task.get("id", ""),
            "due_date": task.get("due_date"),
        })

    return enriched


def generate_vault_task_hashes(
    vault_tasks: List[Dict],
    daily_note_relative_path: str
) -> List[Dict]:
    """
    Generate TaskHash for Vault tasks (both TaskHashless Project children and Inbox tasks).

    Each result contains:
      - classification info (parent_name, etc.)
      - task_hash, source_id, new_name
    """
    enriched = []
    for item in vault_tasks:
        task = item["task"]
        original_name = task["name"].strip()

        # Generate source_id for this Vault task
        source_id = make_vault_source_id(daily_note_relative_path, original_name)
        task_hash = compute_hash(source_id)
        new_name = f"{original_name} ({task_hash})"

        enriched.append({
            **item,  # Keep classification info
            "original_name": original_name,
            "new_name": new_name,
            "task_hash": task_hash,
            "source_id": source_id,
            "of_task_id": task.get("id", ""),
            "due_date": task.get("due_date"),
        })

    return enriched


def generate_task_hashes(new_tasks: List[Dict], daily_note_relative_path: str) -> List[Dict]:
    """
    Generate TaskHash for each new task and build enriched task dicts.

    Each result dict contains:
      - original_name: str
      - new_name: str (with hash appended)
      - task_hash: str (8-char hex)
      - source_id: str
      - of_task_id: str (OmniFocus task ID)
      - due_date: str | None
    """
    enriched = []
    for task in new_tasks:
        original_name = task["name"].strip()
        source_id = make_vault_source_id(daily_note_relative_path, original_name)
        task_hash = compute_hash(source_id)
        new_name = f"{original_name} ({task_hash})"

        enriched.append({
            "original_name": original_name,
            "new_name": new_name,
            "task_hash": task_hash,
            "source_id": source_id,
            "of_task_id": task.get("id", ""),
            "due_date": task.get("due_date"),
        })

    return enriched


# ─── Daily Note I/O ───────────────────────────────────────────────────────────

def get_daily_note_path(date_str: str) -> Path:
    """
    Return the absolute path for a Daily Note given 'YYYY-MM-DD'.
    Example: Calendar/Daily/2026/05/2026-05-03.md
    """
    year, month, _ = date_str.split("-")
    return VAULT_ROOT / "Calendar" / "Daily" / year / month / f"{date_str}.md"


def get_daily_note_relative_path(date_str: str) -> str:
    """Return vault-root-relative path for use in make_vault_source_id."""
    year, month, _ = date_str.split("-")
    return f"Calendar/Daily/{year}/{month}/{date_str}.md"


def create_daily_note_content(date_str: str) -> str:
    """Create a new Daily Note with standard frontmatter and section headers."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        f"---\n"
        f"created: {now}\n"
        f"tags:\n"
        f"  - daily\n"
        f"---\n"
        f"\n"
        f"## Tasks\n"
        f"\n"
        f"## Projects\n"
        f"Projects (no TaskHash) - excluded from sync:\n"
    )


def insert_tasks_into_daily_note(content: str, enriched_tasks: List[Dict]) -> str:
    """
    Append new task lines under '## Tasks' section.
    Skips tasks already present (idempotent, compares by base name without hash).
    """
    lines = content.split("\n")

    # Find the ## Tasks section index
    tasks_section_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "## Tasks":
            tasks_section_idx = i
            break

    if tasks_section_idx is None:
        # No ## Tasks section found; append it at end
        lines.append("")
        lines.append("## Tasks")
        tasks_section_idx = len(lines) - 1

    # Find insertion point: after ## Tasks, before next ## section or end
    insert_idx = tasks_section_idx + 1
    while insert_idx < len(lines):
        stripped = lines[insert_idx].strip()
        if stripped.startswith("## "):
            break
        insert_idx += 1

    # Collect existing task base names in this section for deduplication
    existing_names = set()
    for i in range(tasks_section_idx + 1, insert_idx):
        line = lines[i]
        # Match task lines: "- [ ] ..." or "- [x] ..."
        if line.strip().startswith("- ["):
            # Extract name part (after the checkbox)
            task_text = line.strip()[6:].strip()  # Remove "- [ ] " prefix (6 chars)
            existing_names.add(remove_hash(task_text).strip())

    # Build new task lines, skipping duplicates
    new_lines = []
    for task in enriched_tasks:
        base_name = remove_hash(task["new_name"]).strip()
        if base_name not in existing_names:
            new_lines.append(f"- [ ] {task['new_name']}")
            existing_names.add(base_name)

    if not new_lines:
        return content  # Nothing to add

    # Insert lines before the next ## section (or end)
    for offset, line in enumerate(new_lines):
        lines.insert(insert_idx + offset, line)

    return "\n".join(lines)


def write_daily_note(note_path: Path, content: str) -> None:
    """Ensure parent directories exist, then write the Daily Note."""
    note_path.parent.mkdir(parents=True, exist_ok=True)
    with open(note_path, "w", encoding="utf-8") as f:
        f.write(content)


# ─── State Update ─────────────────────────────────────────────────────────────

def build_state_entries(
    github_enriched: List[Dict],
    vault_enriched: List[Dict],
    timestamp: str
) -> Dict[str, Dict]:
    """Build sync_state.json entries for both GitHub and Vault tasks."""
    entries = {}

    # GitHub Issue child tasks
    for task in github_enriched:
        parent_hash = task["parent_hash"]
        entries[task["task_hash"]] = {
            "source_id": task["source_id"],
            "of_task_id": task["of_task_id"],
            "of_task_name": task["new_name"],
            "status": "open",
            "task_type": "github_task",
            "parent_task_hash": parent_hash,
            "synced_at": timestamp,
        }
        if task.get("due_date"):
            entries[task["task_hash"]]["due_date"] = task["due_date"]

    # Vault tasks (includes both TaskHashless Project children and Inbox tasks)
    for task in vault_enriched:
        entries[task["task_hash"]] = {
            "source_id": task["source_id"],
            "of_task_id": task["of_task_id"],
            "of_task_name": task["new_name"],
            "status": "open",
            "task_type": "vault_task",
            "synced_at": timestamp,
        }
        # Only add parent_task_hash if parent is a real task (has hash)
        if task.get("parent_hash"):
            entries[task["task_hash"]]["parent_task_hash"] = task["parent_hash"]

        if task.get("due_date"):
            entries[task["task_hash"]]["due_date"] = task["due_date"]

    return entries


# ─── Rename Requests Output ───────────────────────────────────────────────────

def save_rename_requests(
    github_enriched: List[Dict],
    vault_enriched: List[Dict]
) -> None:
    """
    Write inbox_rename_requests.json for Claude to execute edit_item calls.
    Includes both GitHub and Vault task renames.
    """
    renames = []

    for task in github_enriched:
        renames.append({
            "of_task_id": task["of_task_id"],
            "original_name": task["original_name"],
            "new_name": task["new_name"],
            "task_hash": task["task_hash"],
            "source_id": task["source_id"],
            "classification": "github_issue_child",
            "issue_number": task["issue_number"],
        })

    for task in vault_enriched:
        renames.append({
            "of_task_id": task["of_task_id"],
            "original_name": task["original_name"],
            "new_name": task["new_name"],
            "task_hash": task["task_hash"],
            "source_id": task["source_id"],
            "classification": "vault_task",
            "parent_name": task["parent_name"],
        })

    data = {
        "generated_at": datetime.now().isoformat(),
        "renames": renames,
        "count": len(renames),
    }
    with open(RENAME_REQUESTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def save_github_additions(github_enriched: List[Dict]) -> None:
    """
    Write github_issue_additions.json for Claude to add tasks to GitHub Issues.

    Format:
      {
        "generated_at": "ISO timestamp",
        "additions_by_issue": {
          "2": [
            {
              "task_name": "Apply to Company A",
              "task_hash": "35f7a9d2",
              "source_id": "github:x5gtrn/LIFE#2:Apply to Company A"
            }
          ]
        }
      }
    """
    # Group additions by issue number
    by_issue = {}
    for task in github_enriched:
        issue_num = str(task["issue_number"])
        if issue_num not in by_issue:
            by_issue[issue_num] = []

        by_issue[issue_num].append({
            "task_name": task["original_name"],
            "task_hash": task["task_hash"],
            "source_id": task["source_id"],
            "omnifocus_id": task["of_task_id"],
        })

    data = {
        "generated_at": datetime.now().isoformat(),
        "additions_by_issue": by_issue,
        "total_tasks": len(github_enriched),
    }
    with open(GITHUB_ADDITIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Scan ALL OmniFocus tasks for TaskHash-less items and route to Vault Daily Note or GitHub Issue.\n"
            "Tasks whose parent Project has no TaskHash (or have no parent) → Vault Daily Note.\n"
            "Tasks whose parent Project has a TaskHash (GitHub Issue Project) → GitHub Issue."
        )
    )
    # Primary argument: all tasks from dump_database
    tasks_group = parser.add_mutually_exclusive_group(required=True)
    tasks_group.add_argument(
        "--tasks",
        type=str,
        help=(
            "Path to all_tasks_raw.json — all OmniFocus tasks normalized by Claude from dump_database(). "
            "Format: {\"tasks\": [{\"id\": \"...\", \"name\": \"...\", \"due_date\": null, \"parent_name\": \"ProjectName\"}]}"
        ),
    )
    tasks_group.add_argument(
        "--inbox-tasks",
        type=str,
        help="Deprecated alias for --tasks. Accepts inbox_tasks_raw.json format.",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Override today's date as YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing any files",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output",
    )
    args = parser.parse_args()

    # Determine target date
    target_date = args.date or date.today().isoformat()

    if args.verbose:
        print(f"Target date: {target_date}")
        print(f"Dry run: {args.dry_run}")

    # Resolve input file path (--tasks takes precedence; --inbox-tasks is deprecated alias)
    tasks_path_str = args.tasks or args.inbox_tasks
    tasks_path = Path(tasks_path_str)
    if args.inbox_tasks and not args.tasks:
        print("Warning: --inbox-tasks is deprecated. Use --tasks with all_tasks_raw.json instead.")

    try:
        all_tasks = load_tasks(tasks_path)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1

    state = load_state()

    print(f"Loaded {len(all_tasks)} tasks from OmniFocus (all projects + inbox)")

    # Detect new (untracked) tasks across all projects
    new_tasks = detect_new_tasks(all_tasks, state)

    if not new_tasks:
        print("✓ No new tasks without TaskHash found")
        return 0

    print(f"Found {len(new_tasks)} new task(s) without TaskHash:\n")
    for t in new_tasks:
        parent_info = f" (parent: {t.get('parent_name')})" if t.get('parent_name') else " (Inbox)"
        print(f"  • {t['name']}{parent_info}")
    print()

    # Compute paths
    daily_relative = get_daily_note_relative_path(target_date)
    daily_abs = get_daily_note_path(target_date)

    if args.verbose:
        print(f"Daily Note: {daily_relative}")

    # Classify and route tasks
    github_classified, vault_classified = classify_and_route_tasks(
        new_tasks, state, daily_relative
    )

    print(f"Classification Results:")
    print(f"  📍 GitHub Issue children:  {len(github_classified)} task(s)")
    for item in github_classified:
        print(f"     → Issue #{item['issue_number']}: {item['task']['name']}")
    print(f"  📍 Vault Daily Note tasks: {len(vault_classified)} task(s)")
    for item in vault_classified:
        parent_str = f" [parent: {item['parent_name']}]" if item['parent_name'] else " [Inbox]"
        print(f"     → {item['task']['name']}{parent_str}")
    print()

    # Generate hashes for each classification
    github_enriched = generate_github_task_hashes(github_classified)
    vault_enriched = generate_vault_task_hashes(vault_classified, daily_relative)

    if args.verbose or args.dry_run:
        print("TaskHash assignments (GitHub):")
        for t in github_enriched:
            print(f"  {t['original_name']} → ({t['task_hash']}) [Issue #{t['issue_number']}]")
        print("TaskHash assignments (Vault):")
        for t in vault_enriched:
            print(f"  {t['original_name']} → ({t['task_hash']})")
        print()

    # Update Daily Note (only with Vault tasks)
    if daily_abs.exists():
        with open(daily_abs, "r", encoding="utf-8") as f:
            note_content = f.read()
        if args.verbose:
            print(f"Updating existing Daily Note: {daily_relative}")
    else:
        note_content = create_daily_note_content(target_date)
        if args.verbose:
            print(f"Creating new Daily Note: {daily_relative}")

    updated_content = insert_tasks_into_daily_note(note_content, vault_enriched)

    # Build state entries for both GitHub and Vault
    timestamp = datetime.now().isoformat()
    new_state_entries = build_state_entries(github_enriched, vault_enriched, timestamp)

    if args.dry_run:
        print("─── DRY RUN: Changes that would be made ───\n")

        if github_enriched:
            print(f"[1] GitHub Issues: +{len(github_enriched)} task(s)")
            for t in github_enriched:
                print(f"    Issue #{t['issue_number']}: - [ ] {t['original_name']} ({t['task_hash']})")
            print()

        print(f"[2] Vault Daily Note: {daily_relative}")
        if vault_enriched:
            print(f"    +{len(vault_enriched)} task(s):")
            for t in vault_enriched:
                print(f"      - [ ] {t['new_name']}")
        print()

        print(f"[3] sync_state.json: +{len(new_state_entries)} entries")
        for h, entry in new_state_entries.items():
            print(f"    {h}: {entry['of_task_name']} [{entry['task_type']}]")
        print()

        all_enriched = github_enriched + vault_enriched
        print(f"[4] inbox_rename_requests.json: {len(all_enriched)} rename(s)")
        for t in all_enriched:
            print(f"    {t['original_name']} → {t['new_name']}")

        if github_enriched:
            print()
            print(f"[5] github_issue_additions.json: {len(github_enriched)} addition(s)")

        print("\n(No files written — dry run)")
        return 0

    # Write Daily Note (if there are Vault tasks)
    if vault_enriched:
        write_daily_note(daily_abs, updated_content)
        print(f"✓ Updated Vault Daily Note: {daily_relative} (+{len(vault_enriched)} tasks)")
    else:
        if args.verbose:
            print(f"  (No Vault tasks to add to Daily Note)")

    # Update sync_state.json
    state.update(new_state_entries)
    save_state(state)
    print(f"✓ Updated sync_state.json (+{len(new_state_entries)} entries)")

    # Save rename requests for Claude (all tasks, both GitHub and Vault)
    all_enriched = github_enriched + vault_enriched
    save_rename_requests(github_enriched, vault_enriched)
    print(f"✓ Saved inbox_rename_requests.json ({len(all_enriched)} rename request(s))")

    # Save GitHub additions if any
    if github_enriched:
        save_github_additions(github_enriched)
        print(f"✓ Saved github_issue_additions.json ({len(github_enriched)} addition(s))")

    print()
    print("Next steps:")
    if github_enriched:
        print("  1. Claude reads github_issue_additions.json and adds tasks to GitHub Issues")
        print("  2. Claude reads inbox_rename_requests.json and calls edit_item for OmniFocus tasks")
    else:
        print("  1. Claude reads inbox_rename_requests.json and calls edit_item for OmniFocus tasks")

    return 0


if __name__ == "__main__":
    sys.exit(main())
