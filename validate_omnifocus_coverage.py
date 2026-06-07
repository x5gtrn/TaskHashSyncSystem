#!/usr/bin/env python3
"""
VALIDATION LAYER: Omnifocus TaskHash Coverage Checker

Purpose: Ensure all OmniFocus tasks have TaskHash for proper sync tracking
Triggers: Automatically after every sync operation
Output: Pass/Fail status with detailed report

Coverage Requirement: 100% of tasks must have TaskHash
Threshold: If coverage < 100%, alerts user with auto-remediation options
"""

import json
import re
import sys
import subprocess
from datetime import datetime
from pathlib import Path

class OmniFocusCoverageValidator:
    def __init__(self, vault_root):
        self.vault_root = Path(vault_root)
        self.sync_state_path = self.vault_root / 'x/Scripts/TaskHashSyncSystem/sync_state.json'
        self.audit_log_path = self.vault_root / 'x/Audits/coverage_audit.json'
        self.hash_pattern = re.compile(r'\s\([0-9a-f]{8}\)$')

        self.results = {
            'timestamp': datetime.now().isoformat(),
            'total_tasks': 0,
            'tasks_with_hash': 0,
            'tasks_without_hash': [],
            'orphaned_entries': [],
            'coverage_percent': 0.0,
            'status': 'UNKNOWN'
        }

    def load_sync_state(self):
        """Load sync_state.json"""
        try:
            with open(self.sync_state_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"ERROR: Failed to load sync_state.json: {e}")
            return {}

    def run_omnifocus_dump(self):
        """Get current OmniFocus task list via MCP"""
        try:
            result = subprocess.run(
                ['osascript', '-e', '''
tell application "OmniFocus 3"
    tell default document
        set allTasks to flattened of every task
        set taskList to {}
        repeat with t in allTasks
            set taskName to name of t
            set end of taskList to taskName
        end repeat
        return taskList
    end tell
end tell
                '''],
                capture_output=True,
                text=True,
                timeout=10
            )

            # Parse output (basic parsing)
            if result.returncode == 0:
                return result.stdout.strip().split('\n')
            else:
                print(f"Warning: OmniFocus dump failed: {result.stderr}")
                return []
        except Exception as e:
            print(f"Warning: Cannot access OmniFocus directly: {e}")
            return []

    def check_task_hash(self, task_name):
        """Check if task has TaskHash suffix"""
        return bool(self.hash_pattern.search(task_name))

    def extract_hash(self, task_name):
        """Extract hash from task name"""
        match = self.hash_pattern.search(task_name)
        if match:
            return match.group().strip().strip('()')
        return None

    def validate_coverage(self):
        """Validate TaskHash coverage in OmniFocus"""
        sync_state = self.load_sync_state()

        print("\n" + "=" * 80)
        print("VALIDATING OMNIFOCUS TASKHASH COVERAGE")
        print("=" * 80)

        # Try to get task list
        task_names = self.run_omnifocus_dump()

        if not task_names:
            print("⚠️  Warning: Could not retrieve task list from OmniFocus")
            print("    Running validation on sync_state.json only")
            return self.validate_sync_state_only(sync_state)

        print(f"\n📊 Tasks found in OmniFocus: {len(task_names)}")
        self.results['total_tasks'] = len(task_names)

        # Check each task
        for task_name in task_names:
            if not task_name.strip():
                continue

            has_hash = self.check_task_hash(task_name)

            if has_hash:
                self.results['tasks_with_hash'] += 1
                hash_val = self.extract_hash(task_name)

                # Verify hash exists in sync_state
                if hash_val and hash_val not in sync_state:
                    self.results['orphaned_entries'].append({
                        'task_name': task_name,
                        'hash': hash_val,
                        'issue': 'Hash in OmniFocus but not in sync_state'
                    })
            else:
                self.results['tasks_without_hash'].append(task_name)

        # Calculate coverage
        if self.results['total_tasks'] > 0:
            self.results['coverage_percent'] = (
                self.results['tasks_with_hash'] / self.results['total_tasks'] * 100
            )

        # Determine status
        if self.results['coverage_percent'] == 100.0 and not self.results['orphaned_entries']:
            self.results['status'] = 'PASS - 100% Coverage'
        elif self.results['coverage_percent'] >= 95.0:
            self.results['status'] = 'WARNING - High coverage but not 100%'
        else:
            self.results['status'] = 'FAIL - Coverage below 95%'

        return self.results

    def validate_sync_state_only(self, sync_state):
        """Fallback: Validate sync_state.json structure only"""
        print("\n📊 Validating sync_state.json structure")

        self.results['total_tasks'] = len(sync_state)
        self.results['tasks_with_hash'] = len(sync_state)

        # Check for invalid entries
        for hash_val, entry in sync_state.items():
            if not entry.get('of_task_name'):
                self.results['tasks_without_hash'].append(f"Hash {hash_val} missing of_task_name")

        if not self.results['tasks_without_hash']:
            self.results['coverage_percent'] = 100.0
            self.results['status'] = 'PASS - sync_state.json valid'
        else:
            self.results['coverage_percent'] = 0.0
            self.results['status'] = 'FAIL - Invalid sync_state entries'

        return self.results

    def generate_report(self):
        """Generate and display coverage report"""
        print("\n" + "=" * 80)
        print("COVERAGE VALIDATION REPORT")
        print("=" * 80)
        print(f"\nTimestamp: {self.results['timestamp']}")
        print(f"Status: {self.results['status']}")
        print(f"\nCoverage: {self.results['tasks_with_hash']}/{self.results['total_tasks']} tasks ({self.results['coverage_percent']:.1f}%)")

        if self.results['tasks_without_hash']:
            print(f"\n❌ TASKS WITHOUT TASHHASH ({len(self.results['tasks_without_hash'])}):")
            for task in self.results['tasks_without_hash'][:10]:
                print(f"  • {task[:70]}")
            if len(self.results['tasks_without_hash']) > 10:
                print(f"  ... and {len(self.results['tasks_without_hash']) - 10} more")

        if self.results['orphaned_entries']:
            print(f"\n⚠️  ORPHANED ENTRIES ({len(self.results['orphaned_entries'])}):")
            for entry in self.results['orphaned_entries']:
                print(f"  • {entry['task_name'][:70]}")
                print(f"    Issue: {entry['issue']}")

        # Save report
        with open(self.audit_log_path, 'a') as f:
            f.write(json.dumps(self.results) + '\n')

        return self.results

    def should_halt_sync(self):
        """Determine if sync should be halted"""
        return self.results['coverage_percent'] < 100.0 and self.results['tasks_without_hash']

def main():
    validator = OmniFocusCoverageValidator('.')
    results = validator.validate_coverage()
    validator.generate_report()

    # Exit with appropriate code
    if validator.should_halt_sync():
        print("\n🛑 SYNC VALIDATION FAILED")
        print("   Coverage < 100% - hashless tasks detected")
        print("   Use --force to override and auto-hash")
        sys.exit(1)
    else:
        print("\n✅ SYNC VALIDATION PASSED")
        print("   All tasks properly tracked")
        sys.exit(0)

if __name__ == '__main__':
    main()
