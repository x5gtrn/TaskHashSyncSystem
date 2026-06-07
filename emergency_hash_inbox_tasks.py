#!/usr/bin/env python3
"""
emergency_hash_inbox_tasks.py - Rescue and Hash Unhashed Inbox Tasks

PURPOSE:
  Emergency cleanup: Find any hashless tasks in OmniFocus Inbox,
  generate TaskHashes, update task names, and sync to Vault/GitHub.

PROCESS:
  1. Get all OmniFocus Inbox tasks
  2. Filter for tasks WITHOUT hash (no "(...)" suffix)
  3. For each unhashed task:
     a. Generate TaskHash
     b. Update task name in OmniFocus via JXA
     c. Add to sync_state.json
     d. Route to Vault Daily Note or GitHub Issue

USAGE:
  python3 emergency_hash_inbox_tasks.py [--dry-run] [--verbose]

  --dry-run   Preview changes without writing
  --verbose   Show detailed output
"""

import json
import sys
import subprocess
import re
from pathlib import Path
from datetime import datetime, date
from typing import Dict, List, Optional, Any

# Import from task_hash and system improvements
sys.path.insert(0, str(Path(__file__).parent))
from task_hash import compute_hash, make_vault_source_id, remove_hash
from user_alert_system import UserAlertSystem, AlertSeverity

# Constants
SCRIPT_DIR = Path(__file__).parent
VAULT_ROOT = Path("/Users/x5gtrn/Library/Mobile Documents/iCloud~md~obsidian/Documents/LIFE")
STATE_FILE = SCRIPT_DIR / "sync_state.json"
REPORT_FILE = SCRIPT_DIR / "emergency_hash_report.json"


def load_state() -> Dict[str, Any]:
    """Load sync_state.json"""
    if STATE_FILE.exists():
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_state(state: Dict[str, Any]) -> None:
    """Save sync_state.json"""
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def get_omnifocus_inbox_tasks() -> List[Dict[str, Any]]:
    """
    Get all OmniFocus Inbox tasks using JXA.

    Returns:
      [
        {
          "id": "OFTaskID123",
          "name": "Task Name",
          "has_hash": bool,
          "note": "",
          "added_date": "YYYY-MM-DD" or None
        }
      ]
    """
    jxa_script = """
(function() {
    const app = Application('OmniFocus 3');
    app.includeStandardAdditions = true;

    const tasks = app.defaultDocument.inboxTasks();
    const result = [];

    for (let task of tasks) {
        // Get added date (creation date)
        let addedDate = null;
        try {
            const createdAt = task.creationDate();
            if (createdAt) {
                const year = createdAt.getFullYear();
                const month = String(createdAt.getMonth() + 1).padStart(2, '0');
                const day = String(createdAt.getDate()).padStart(2, '0');
                addedDate = `${year}-${month}-${day}`;
            }
        } catch (e) {
            addedDate = null;
        }

        // Check if name contains hash
        const taskName = task.name();
        const hasHash = /\\([0-9a-f]{8}\\)$/.test(taskName);

        result.push({
            id: task.id(),
            name: taskName,
            has_hash: hasHash,
            note: task.note() || "",
            added_date: addedDate
        });
    }

    return JSON.stringify(result);
})();
"""

    try:
        result = subprocess.run(
            ['osascript', '-l', 'JavaScript', '-'],
            input=jxa_script,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception as e:
        print(f"⚠️  JXA query failed: {e}", file=sys.stderr)

    return []


def rename_omnifocus_task(task_id: str, new_name: str) -> bool:
    """
    Rename OmniFocus task via JXA.

    Args:
      task_id: OmniFocus task ID
      new_name: New name with hash

    Returns:
      True if successful, False otherwise
    """
    jxa_script = f"""
(function() {{
    const app = Application('OmniFocus 3');
    app.includeStandardAdditions = true;

    try {{
        const allTasks = [
            ...app.defaultDocument.inboxTasks(),
            ...app.defaultDocument.projects().flatMap(p => [
                ...p.tasks(),
                ...p.tasks().flatMap(t => t.tasks())
            ])
        ];

        for (let task of allTasks) {{
            if (task.id() === '{task_id}') {{
                task.name = '{new_name}';
                return "success";
            }}
        }}
        return "not_found";
    }} catch (e) {{
        return "error: " + e.message;
    }}
}})();
"""

    try:
        result = subprocess.run(
            ['osascript', '-l', 'JavaScript', '-'],
            input=jxa_script,
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            output = result.stdout.strip()
            return output == "success"
    except Exception as e:
        print(f"⚠️  JXA rename failed: {e}", file=sys.stderr)

    return False


def process_inbox_tasks(dry_run: bool = False, verbose: bool = False) -> Tuple[List, List]:
    """
    Process all Inbox tasks, hash the unhashed ones.

    Returns:
      (processed: List of successfully hashed tasks,
       failed: List of tasks that failed)
    """
    tasks = get_omnifocus_inbox_tasks()
    state = load_state()

    processed = []
    failed = []
    unhashed_count = 0

    print(f"\n📦 Retrieved {len(tasks)} tasks from OmniFocus Inbox")

    for task in tasks:
        if task['has_hash']:
            if verbose:
                print(f"   ✓ Already hashed: {task['name']}")
            continue

        unhashed_count += 1
        task_name = remove_hash(task['name']).strip()

        if verbose:
            print(f"\n   Processing unhashed: {task_name}")

        # Generate TaskHash
        source_id = make_vault_source_id(
            f"Calendar/Daily/{task.get('added_date', str(date.today()))}.md",
            task_name
        )
        task_hash = compute_hash(source_id)

        new_name = f"{task_name} ({task_hash})"

        if verbose:
            print(f"      Hash: {task_hash}")
            print(f"      New name: {new_name}")

        # Rename in OmniFocus
        if not dry_run:
            success = rename_omnifocus_task(task['id'], new_name)
            if not success:
                failed.append({
                    'name': task_name,
                    'hash': task_hash,
                    'reason': 'Failed to rename in OmniFocus'
                })
                print(f"      ✗ Failed to rename")
                continue

        # Add to sync_state
        if task_hash not in state:
            state[task_hash] = {
                'source_id': source_id,
                'of_task_id': task['id'],
                'of_task_name': new_name,
                'status': 'open',
                'synced_at': datetime.now().isoformat(),
                'task_type': 'vault_task',
                'added_date': task.get('added_date')
            }

        processed.append({
            'name': task_name,
            'hash': task_hash,
            'new_name': new_name,
            'of_id': task['id'],
            'added_date': task.get('added_date')
        })

        if verbose:
            print(f"      ✓ Processed")

    if not dry_run and processed:
        save_state(state)

    return processed, failed


def route_to_vault(task_item: Dict) -> bool:
    """
    Add hashed task to appropriate Vault Daily Note.

    Returns True if successful.
    """
    added_date = task_item.get('added_date') or str(date.today())
    daily_note_path = VAULT_ROOT / f"Calendar/Daily/{added_date}.md"

    # Create daily note if it doesn't exist
    if not daily_note_path.exists():
        daily_note_path.parent.mkdir(parents=True, exist_ok=True)
        daily_note_path.write_text(f"# {added_date}\n\n## Tasks\n")

    # Read current content
    content = daily_note_path.read_text()

    # Check if task already exists
    task_line = f"- [ ] {task_item['name']} ({task_item['hash']})"
    if task_line in content:
        return True  # Already exists

    # Find ## Tasks section and append
    if "## Tasks" in content:
        lines = content.split('\n')
        insert_idx = -1

        for i, line in enumerate(lines):
            if line.strip() == "## Tasks":
                insert_idx = i + 1
                break

        if insert_idx >= 0:
            lines.insert(insert_idx, task_line)
            daily_note_path.write_text('\n'.join(lines))
            return True

    return False


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Emergency hash unhashed Inbox tasks"
    )
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview changes without writing')
    parser.add_argument('--verbose', action='store_true',
                       help='Show detailed output')

    args = parser.parse_args()

    print("=" * 78)
    print("EMERGENCY HASH INBOX TASKS - Emergency Cleanup (PHASE 1.2)")
    print("=" * 78)

    # Setup alert system
    alert_system = UserAlertSystem(log_file=str(SCRIPT_DIR / "emergency_hash_alerts.jsonl"))

    # Process tasks
    processed, failed = process_inbox_tasks(dry_run=args.dry_run, verbose=args.verbose)

    # Report
    print("\n" + "=" * 78)
    print("RESULTS")
    print("=" * 78)

    print(f"\n✓ PROCESSED (hashed & added): {len(processed)}")
    for item in processed:
        print(f"   - {item['name']} ({item['hash']})")

    print(f"\n✗ FAILED: {len(failed)}")
    for item in failed:
        print(f"   - {item['name']}: {item['reason']}")

    # Alert on failures
    if failed and not args.dry_run:
        alert_system.alert_rename_failures([
            {
                'task': item['name'],
                'expected': f"{item['name']} ({item['hash']})"
            }
            for item in failed
        ])

    # Route to Vault
    if processed and not args.dry_run:
        print(f"\n📝 Routing to Vault Daily Notes...")
        routed = 0
        for item in processed:
            if route_to_vault(item):
                routed += 1
                if args.verbose:
                    print(f"   ✓ {item['name']} → {item['added_date']}")

        print(f"\n✓ Routed {routed}/{len(processed)} tasks to Vault")

    # Generate report
    report = {
        'executed_at': datetime.now().isoformat(),
        'dry_run': args.dry_run,
        'processed': processed,
        'failed': failed,
        'processed_count': len(processed),
        'failed_count': len(failed)
    }

    if not args.dry_run:
        with open(REPORT_FILE, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n📄 Report saved to: {REPORT_FILE}")

    # Summary
    print("\n" + "=" * 78)
    if args.dry_run:
        print("DRY-RUN: No changes were made")
    else:
        print("✅ Phase 1.2 Complete")
    print("=" * 78)

    return 0 if len(failed) == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
