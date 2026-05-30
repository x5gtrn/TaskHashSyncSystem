#!/usr/bin/env python3
"""
run_full_sync.py - PHASE 4: Complete Sync Pipeline Orchestrator

PURPOSE:
  Execute all sync phases in correct order with proper error handling.
  This is the main entry point for "sync tasks" operations.

PHASES:
  PHASE 1: Emergency Cleanup
    1.1. detect_phantom_tasks.py → identify & remove phantoms
    1.2. emergency_hash_inbox_tasks.py → hash any remaining unhashed tasks

  PHASE 2: MCP Execution Layer
    2.1. omnifocus_mcp.py → MCP interface (used by 2.2)
    2.2. sync_to_omnifocus_v2.py → execute batch_add_items, capture IDs

  PHASE 3: Robust Monitoring
    3.1. scan_omnifocus_inbox_v3.py → detect & hash new unhashed tasks
    3.2. validate_sync_consistency.py → verify state consistency

  PHASE 4: Integration (this script)

USAGE:
  python3 run_full_sync.py [--skip-phase N] [--dry-run] [--verbose]

  --skip-phase 1|2|3  Skip entire phase
  --dry-run           Preview without changes
  --verbose           Show detailed output
"""

import subprocess
import sys
import json
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

# Constants
SCRIPT_DIR = Path(__file__).parent


class SyncPhaseRunner:
    """Orchestrate sync phases"""

    def __init__(self, dry_run: bool = False, verbose: bool = False):
        self.dry_run = dry_run
        self.verbose = verbose
        self.results = []

    def run_script(self, script_name: str, args: List[str] = None) -> bool:
        """
        Run a Python script and capture result.

        Returns True if successful, False otherwise.
        """
        if args is None:
            args = []

        cmd = ['python3', str(SCRIPT_DIR / script_name)] + args

        if self.dry_run:
            cmd.append('--dry-run')

        if self.verbose:
            cmd.append('--verbose')

        print(f"\n   🔧 Running: {script_name}")
        print(f"      Command: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                cwd=str(SCRIPT_DIR),
                capture_output=True,
                text=True,
                timeout=60
            )

            # Show output
            if result.stdout:
                for line in result.stdout.split('\n')[:20]:  # First 20 lines
                    if line.strip():
                        print(f"      {line}")

            if result.returncode != 0:
                print(f"   ❌ Failed (exit code {result.returncode})")
                if result.stderr:
                    print(f"      Error: {result.stderr[:200]}")
                return False

            print(f"   ✓ Success")
            return True

        except subprocess.TimeoutExpired:
            print(f"   ❌ Timeout")
            return False
        except Exception as e:
            print(f"   ❌ Exception: {e}")
            return False

    def run_phase_1(self) -> bool:
        """PHASE 1: Emergency Cleanup"""
        print("\n" + "=" * 80)
        print("PHASE 1: EMERGENCY CLEANUP")
        print("=" * 80)

        steps = [
            ("detect_phantom_tasks.py", ["--remove-phantoms"],
             "Detect and remove phantom tasks"),
            ("emergency_hash_inbox_tasks.py", [],
             "Hash remaining unhashed Inbox tasks"),
        ]

        for script, args, description in steps:
            print(f"\n{description}...")
            if not self.run_script(script, args):
                print(f"⚠️  Phase 1 step failed: {script}")
                return False

        return True

    def run_phase_2(self) -> bool:
        """PHASE 2: MCP Execution Layer"""
        print("\n" + "=" * 80)
        print("PHASE 2: MCP EXECUTION LAYER")
        print("=" * 80)

        # Only run if there are tasks to sync
        prepare_file = SCRIPT_DIR / "tasks_to_sync.json"
        if not prepare_file.exists():
            print("\n⚠️  tasks_to_sync.json not found, skipping Phase 2")
            return True

        with open(prepare_file) as f:
            data = json.load(f)
            task_count = len(data.get('tasks', []))

        if task_count == 0:
            print(f"\n⚠️  No tasks to sync (tasks_to_sync.json is empty), skipping Phase 2")
            return True

        print(f"\nFound {task_count} tasks to sync...")
        if not self.run_script("sync_to_omnifocus_v2.py", []):
            print(f"⚠️  Phase 2 failed")
            return False

        return True

    def run_phase_3(self) -> bool:
        """PHASE 3: Robust Monitoring"""
        print("\n" + "=" * 80)
        print("PHASE 3: ROBUST MONITORING")
        print("=" * 80)

        steps = [
            ("scan_omnifocus_inbox_v3.py", [],
             "Scan and hash new hashless tasks"),
            ("validate_sync_consistency.py", ["--fix"],
             "Validate sync consistency"),
        ]

        for script, args, description in steps:
            print(f"\n{description}...")
            if not self.run_script(script, args):
                print(f"⚠️  Phase 3 step failed: {script}")
                # Don't fail on validation issues
                if "validate" not in script:
                    return False

        return True

    def run_all(self, skip_phases: List[int] = None) -> bool:
        """Run all phases in order"""
        if skip_phases is None:
            skip_phases = []

        print("=" * 80)
        print("FULL SYNC PIPELINE ORCHESTRATOR")
        print("=" * 80)
        print(f"Start time: {datetime.now().isoformat()}")
        print(f"Dry run: {self.dry_run}")

        phases = [
            (1, self.run_phase_1, "Emergency Cleanup"),
            (2, self.run_phase_2, "MCP Execution"),
            (3, self.run_phase_3, "Robust Monitoring"),
        ]

        summary = {
            'start_time': datetime.now().isoformat(),
            'dry_run': self.dry_run,
            'phases': {}
        }

        for phase_num, phase_func, phase_name in phases:
            if phase_num in skip_phases:
                print(f"\n⏭️  Skipping Phase {phase_num}: {phase_name}")
                continue

            print(f"\n{'=' * 80}")
            print(f"PHASE {phase_num}: {phase_name}")
            print(f"{'=' * 80}")

            try:
                success = phase_func()
                summary['phases'][f'phase_{phase_num}'] = {
                    'name': phase_name,
                    'success': success
                }

                if not success:
                    print(f"\n❌ Phase {phase_num} failed, stopping pipeline")
                    summary['end_time'] = datetime.now().isoformat()
                    summary['success'] = False
                    return False

            except Exception as e:
                print(f"\n❌ Exception in Phase {phase_num}: {e}")
                summary['phases'][f'phase_{phase_num}'] = {
                    'name': phase_name,
                    'success': False,
                    'error': str(e)
                }
                return False

        summary['end_time'] = datetime.now().isoformat()
        summary['success'] = True

        # Save summary
        report_file = SCRIPT_DIR / "full_sync_report.json"
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2)

        return True


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="PHASE 4: Full Sync Pipeline Orchestrator"
    )
    parser.add_argument('--skip-phase', type=int, action='append', dest='skip_phases',
                       help='Skip phase 1, 2, or 3')
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview without making changes')
    parser.add_argument('--verbose', action='store_true',
                       help='Show detailed output')

    args = parser.parse_args()

    runner = SyncPhaseRunner(dry_run=args.dry_run, verbose=args.verbose)
    success = runner.run_all(skip_phases=args.skip_phases or [])

    print("\n" + "=" * 80)
    if success:
        print("✅ FULL SYNC PIPELINE COMPLETE")
    else:
        print("❌ FULL SYNC PIPELINE FAILED")
    print("=" * 80)

    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
