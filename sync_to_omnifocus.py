#!/usr/bin/env python3
"""
Sync prepared tasks to OmniFocus via MCP - Complete Automation

Workflow:
1. Load tasks from tasks_to_sync.json
2. Resolve parentTaskHash to parentTaskId
3. Generate formatted items for batch_add_items MCP call
4. Output pre-existence check requests (Claude MUST verify before adding)
5. Output ready-to-use JSON for MCP execution

PRE-EXISTENCE CHECK (mandatory):
  Before calling batch_add_items, Claude MUST call get_task_by_id for every
  task/project name in the batch to detect existing items in OmniFocus.
  - If found:  record the existing OmniFocus ID in sync_state.json → SKIP creation
  - If absent: proceed with batch_add_items as normal

  This prevents duplicate projects/tasks when sync_state.json is out of sync
  with OmniFocus reality (e.g., after a reset or manual OmniFocus edits).

Usage:
  python3 sync_to_omnifocus.py                    # Default: prepare for MCP
  python3 sync_to_omnifocus.py --dry-run          # Validate without changes
  python3 sync_to_omnifocus.py --verbose          # Show detailed output
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

# Directories
SCRIPT_DIR = Path(__file__).parent
PREPARE_FILE = SCRIPT_DIR / "tasks_to_sync.json"
STATE_FILE = SCRIPT_DIR / "sync_state.json"
RESOLVED_FILE = SCRIPT_DIR / "tasks_resolved.json"
MCP_REQUEST_FILE = SCRIPT_DIR / "mcp_batch_add_request.json"
PRECHECK_FILE = SCRIPT_DIR / "precheck_requests.json"


def load_state() -> Dict[str, Any]:
    """Load sync state from JSON file."""
    if STATE_FILE.exists():
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {}


def load_prepared_tasks() -> List[Dict[str, Any]]:
    """Load prepared tasks from JSON file."""
    if PREPARE_FILE.exists():
        with open(PREPARE_FILE, 'r') as f:
            data = json.load(f)
            return data.get('tasks', [])
    return []


def hash_to_task_id(task_hash: str, state: Dict[str, Any]) -> Optional[str]:
    """Convert TaskHash to OmniFocus task ID using sync_state."""
    if task_hash in state:
        return state[task_hash].get('of_task_id')
    return None


def resolve_parent_task(task: Dict[str, Any], state: Dict[str, Any], verbose: bool = False) -> Dict[str, Any]:
    """
    Resolve parentTaskHash to parentTaskId.

    If parentTaskHash is specified, look it up in sync_state.json
    and return parentTaskId instead.
    """
    if 'parentTaskHash' in task:
        parent_hash = task['parentTaskHash']
        parent_id = hash_to_task_id(parent_hash, state)

        if parent_id and parent_id != 'pending':
            # Remove parentTaskHash and add parentTaskId
            task_copy = task.copy()
            del task_copy['parentTaskHash']
            task_copy['parentTaskId'] = parent_id
            if verbose:
                print(f"  ✓ Resolved parent: {parent_hash} → {parent_id}")
            return task_copy
        else:
            if verbose and not parent_id:
                print(f"  ⚠️  Parent hash '{parent_hash}' not yet synced to OmniFocus", file=sys.stderr)
            # Remove parentTaskHash if not found
            task_copy = task.copy()
            del task_copy['parentTaskHash']
            return task_copy

    return task


def validate_tasks(resolved_tasks: List[Dict[str, Any]], verbose: bool = False) -> tuple:
    """
    Validate resolved tasks before MCP submission.

    Returns: (is_valid: bool, error_list: List[str])
    """
    errors = []

    for i, task in enumerate(resolved_tasks):
        # Check required fields
        if 'type' not in task:
            errors.append(f"Task {i}: missing 'type' field")
        if 'name' not in task:
            errors.append(f"Task {i}: missing 'name' field")

        # Check name format (must contain hash)
        if 'name' in task:
            if '(' not in task['name'] or ')' not in task['name']:
                errors.append(f"Task {i}: name '{task['name']}' missing hash format (hash)")

        # Check projectName for tasks (if parent not specified)
        if task.get('type') == 'task':
            if 'projectName' not in task and 'parentTaskId' not in task:
                errors.append(f"Task {i}: task '{task.get('name')}' has no projectName or parentTaskId")

    if verbose and not errors:
        print("✓ All tasks passed validation")

    return len(errors) == 0, errors


def format_for_mcp(resolved_tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Format resolved tasks into MCP batch_add_items format.
    Note: MCP does not know about hash/source_id, so they are excluded.
    """
    items = []

    for task in resolved_tasks:
        item = {
            'type': task['type'],
            'name': task['name'],
        }

        # Add optional fields
        if 'note' in task and task['note']:
            item['note'] = task['note']

        if 'projectName' in task and task['projectName']:
            item['projectName'] = task['projectName']

        if 'parentTaskId' in task:
            item['parentTaskId'] = task['parentTaskId']

        if 'dueDate' in task and task['dueDate']:
            item['dueDate'] = task['dueDate']

        if 'flagged' in task:
            item['flagged'] = task['flagged']

        items.append(item)

    return items


def generate_precheck_requests(resolved_tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generate a list of get_task_by_id calls Claude MUST run before batch_add_items.

    For each task/project to be added, Claude calls get_task_by_id(taskName=<name>).
    If the item already exists in OmniFocus, Claude:
      1. Records the existing OmniFocus ID in sync_state.json
      2. Removes that item from the batch_add_items call (skip creation)

    This prevents duplicates when sync_state.json is out of sync with OmniFocus.
    """
    checks = []
    for task in resolved_tasks:
        checks.append({
            "task_name": task["name"],
            "task_hash": task.get("hash", ""),
            "task_type": task.get("type", "task"),
            "action_if_found": "record_existing_id_and_skip",
            "action_if_absent": "include_in_batch_add",
        })
    return {
        "instruction": (
            "MANDATORY: Before calling batch_add_items, call get_task_by_id for EACH item below. "
            "If found → record its ID in sync_state.json and EXCLUDE it from batch_add_items. "
            "If absent → include it in batch_add_items as normal."
        ),
        "checks": checks,
        "count": len(checks),
        "generated_at": datetime.now().isoformat(),
    }


def generate_mcp_request(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate formatted MCP batch_add_items request."""
    return {
        "action": "batch_add_items",
        "tool": "mcp__omnifocus-local-server__batch_add_items",
        "items": items,
        "count": len(items),
        "generated_at": datetime.now().isoformat()
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Sync prepared tasks to OmniFocus")
    parser.add_argument('--dry-run', action='store_true', help='Validate without making changes')
    parser.add_argument('--verbose', action='store_true', help='Show detailed output')
    args = parser.parse_args()

    # Load data
    state = load_state()
    tasks = load_prepared_tasks()

    if not tasks:
        print("✓ No tasks to sync")
        return 0

    if args.verbose:
        print(f"📋 Loaded {len(tasks)} tasks from tasks_to_sync.json\n")

    # Resolve parent references
    print(f"🔗 Resolving {len(tasks)} tasks for OmniFocus sync...\n")
    resolved_tasks = []

    for task in tasks:
        resolved_task = resolve_parent_task(task, state, verbose=args.verbose)
        resolved_tasks.append(resolved_task)

        task_name = resolved_task.get('name', 'Unknown')
        task_type = resolved_task.get('type', '?')
        print(f"✓ {task_type.upper()}: {task_name}")

    # Validate tasks
    print(f"\n✅ Validating {len(resolved_tasks)} tasks...\n")
    is_valid, errors = validate_tasks(resolved_tasks, verbose=args.verbose)

    if not is_valid:
        print("❌ Validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    # Save resolved tasks
    with open(RESOLVED_FILE, 'w') as f:
        json.dump({
            "tasks": resolved_tasks,
            "count": len(resolved_tasks),
            "generated_at": datetime.now().isoformat()
        }, f, indent=2, ensure_ascii=False)

    print(f"✓ Saved resolved tasks to: {RESOLVED_FILE}")

    # Format for MCP
    print(f"\n📦 Formatting {len(resolved_tasks)} tasks for MCP submission...\n")
    mcp_items = format_for_mcp(resolved_tasks)
    mcp_request = generate_mcp_request(mcp_items)

    # Generate pre-existence check requests
    precheck = generate_precheck_requests(resolved_tasks)

    if args.dry_run:
        print("🏃 DRY RUN - Would submit the following MCP request:")
        print(f"\nMCP Tool: mcp__omnifocus-local-server__batch_add_items")
        print(f"Items count: {len(mcp_items)}")
        print(f"\n⚠️  PRE-EXISTENCE CHECKS required ({len(precheck['checks'])} items):")
        for c in precheck["checks"]:
            print(f"   → get_task_by_id(taskName='{c['task_name']}')")

        # Save for review
        with open(MCP_REQUEST_FILE, 'w') as f:
            json.dump(mcp_request, f, indent=2, ensure_ascii=False)
        with open(PRECHECK_FILE, 'w') as f:
            json.dump(precheck, f, indent=2, ensure_ascii=False)

        return 0

    # Save pre-existence check requests
    with open(PRECHECK_FILE, 'w') as f:
        json.dump(precheck, f, indent=2, ensure_ascii=False)
    print(f"✓ Pre-existence check requests saved to: {PRECHECK_FILE}")

    # Save MCP request for Claude execution
    with open(MCP_REQUEST_FILE, 'w') as f:
        json.dump(mcp_request, f, indent=2, ensure_ascii=False)

    print(f"✓ MCP request saved to: {MCP_REQUEST_FILE}")
    print(f"\n🎯 Next steps (MANDATORY ORDER):")
    print(f"   1. Claude reads precheck_requests.json")
    print(f"   2. Claude calls get_task_by_id for EACH item")
    print(f"   3. If item exists → record ID in sync_state.json, remove from batch")
    print(f"   4. If item absent → keep in batch")
    print(f"   5. Claude calls batch_add_items with filtered batch")

    return 0


if __name__ == "__main__":
    sys.exit(main())
