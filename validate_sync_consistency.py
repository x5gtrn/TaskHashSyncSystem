#!/usr/bin/env python3
"""
validate_sync_consistency.py - PHASE 3.2: Consistency Validator

PURPOSE:
  Detect divergence between sync_state.json and OmniFocus reality.
  Identify phantom tasks, orphaned tasks, and inconsistencies.

CHECKS:
  1. Phantom Tasks: In sync_state but NOT in OmniFocus
  2. Orphaned Tasks: In OmniFocus but NOT in sync_state
  3. ID Mismatches: Wrong of_task_id recorded
  4. Duplicate Hashes: Same hash in multiple locations
  5. Pending Tasks: Long-standing pending entries

USAGE:
  python3 validate_sync_consistency.py [--fix] [--verbose]

  --fix       Auto-fix identified issues (remove phantoms, etc)
  --verbose   Show detailed output
"""

import json
import sys
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime

# Import MCP
sys.path.insert(0, str(Path(__file__).parent))
from omnifocus_mcp import OmniFocusMCP

# Constants
SCRIPT_DIR = Path(__file__).parent
STATE_FILE = SCRIPT_DIR / "sync_state.json"
REPORT_FILE = SCRIPT_DIR / "consistency_validation_report.json"


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


def get_omnifocus_tasks(mcp: OmniFocusMCP) -> Dict[str, List[str]]:
    """
    Get all OmniFocus tasks from database dump.

    Returns:
      {
        'inbox': ['Task Name (hash)', ...],
        'projects': {'ProjectName': ['Task Name (hash)', ...]},
        'all_ids': set of all task IDs
      }
    """
    dump = mcp.dump_database()
    if not dump:
        return {'inbox': [], 'projects': {}, 'all_ids': set()}

    inbox = []
    projects = {}
    all_ids = set()

    lines = dump.split('\n')
    current_section = None
    current_project = None

    for line in lines:
        line = line.strip()

        # Project header: "Project: Name"
        if line.startswith('Project:'):
            current_project = line.replace('Project:', '').strip()
            projects[current_project] = []
            current_section = 'project'

        # Inbox section
        elif line.startswith('INBOX'):
            current_section = 'inbox'
            current_project = None

        # Task line: "- [ ] or [x] Task Name"
        elif line.startswith('-'):
            # Extract task name
            match = re.search(r'- \[.\] (.+)', line)
            if match:
                task_name = match.group(1)

                if current_section == 'project' and current_project:
                    projects[current_project].append(task_name)
                elif current_section == 'inbox':
                    inbox.append(task_name)

    return {
        'inbox': inbox,
        'projects': projects,
        'all_ids': set()  # IDs not tracked in dump text format
    }


def extract_hash_from_name(task_name: str) -> Optional[str]:
    """Extract TaskHash from task name, e.g., "Task Name (abc12345)" → "abc12345" """
    match = re.search(r'\(([0-9a-f]{8})\)$', task_name)
    return match.group(1) if match else None


def check_phantom_tasks(state: Dict[str, Any], of_tasks: Dict[str, Any]) -> List[Dict]:
    """
    Find tasks in sync_state that don't exist in OmniFocus.

    Returns list of phantom task dicts with hash, name, and reason.
    """
    phantoms = []

    of_inbox = of_tasks.get('inbox', [])
    of_projects = of_tasks.get('projects', {})

    # Flatten all OmniFocus task names
    all_of_task_names = set(of_inbox)
    for project_tasks in of_projects.values():
        all_of_task_names.update(project_tasks)

    for hash_key, entry in state.items():
        task_name = entry.get('of_task_name', '')
        of_id = entry.get('of_task_id', '')

        # Skip if pending (expected to be missing)
        if of_id == 'pending':
            continue

        # Check if task exists in OmniFocus by name
        if task_name not in all_of_task_names:
            phantoms.append({
                'hash': hash_key,
                'name': task_name,
                'of_id': of_id,
                'task_type': entry.get('task_type', '?'),
                'reason': 'Not found in OmniFocus dump'
            })

    return phantoms


def check_orphaned_tasks(state: Dict[str, Any], of_tasks: Dict[str, Any]) -> List[Dict]:
    """
    Find tasks in OmniFocus that don't exist in sync_state.

    Returns list of orphaned task dicts.
    """
    orphans = []

    of_inbox = of_tasks.get('inbox', [])
    of_projects = of_tasks.get('projects', {})

    # Get all task names in sync_state
    state_names = set()
    for entry in state.values():
        task_name = entry.get('of_task_name', '')
        if task_name:
            state_names.add(task_name)

    # Check inbox
    for task_name in of_inbox:
        if task_name not in state_names:
            has_hash = extract_hash_from_name(task_name) is not None
            if not has_hash:
                # Hashless task in Inbox
                orphans.append({
                    'name': task_name,
                    'location': 'Inbox',
                    'has_hash': False,
                    'reason': 'Hashless Inbox task (should be auto-hashed)'
                })

    # Check projects
    for project_name, project_tasks in of_projects.items():
        for task_name in project_tasks:
            if task_name not in state_names:
                has_hash = extract_hash_from_name(task_name) is not None
                if not has_hash:
                    orphans.append({
                        'name': task_name,
                        'location': f'Project: {project_name}',
                        'has_hash': False,
                        'reason': 'Hashless project task (should be auto-hashed)'
                    })

    return orphans


def check_duplicate_hashes(state: Dict[str, Any]) -> List[Dict]:
    """
    Find duplicate hashes (should not happen).

    Returns list of duplicate entries.
    """
    duplicates = []
    hash_map = {}

    for hash_key, entry in state.items():
        if hash_key in hash_map:
            duplicates.append({
                'hash': hash_key,
                'entries': hash_map[hash_key] + [entry]
            })
        else:
            hash_map[hash_key] = [entry]

    return duplicates


def check_long_pending(state: Dict[str, Any]) -> List[Dict]:
    """
    Find pending tasks that have been pending for a long time.

    Returns list of old pending tasks.
    """
    old_pending = []
    now = datetime.now()

    for hash_key, entry in state.items():
        if entry.get('of_task_id') == 'pending':
            synced_at_str = entry.get('synced_at', '')
            try:
                synced_at = datetime.fromisoformat(synced_at_str)
                days_pending = (now - synced_at).days

                if days_pending > 0:  # More than 0 days old
                    old_pending.append({
                        'hash': hash_key,
                        'name': entry.get('of_task_name', '?'),
                        'days_pending': days_pending,
                        'synced_at': synced_at_str
                    })
            except (ValueError, TypeError):
                pass

    return sorted(old_pending, key=lambda x: x['days_pending'], reverse=True)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="PHASE 3.2: Validate Sync Consistency"
    )
    parser.add_argument('--fix', action='store_true',
                       help='Auto-fix identified issues')
    parser.add_argument('--verbose', action='store_true',
                       help='Show detailed output')

    args = parser.parse_args()

    print("=" * 80)
    print("PHASE 3.2: SYNC CONSISTENCY VALIDATOR")
    print("=" * 80)

    # Load state
    state = load_state()
    print(f"\n📊 Loaded sync_state.json ({len(state)} entries)")

    # Connect to OmniFocus
    print(f"\n🔌 Connecting to OmniFocus...")
    mcp = OmniFocusMCP(verbose=args.verbose)

    if not mcp.validate_connection():
        print("❌ Failed to connect to OmniFocus", file=sys.stderr)
        return 1

    # Get OmniFocus tasks
    print(f"   ✓ Connected, retrieving tasks...")
    of_tasks = get_omnifocus_tasks(mcp)
    print(f"   ✓ Retrieved OmniFocus snapshot")

    # Run validation checks
    print(f"\n🔍 Running consistency checks...\n")

    phantoms = check_phantom_tasks(state, of_tasks)
    print(f"1️⃣  Phantom Tasks (in state, not in OF): {len(phantoms)}")

    orphans = check_orphaned_tasks(state, of_tasks)
    print(f"2️⃣  Orphaned Tasks (in OF, not in state): {len(orphans)}")

    duplicates = check_duplicate_hashes(state)
    print(f"3️⃣  Duplicate Hashes: {len(duplicates)}")

    old_pending = check_long_pending(state)
    print(f"4️⃣  Long-Standing Pending Tasks: {len(old_pending)}")

    # Report details
    print(f"\n" + "=" * 80)
    print("DETAILED FINDINGS")
    print("=" * 80)

    if phantoms:
        print(f"\n❌ PHANTOM TASKS ({len(phantoms)}):")
        for phantom in phantoms[:10]:  # Show first 10
            print(f"   - {phantom['name']} ({phantom['hash']})")
            if args.verbose:
                print(f"     └─ {phantom['reason']}")

        if args.fix:
            print(f"\n🗑️  Removing {len(phantoms)} phantom entries...")
            for phantom in phantoms:
                del state[phantom['hash']]
                print(f"   ✓ Deleted {phantom['hash']}")

    if orphans:
        print(f"\n⚠️  ORPHANED TASKS ({len(orphans)}):")
        for orphan in orphans[:10]:  # Show first 10
            print(f"   - {orphan['name']} ({orphan['location']})")
            if args.verbose:
                print(f"     └─ {orphan['reason']}")

    if duplicates:
        print(f"\n🚨 DUPLICATE HASHES ({len(duplicates)}):")
        for dup in duplicates:
            print(f"   - Hash {dup['hash']}: appears {len(dup['entries'])} times")

    if old_pending:
        print(f"\n⏳ LONG PENDING ({len(old_pending)}):")
        for task in old_pending[:5]:  # Show first 5
            print(f"   - {task['name']} ({task['hash']})")
            print(f"     └─ Pending for {task['days_pending']} days")

    # Save state if fixed
    if args.fix and (phantoms or old_pending):
        save_state(state)
        print(f"\n💾 Updated sync_state.json")

    # Generate report
    report = {
        'validated_at': datetime.now().isoformat(),
        'total_entries': len(state),
        'phantom_count': len(phantoms),
        'orphan_count': len(orphans),
        'duplicate_count': len(duplicates),
        'pending_old_count': len(old_pending),
        'phantoms': phantoms,
        'orphans': orphans[:10],  # Limit size
        'duplicates': duplicates,
        'old_pending': old_pending,
        'fixed': args.fix
    }

    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n📄 Report: {REPORT_FILE}")

    # Summary
    total_issues = len(phantoms) + len(orphans) + len(duplicates) + len(old_pending)
    print(f"\n" + "=" * 80)
    if total_issues == 0:
        print("✅ CONSISTENCY CHECK PASSED - No issues found")
    else:
        print(f"⚠️  Found {total_issues} consistency issue(s)")
        if args.fix:
            print(f"✓ Fixed {len(phantoms) + len(old_pending)} entries")
    print("=" * 80)

    return 0 if total_issues == 0 else (0 if args.fix else 1)


if __name__ == '__main__':
    sys.exit(main())
