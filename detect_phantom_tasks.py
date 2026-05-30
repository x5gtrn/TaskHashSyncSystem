#!/usr/bin/env python3
"""
detect_phantom_tasks.py - Identify and Clean Phantom Pending Tasks

PURPOSE:
  Detect which pending tasks (of_task_id='pending') actually exist in OmniFocus
  and which are phantoms that should be removed.

PROCESS:
  1. Load sync_state.json
  2. For each entry with of_task_id='pending':
     a. Query OmniFocus to find task by name
     b. If found → update with real ID, mark as 'confirmed'
     c. If not found → mark as 'phantom' (to be removed)
  3. Generate report: confirmed vs phantom
  4. Optionally auto-remove phantom entries

USAGE:
  python3 detect_phantom_tasks.py [--dry-run] [--remove-phantoms] [--verbose]

  --dry-run          Preview changes without writing
  --remove-phantoms  Actually delete phantom entries from sync_state.json
  --verbose          Show detailed output for each task
"""

import json
import sys
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any

# Constants
SCRIPT_DIR = Path(__file__).parent
STATE_FILE = SCRIPT_DIR / "sync_state.json"
REPORT_FILE = SCRIPT_DIR / "phantom_detection_report.json"


def load_state() -> Dict[str, Any]:
    """Load sync_state.json"""
    if not STATE_FILE.exists():
        print(f"ERROR: {STATE_FILE} not found")
        sys.exit(1)
    with open(STATE_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_state(state: Dict[str, Any]) -> None:
    """Save updated sync_state.json"""
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def query_omnifocus_by_name(task_name: str) -> Optional[str]:
    """
    Query OmniFocus for a task by name using JXA.
    Returns OmniFocus task ID if found, None otherwise.
    """
    jxa_script = f"""
(function() {{
    const app = Application('OmniFocus 3');
    app.includeStandardAdditions = true;

    const allTasks = [
        ...app.defaultDocument.inboxTasks(),
        ...app.defaultDocument.projects().flatMap(p => [
            ...p.tasks(),
            ...p.tasks().flatMap(t => t.tasks())
        ])
    ];

    for (let task of allTasks) {{
        if (task.name() === '{task_name}') {{
            return task.id();
        }}
    }}
    return null;
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

        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return None
    except Exception as e:
        # JXA failed, return None (not found)
        return None


def detect_omnifocus_tasks_from_dump() -> Dict[str, str]:
    """
    Fallback: Parse omnifocus_dump.txt to get task names.
    Returns: {task_name: "found"}
    """
    dump_file = SCRIPT_DIR / "omnifocus_dump.txt"
    if not dump_file.exists():
        return {}

    task_names = {}
    with open(dump_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # Parse task lines (start with "- ")
            if line.startswith("- "):
                # Remove checkbox and clean up
                task_name = line.replace("- [ ]", "").replace("- [x]", "").strip()
                if task_name:
                    task_names[task_name] = "found"

    return task_names


def run_detection(verbose: bool = False) -> Tuple[List[Dict], List[Dict]]:
    """
    Detect phantom vs confirmed pending tasks.

    Returns:
      (confirmed: List[{hash, name, actual_id}],
       phantom: List[{hash, name}])
    """
    state = load_state()
    confirmed = []
    phantom = []

    # Get all OmniFocus task names from dump (fallback)
    omnifocus_names = detect_omnifocus_tasks_from_dump()

    pending_entries = [
        (hash_key, entry) for hash_key, entry in state.items()
        if entry.get('of_task_id') == 'pending'
    ]

    print(f"\n🔍 Detecting phantom tasks...")
    print(f"   Total pending entries: {len(pending_entries)}\n")

    for hash_key, entry in pending_entries:
        task_name = entry.get('of_task_name', 'UNKNOWN').strip()
        task_type = entry.get('task_type', '?')

        # Clean task name (remove hash if present)
        clean_name = task_name.split('(')[0].strip()

        if verbose:
            print(f"   Checking: {clean_name} ({task_type})")

        # Try JXA first
        actual_id = query_omnifocus_by_name(clean_name)

        # If JXA fails, check omnifocus_dump.txt
        if not actual_id and clean_name in omnifocus_names:
            actual_id = "found_in_dump"

        if actual_id:
            confirmed.append({
                'hash': hash_key,
                'name': clean_name,
                'actual_id': actual_id,
                'task_name': task_name,
                'task_type': task_type
            })
            if verbose:
                print(f"      ✓ FOUND → ID: {actual_id}\n")
        else:
            phantom.append({
                'hash': hash_key,
                'name': clean_name,
                'task_name': task_name,
                'task_type': task_type
            })
            if verbose:
                print(f"      ✗ NOT FOUND (phantom)\n")

    return confirmed, phantom


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Detect and clean phantom pending tasks"
    )
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview changes without writing')
    parser.add_argument('--remove-phantoms', action='store_true',
                       help='Actually delete phantom entries from sync_state.json')
    parser.add_argument('--verbose', action='store_true',
                       help='Show detailed output')

    args = parser.parse_args()

    print("=" * 78)
    print("DETECT PHANTOM TASKS - Emergency Cleanup (PHASE 1.1)")
    print("=" * 78)

    # Run detection
    confirmed, phantom = run_detection(verbose=args.verbose)

    # Report
    print("\n" + "=" * 78)
    print("RESULTS")
    print("=" * 78)

    print(f"\n✓ CONFIRMED (exist in OmniFocus): {len(confirmed)}")
    for item in confirmed:
        print(f"   - {item['name']} ({item['hash']})")
        if args.verbose:
            print(f"     └─ actual_id: {item['actual_id']}")

    print(f"\n✗ PHANTOM (do not exist): {len(phantom)}")
    for item in phantom:
        print(f"   - {item['name']} ({item['hash']})")
        if args.verbose:
            print(f"     └─ type: {item['task_type']}")

    # Generate report
    report = {
        'detected_at': datetime.now().isoformat(),
        'confirmed': confirmed,
        'phantom': phantom,
        'confirmed_count': len(confirmed),
        'phantom_count': len(phantom)
    }

    if not args.dry_run:
        with open(REPORT_FILE, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n📄 Report saved to: {REPORT_FILE}")

    # Update sync_state if requested
    if args.remove_phantoms and phantom:
        if args.dry_run:
            print(f"\n[DRY-RUN] Would remove {len(phantom)} phantom entries")
        else:
            state = load_state()

            print(f"\n🗑️  Removing {len(phantom)} phantom entries from sync_state...")
            for item in phantom:
                hash_key = item['hash']
                if hash_key in state:
                    del state[hash_key]
                    print(f"   ✓ Deleted: {item['name']}")

            save_state(state)
            print(f"\n✅ Updated sync_state.json")

    # Suggest next steps
    print("\n" + "=" * 78)
    print("NEXT STEPS")
    print("=" * 78)

    if confirmed:
        print(f"\n1️⃣  For {len(confirmed)} confirmed tasks:")
        print(f"   Run: python3 {SCRIPT_DIR}/detect_phantom_tasks.py --update-ids")
        print(f"   (This will update their of_task_id with actual IDs)")

    if phantom:
        print(f"\n2️⃣  For {len(phantom)} phantom tasks:")
        print(f"   Run: python3 {SCRIPT_DIR}/detect_phantom_tasks.py --remove-phantoms")
        print(f"   (This will delete them from sync_state.json)")

    print(f"\n3️⃣  Then run Phase 1.2: emergency_hash_inbox_tasks.py")
    print(f"   to hash any remaining unhashed tasks in OmniFocus Inbox")

    return 0


if __name__ == '__main__':
    sys.exit(main())
