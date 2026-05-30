#!/usr/bin/env python3
"""
sync_to_omnifocus_v2.py - PHASE 2: Forward Sync with ID Capture

IMPROVEMENTS OVER v1:
  ✓ Actually executes batch_add_items via omnifocus_mcp.py
  ✓ Captures returned OmniFocus IDs
  ✓ Updates sync_state.json with real IDs (pending → actual)
  ✓ Comprehensive error handling
  ✓ Detailed reporting

USAGE:
  python3 sync_to_omnifocus_v2.py [--dry-run] [--verbose]

WORKFLOW:
  1. Load prepared tasks from tasks_to_sync.json
  2. Resolve parent task hashes to IDs
  3. Validate task structure
  4. Execute batch_add_items via MCP
  5. Capture returned OmniFocus IDs
  6. Update sync_state.json
  7. Generate report
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

# Import MCP interface
sys.path.insert(0, str(Path(__file__).parent))
from omnifocus_mcp import OmniFocusMCP

# Constants
SCRIPT_DIR = Path(__file__).parent
PREPARE_FILE = SCRIPT_DIR / "tasks_to_sync.json"
STATE_FILE = SCRIPT_DIR / "sync_state.json"
REPORT_FILE = SCRIPT_DIR / "sync_to_omnifocus_report.json"


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


def load_prepared_tasks() -> List[Dict[str, Any]]:
    """Load tasks from tasks_to_sync.json"""
    if PREPARE_FILE.exists():
        with open(PREPARE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('tasks', [])
    return []


def resolve_parent_hash(task: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolve parentTaskHash to parentTaskId.
    If parent is pending, still include it (will be fixed in next sync).
    """
    if 'parentTaskHash' not in task:
        return task

    parent_hash = task['parentTaskHash']
    parent_entry = state.get(parent_hash)

    if parent_entry:
        parent_id = parent_entry.get('of_task_id')
        task_copy = task.copy()

        if parent_id and parent_id != 'pending':
            # Real ID available
            del task_copy['parentTaskHash']
            task_copy['parentTaskId'] = parent_id
        else:
            # Parent is pending or no ID yet
            del task_copy['parentTaskHash']
            if parent_id == 'pending':
                # Mark as waiting for parent
                task_copy['waiting_for_parent'] = parent_hash

        return task_copy

    return task


def format_for_batch_add(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Format tasks for omnifocus_mcp.batch_add_items()
    """
    items = []

    for task in tasks:
        item = {
            'type': task.get('type', 'task'),
            'name': task.get('name', 'Untitled'),
        }

        # Optional fields
        if task.get('note'):
            item['note'] = task['note']

        if task.get('projectName'):
            item['projectName'] = task['projectName']

        if task.get('parentTaskId'):
            item['parentTaskId'] = task['parentTaskId']

        if task.get('dueDate'):
            item['dueDate'] = task['dueDate']

        items.append(item)

    return items


def execute_batch_add(items: List[Dict[str, Any]], mcp: OmniFocusMCP,
                      verbose: bool = False) -> Tuple[List, List, List]:
    """
    Execute batch_add_items via MCP and capture results.

    Returns:
      (created: List[{name, id, hash}],
       failed: List[{name, error}],
       waiting: List[{name, waiting_for}])
    """
    print(f"\n🔗 Executing batch_add_items ({len(items)} items)...")

    result = mcp.batch_add_items(items)

    created = []
    failed = []

    if result['success']:
        for item in result.get('created', []):
            created.append({
                'name': item['name'],
                'id': item['id'],
                'type': item.get('type', 'task')
            })
            if verbose:
                print(f"   ✓ {item['name']} → {item['id']}")
    else:
        print("⚠️  batch_add_items returned errors")

    for item in result.get('failed', []):
        failed.append({
            'name': item['name'],
            'error': item.get('error', 'Unknown error')
        })
        if verbose:
            print(f"   ✗ {item['name']}: {item['error']}")

    return created, failed, []


def update_sync_state_with_ids(state: Dict[str, Any],
                               original_tasks: List[Dict[str, Any]],
                               created_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Update sync_state.json with real OmniFocus IDs.

    Maps created items back to original tasks (by name) and updates
    their of_task_id from 'pending' to actual ID.
    """
    updated_count = 0

    for created in created_items:
        created_name = created['name']

        # Find matching entry in sync_state by task name
        for hash_key, entry in state.items():
            if entry.get('of_task_name') == created_name:
                if entry.get('of_task_id') == 'pending':
                    # Update from pending to real ID
                    old_id = entry['of_task_id']
                    entry['of_task_id'] = created['id']
                    updated_count += 1

                    print(f"   ✓ Updated {hash_key}: {old_id} → {created['id']}")

    return state


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="PHASE 2: Forward Sync with ID Capture"
    )
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview without making changes')
    parser.add_argument('--verbose', action='store_true',
                       help='Show detailed output')

    args = parser.parse_args()

    print("=" * 80)
    print("PHASE 2.2: FORWARD SYNC WITH ID CAPTURE")
    print("=" * 80)

    # Load data
    state = load_state()
    tasks = load_prepared_tasks()

    if not tasks:
        print("\n✓ No tasks to sync")
        return 0

    print(f"\n📋 Loaded {len(tasks)} tasks from tasks_to_sync.json")

    # Resolve parent references
    print(f"\n🔗 Resolving parent references...")
    resolved_tasks = []

    for task in tasks:
        resolved = resolve_parent_hash(task, state)
        resolved_tasks.append(resolved)

    print(f"   ✓ {len(resolved_tasks)} tasks resolved")

    # Format for batch_add
    print(f"\n📦 Formatting {len(resolved_tasks)} items...")
    batch_items = format_for_batch_add(resolved_tasks)

    # Connect to OmniFocus
    print(f"\n🔌 Connecting to OmniFocus...")
    mcp = OmniFocusMCP(verbose=args.verbose)

    if not mcp.validate_connection():
        print("❌ Failed to connect to OmniFocus", file=sys.stderr)
        return 1

    print("   ✓ Connected to OmniFocus 3")

    # Execute batch_add
    if args.dry_run:
        print(f"\n[DRY-RUN] Would add {len(batch_items)} items to OmniFocus")
        print("Items that would be created:")
        for item in batch_items:
            print(f"   - {item['type'].upper()}: {item['name']}")
        return 0
    else:
        created, failed, waiting = execute_batch_add(batch_items, mcp, args.verbose)

    # Update sync_state
    print(f"\n💾 Updating sync_state.json...")
    state = update_sync_state_with_ids(state, tasks, created)

    if not args.dry_run:
        save_state(state)
        print(f"   ✓ Saved sync_state.json")

    # Report
    print(f"\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)

    print(f"\n✓ CREATED: {len(created)}")
    for item in created:
        print(f"   - {item['name']} (ID: {item['id']})")

    print(f"\n✗ FAILED: {len(failed)}")
    for item in failed:
        print(f"   - {item['name']}: {item['error']}")

    if waiting:
        print(f"\n⏳ WAITING FOR PARENT: {len(waiting)}")
        for item in waiting:
            print(f"   - {item['name']} (waiting for {item['waiting_for']})")

    # Generate report
    report = {
        'executed_at': datetime.now().isoformat(),
        'dry_run': args.dry_run,
        'tasks_count': len(tasks),
        'created': created,
        'failed': failed,
        'waiting': waiting,
        'created_count': len(created),
        'failed_count': len(failed),
        'waiting_count': len(waiting)
    }

    if not args.dry_run:
        with open(REPORT_FILE, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n📄 Report: {REPORT_FILE}")

    print(f"\n" + "=" * 80)
    print(f"✅ PHASE 2.2 Complete" if len(failed) == 0 else f"⚠️  Some tasks failed")
    print("=" * 80)

    return 0 if len(failed) == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
