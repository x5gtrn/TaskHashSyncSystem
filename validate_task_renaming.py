#!/usr/bin/env python3
"""
TASK RENAME VALIDATION LAYER
Version: 2.0 (2026-06-07)

Purpose:
  Verify that all intended task renames were actually successful in OmniFocus
  Detect partial failures and provide detailed remediation guidance

Improvements:
  1. Verify each renamed task exists in OmniFocus with hash appended
  2. Detect rename failures early
  3. Generate remediation report for user
  4. Prevent silent failures
"""

import json
import sys
from datetime import datetime
from typing import List, Dict, Optional

class TaskRenameValidator:
    def __init__(self, verbose=True):
        self.verbose = verbose
        self.validation_results = []
        self.failures = []

    def validate_rename(self, original_name: str, expected_hash: str, actual_name_in_omnifocus: str) -> bool:
        """
        Validate that a task was renamed correctly

        Args:
            original_name: Original task name (before rename)
            expected_hash: TaskHash that should be appended
            actual_name_in_omnifocus: Current name in OmniFocus (from API query)

        Returns:
            True if rename successful, False otherwise
        """
        expected_name = f"{original_name} ({expected_hash})"

        is_valid = actual_name_in_omnifocus == expected_name

        result = {
            'original_name': original_name,
            'expected_name': expected_name,
            'actual_name': actual_name_in_omnifocus,
            'expected_hash': expected_hash,
            'status': 'PASS' if is_valid else 'FAIL',
            'timestamp': datetime.now().isoformat()
        }

        self.validation_results.append(result)

        if not is_valid:
            self.failures.append({
                'task': original_name,
                'reason': 'Name mismatch',
                'expected': expected_name,
                'actual': actual_name_in_omnifocus,
                'remediation': f"Rename '{actual_name_in_omnifocus}' to '{expected_name}' in OmniFocus"
            })

        if self.verbose:
            status_icon = "✅" if is_valid else "❌"
            print(f"{status_icon} {original_name[:50]}")
            if not is_valid:
                print(f"   Expected: {expected_name[:60]}")
                print(f"   Actual: {actual_name_in_omnifocus[:60]}")

        return is_valid

    def validate_batch(self, tasks_to_validate: List[Dict]) -> Dict:
        """
        Validate multiple task renames

        Args:
            tasks_to_validate: List of {
                'original_name': str,
                'expected_hash': str,
                'actual_name': str  # Query from OmniFocus API
            }

        Returns:
            Validation report
        """
        print("=" * 80)
        print("TASK RENAME VALIDATION")
        print("=" * 80 + "\n")

        results = {
            'timestamp': datetime.now().isoformat(),
            'total_tasks': len(tasks_to_validate),
            'passed': 0,
            'failed': 0,
            'details': []
        }

        for task in tasks_to_validate:
            is_valid = self.validate_rename(
                task['original_name'],
                task['expected_hash'],
                task['actual_name']
            )

            if is_valid:
                results['passed'] += 1
            else:
                results['failed'] += 1

            results['details'].append({
                'task': task['original_name'],
                'status': 'PASS' if is_valid else 'FAIL'
            })

        # Summary
        print("\n" + "=" * 80)
        print("VALIDATION SUMMARY")
        print("=" * 80)
        print(f"Total tasks: {results['total_tasks']}")
        print(f"✅ Passed: {results['passed']}")
        print(f"❌ Failed: {results['failed']}")
        print(f"Success rate: {results['passed'] / results['total_tasks'] * 100:.1f}%")

        if self.failures:
            print("\n" + "=" * 80)
            print("⚠️  FAILURES DETECTED - REMEDIATION REQUIRED")
            print("=" * 80)
            for failure in self.failures:
                print(f"\nTask: {failure['task']}")
                print(f"Expected: {failure['expected']}")
                print(f"Actual: {failure['actual']}")
                print(f"Action: {failure['remediation']}")

        results['failures'] = self.failures
        results['all_passed'] = results['failed'] == 0

        return results

    def generate_remediation_script(self) -> str:
        """
        Generate Python code to remediate failed renames
        """
        if not self.failures:
            return "# No failures to remediate"

        script = """#!/usr/bin/env python3
'''
REMEDIATION SCRIPT: Fix Failed Task Renames
Generated: {}
'''

# These tasks need to be renamed in OmniFocus

failed_renames = [
""".format(datetime.now().isoformat())

        for failure in self.failures:
            script += f"""    {{
        'original': "{failure['task']}",
        'expected': "{failure['expected']}",
        'action': "Rename in OmniFocus UI and run next sync"
    }},
"""

        script += """]

# Manual remediation steps:
# 1. Open OmniFocus
# 2. For each task in failed_renames:
#    - Search for the task
#    - Edit name to match 'expected'
#    - Confirm save
# 3. Run: sync tasks

print(f"Found {len(failed_renames)} tasks requiring manual rename")
for task in failed_renames:
    print(f"  • {task['original']} → {task['expected']}")
"""

        return script

# Example usage
if __name__ == '__main__':
    print("\n📋 EXAMPLE: Validating task renames\n")

    # Simulated OmniFocus query results
    tasks_to_validate = [
        {
            'original_name': 'Nick Milo コミュニティ脱退',
            'expected_hash': 'fd03dadd',
            'actual_name': 'Nick Milo コミュニティ脱退 (fd03dadd)'  # PASS
        },
        {
            'original_name': 'プロンプトを書かないでループでやっている',
            'expected_hash': 'b67a23ad',
            'actual_name': 'プロンプトを書かないでループでやっている (b67a23ad)'  # PASS
        },
        {
            'original_name': 'Codex app をMacBook Airに。',
            'expected_hash': 'ae1b3600',
            'actual_name': 'Codex app をMacBook Airに。 (ae1b3600)'  # PASS
        },
        {
            'original_name': 'AI OSをセットアップするために必要なものがすべて揃っています',
            'expected_hash': '3e9a2270',
            'actual_name': 'AI OSをセットアップするために必要なものがすべて揃っています'  # FAIL (no hash)
        }
    ]

    validator = TaskRenameValidator(verbose=True)
    report = validator.validate_batch(tasks_to_validate)

    # Generate remediation script
    remediation = validator.generate_remediation_script()
    if 'No failures' not in remediation:
        print("\n" + "=" * 80)
        print("REMEDIATION SCRIPT")
        print("=" * 80)
        print(remediation)

    # Save report
    with open('/tmp/rename_validation_report.json', 'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n✓ Report saved to /tmp/rename_validation_report.json")
