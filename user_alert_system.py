#!/usr/bin/env python3
"""
USER ALERT SYSTEM
Version: 2.0 (2026-06-07)

Purpose:
  Provide clear, actionable alerts to users when remediation issues occur
  Prevent silent failures and misreporting

Features:
  1. Alert severity levels (INFO, WARNING, ERROR, CRITICAL)
  2. Structured alert JSON for logging
  3. Human-readable alert formatting
  4. Actionable remediation guidance
  5. Alert history tracking
"""

import json
import sys
from datetime import datetime
from typing import List, Dict, Optional
from enum import Enum

class AlertSeverity(Enum):
    INFO = "ℹ️ INFO"
    WARNING = "⚠️ WARNING"
    ERROR = "❌ ERROR"
    CRITICAL = "🔴 CRITICAL"

class UserAlertSystem:
    def __init__(self, log_file: Optional[str] = None):
        self.alerts = []
        self.log_file = log_file
        self.print_to_console = True

    def create_alert(
        self,
        severity: AlertSeverity,
        title: str,
        message: str,
        affected_items: List[str] = None,
        remediation_steps: List[str] = None,
        related_files: List[str] = None
    ) -> Dict:
        """
        Create a structured alert
        """
        alert = {
            'timestamp': datetime.now().isoformat(),
            'severity': severity.value,
            'title': title,
            'message': message,
            'affected_items': affected_items or [],
            'remediation_steps': remediation_steps or [],
            'related_files': related_files or []
        }

        self.alerts.append(alert)

        if self.print_to_console:
            self._print_alert(alert)

        if self.log_file:
            self._log_alert(alert)

        return alert

    def _print_alert(self, alert: Dict):
        """
        Print alert to console in human-readable format
        """
        print("\n" + "=" * 80)
        print(alert['severity'] + " " + alert['title'])
        print("=" * 80)
        print(f"\n{alert['message']}\n")

        if alert['affected_items']:
            print("Affected Items:")
            for item in alert['affected_items']:
                print(f"  • {item}")
            print()

        if alert['remediation_steps']:
            print("Remediation Steps:")
            for i, step in enumerate(alert['remediation_steps'], 1):
                print(f"  {i}. {step}")
            print()

        if alert['related_files']:
            print("Related Files:")
            for file in alert['related_files']:
                print(f"  • {file}")
            print()

    def _log_alert(self, alert: Dict):
        """
        Log alert to JSON file
        """
        try:
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(alert, ensure_ascii=False) + '\n')
        except Exception as e:
            print(f"⚠️  Could not log alert: {e}")

    def alert_rename_failures(self, failures: List[Dict]):
        """
        Alert user to task rename failures
        """
        self.create_alert(
            severity=AlertSeverity.ERROR,
            title="Task Rename Failures Detected",
            message=(
                f"During PHASE 3 remediation, {len(failures)} task(s) could not be "
                "automatically renamed in OmniFocus. These tasks exist in Vault with "
                "TaskHash but lack the hash in OmniFocus, breaking bidirectional sync."
            ),
            affected_items=[f["task"] for f in failures],
            remediation_steps=[
                "1. Open OmniFocus application",
                "2. For each task below, rename to include the TaskHash",
                "3. Search for the task name in Inbox",
                "4. Edit the task name to: <original name> (<hash>)",
                "5. Save and close OmniFocus",
                "6. Run 'sync tasks' again to verify sync"
            ] + [f"   • {f['task']} → {f['expected']}" for f in failures[:3]],
            related_files=[
                "x/Audits/2026-06-07_RemediationSummary.json",
                "Calendar/Daily/2026/06/2026-06-07.md"
            ]
        )

    def alert_api_failures(self, task_names: List[str], retry_count: int):
        """
        Alert user to API lookup failures
        """
        self.create_alert(
            severity=AlertSeverity.WARNING,
            title="OmniFocus API Lookup Failures",
            message=(
                f"API lookup for {len(task_names)} task(s) failed after {retry_count} retries. "
                "This may be due to:\n"
                "  • Whitespace differences (trailing spaces in OmniFocus dump)\n"
                "  • Unicode normalization issues\n"
                "  • Temporary API connectivity issues\n"
                "  • Task names not exactly matching between systems"
            ),
            affected_items=task_names,
            remediation_steps=[
                "1. Use OmniFocus UI search to find the task",
                "2. Verify the exact task name in OmniFocus",
                "3. If name contains trailing spaces, trim them in OmniFocus",
                "4. Run sync again to retry API lookup"
            ]
        )

    def alert_validation_passed(self, total_tasks: int):
        """
        Alert user to successful validation
        """
        self.create_alert(
            severity=AlertSeverity.INFO,
            title="Validation Complete - All Renames Successful",
            message=(
                f"✅ All {total_tasks} task(s) were successfully renamed in OmniFocus "
                "with TaskHash appended. Bidirectional sync is now complete."
            ),
            remediation_steps=[
                "1. Next sync will recognize all tasks as tracked",
                "2. No manual intervention required",
                "3. System coverage is now at 100%"
            ]
        )

    def alert_partial_success(self, total: int, successful: int, failed: int):
        """
        Alert user to partial success with remaining issues
        """
        self.create_alert(
            severity=AlertSeverity.WARNING,
            title=f"Partial Sync Success: {successful}/{total} Tasks Complete",
            message=(
                f"Task rename remediation partially succeeded:\n"
                f"  ✅ {successful} tasks renamed successfully\n"
                f"  ❌ {failed} task(s) require manual attention\n\n"
                "Vault backups exist for all tasks, but OmniFocus needs manual updates."
            ),
            remediation_steps=[
                "1. Manually rename the following task(s) in OmniFocus",
                "2. Use the Remediation Summary report for exact names",
                "3. Run 'sync tasks' after manual changes",
                "4. System will auto-hash any remaining hashless tasks"
            ],
            related_files=[
                "x/Audits/2026-06-07_RemediationSummary.json",
                "x/Audits/2026-06-07_VaultModifications.json"
            ]
        )

    def get_alert_summary(self) -> Dict:
        """
        Get summary of all alerts
        """
        return {
            'timestamp': datetime.now().isoformat(),
            'total_alerts': len(self.alerts),
            'by_severity': {
                'INFO': sum(1 for a in self.alerts if 'ℹ️' in a['severity']),
                'WARNING': sum(1 for a in self.alerts if '⚠️' in a['severity']),
                'ERROR': sum(1 for a in self.alerts if '❌' in a['severity']),
                'CRITICAL': sum(1 for a in self.alerts if '🔴' in a['severity'])
            },
            'alerts': self.alerts
        }

# Example usage
if __name__ == '__main__':
    print("=" * 80)
    print("USER ALERT SYSTEM DEMONSTRATION")
    print("=" * 80)

    alert_system = UserAlertSystem(log_file='/tmp/alerts.jsonl')

    # Simulate rename failures
    failures = [
        {
            'task': 'AI OSをセットアップするために必要なものがすべて揃っています',
            'expected': 'AI OSをセットアップするために必要なものがすべて揃っています (3e9a2270)'
        }
    ]

    alert_system.alert_rename_failures(failures)

    # Simulate partial success alert
    alert_system.alert_partial_success(total=4, successful=3, failed=1)

    # Get summary
    summary = alert_system.get_alert_summary()
    print("\n" + "=" * 80)
    print("ALERT SUMMARY")
    print("=" * 80)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
