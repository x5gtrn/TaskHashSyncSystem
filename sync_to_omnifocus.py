#!/usr/bin/env python3
"""
Sync prepared tasks to OmniFocus via MCP

Converts parentTaskHash to parentTaskId using sync_state.json
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# Directories
SCRIPT_DIR = Path(__file__).parent
PREPARE_FILE = SCRIPT_DIR / "tasks_to_sync.json"
STATE_FILE = SCRIPT_DIR / "sync_state.json"


def load_state() -> Dict[str, Any]:
    """Load sync state from JSON file."""
    if STATE_FILE.exists():
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {}


def hash_to_task_id(task_hash: str, state: Dict[str, Any]) -> Optional[str]:
    """Convert TaskHash to OmniFocus task ID using sync_state."""
    if task_hash in state:
        return state[task_hash].get('of_task_id')
    return None


def load_prepared_tasks() -> list:
    """Load prepared tasks from JSON file."""
    if PREPARE_FILE.exists():
        with open(PREPARE_FILE, 'r') as f:
            data = json.load(f)
            return data.get('tasks', [])
    return []


def resolve_parent_task(task: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolve parentTaskHash to parentTaskId.
    
    If parentTaskHash is specified, look it up in sync_state.json
    and return parentTaskId instead.
    """
    if 'parentTaskHash' in task:
        parent_hash = task['parentTaskHash']
        parent_id = hash_to_task_id(parent_hash, state)
        
        if parent_id:
            # Remove parentTaskHash and add parentTaskId
            task_copy = task.copy()
            del task_copy['parentTaskHash']
            task_copy['parentTaskId'] = parent_id
            return task_copy
        else:
            print(f"⚠️  Warning: parentTaskHash '{parent_hash}' not found in sync_state", file=sys.stderr)
            # Remove parentTaskHash if not found
            task_copy = task.copy()
            del task_copy['parentTaskHash']
            return task_copy
    
    return task


def main():
    state = load_state()
    tasks = load_prepared_tasks()

    if not tasks:
        print("✓ No tasks to sync")
        return

    print(f"📋 Resolving {len(tasks)} tasks for OmniFocus sync...\n")

    resolved_tasks = []
    for task in tasks:
        resolved_task = resolve_parent_task(task, state)
        resolved_tasks.append(resolved_task)

        # Display info
        task_name = resolved_task.get('name', 'Unknown')
        if 'parentTaskId' in resolved_task:
            parent_id = resolved_task['parentTaskId']
            print(f"✓ {task_name}")
            print(f"  Parent ID: {parent_id}")
        else:
            print(f"✓ {task_name}")

    print(f"\n→ Ready to add {len(resolved_tasks)} tasks to OmniFocus")
    print("→ Tasks resolved with parentTaskId references")

    # Save resolved tasks for manual review
    output_file = SCRIPT_DIR / "tasks_resolved.json"
    with open(output_file, 'w') as f:
        json.dump({
            "tasks": resolved_tasks,
            "count": len(resolved_tasks)
        }, f, indent=2, ensure_ascii=False)

    print(f"✓ Saved to: {output_file}")


if __name__ == "__main__":
    main()
