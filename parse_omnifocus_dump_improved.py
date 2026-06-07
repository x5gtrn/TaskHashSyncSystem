#!/usr/bin/env python3
"""
IMPROVED OMNIFOCUS DUMP PARSER
Version: 2.0 (2026-06-07)

Improvements:
  1. Strip trailing whitespace from task names
  2. Normalize Unicode (NFC)
  3. Handle special characters and emoji
  4. Detect and report parsing anomalies
"""

import re
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

class OmniFocusDumpParser:
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.tasks = []
        self.parse_issues = []

    def clean_task_name(self, name: str) -> str:
        """
        Clean and normalize task name:
        1. Strip leading/trailing whitespace
        2. Normalize Unicode (NFC)
        3. Remove control characters
        """
        # Strip whitespace (CRITICAL FIX)
        name = name.strip()

        # Normalize Unicode to NFC form
        import unicodedata
        name = unicodedata.normalize('NFC', name)

        # Remove control characters but keep emoji
        name = ''.join(char for char in name if unicodedata.category(char)[0] != 'C')

        return name

    def parse_task_line(self, line: str, indent_level: int) -> Optional[Dict]:
        """
        Parse a task line from OmniFocus dump
        Format: "   • Task Name (hash) [metadata]"
        """
        # Match task line pattern
        match = re.match(r'^(\s*)•\s+(.+?)(?:\s+\[.*?\])?(?:\s+#\w+)?$', line)

        if not match:
            return None

        indent = len(match.group(1))
        raw_name = match.group(2)

        # Clean the task name
        task_name = self.clean_task_name(raw_name)

        # Extract hash if present
        hash_match = re.search(r'\s\(([0-9a-f]{8})\)$', task_name)
        task_hash = hash_match.group(1) if hash_match else None

        # Extract metadata
        has_children = False  # Will be determined by next lines

        return {
            'name': task_name,
            'raw_name': raw_name,
            'hash': task_hash,
            'indent': indent,
            'indent_level': indent_level,
            'has_children': has_children
        }

    def parse_dump(self, dump_text: str) -> Dict:
        """
        Parse full OmniFocus dump
        """
        lines = dump_text.split('\n')
        tasks = []

        for line_num, line in enumerate(lines, 1):
            if not line.strip():
                continue

            # Skip header lines
            if any(header in line for header in ['FORMAT LEGEND', 'Status:', '# OMNIFOCUS']):
                continue

            # Detect task line
            if '•' in line:
                task = self.parse_task_line(line, len(line) - len(line.lstrip()) // 3)
                if task:
                    task['line_num'] = line_num
                    tasks.append(task)

                    if self.verbose:
                        print(f"✓ Line {line_num}: {task['name'][:50]}")
                        if task['hash'] != task.get('original_hash'):
                            print(f"  (cleaned from: {task['raw_name'][:50]})")

        self.tasks = tasks
        return {
            'timestamp': datetime.now().isoformat(),
            'total_tasks': len(tasks),
            'tasks': tasks,
            'parse_issues': self.parse_issues
        }

    def detect_parse_anomalies(self) -> List[Dict]:
        """
        Detect and report parsing anomalies
        """
        anomalies = []

        for task in self.tasks:
            # Check for trailing spaces in raw name
            if task['raw_name'] != task['raw_name'].rstrip():
                anomalies.append({
                    'type': 'trailing_spaces',
                    'task': task['name'],
                    'raw': task['raw_name'],
                    'spaces_count': len(task['raw_name']) - len(task['raw_name'].rstrip())
                })

            # Check for Unicode normalization issues
            import unicodedata
            nfc_form = unicodedata.normalize('NFC', task['raw_name'].strip())
            if nfc_form != task['name']:
                anomalies.append({
                    'type': 'unicode_normalization',
                    'task': task['name'],
                    'before': task['raw_name'],
                    'after': nfc_form
                })

        self.parse_issues = anomalies
        return anomalies

    def generate_report(self) -> Dict:
        """
        Generate detailed parse report
        """
        anomalies = self.detect_parse_anomalies()

        return {
            'timestamp': datetime.now().isoformat(),
            'parse_summary': {
                'total_tasks': len(self.tasks),
                'anomalies_detected': len(anomalies),
                'anomalies': anomalies
            },
            'recommendations': self._generate_recommendations(anomalies)
        }

    def _generate_recommendations(self, anomalies: List[Dict]) -> List[str]:
        """
        Generate recommendations based on anomalies
        """
        recommendations = []

        trailing_space_tasks = [a for a in anomalies if a['type'] == 'trailing_spaces']
        if trailing_space_tasks:
            recommendations.append(
                f"⚠️  Found {len(trailing_space_tasks)} tasks with trailing spaces. "
                "These may fail API name matching. Use cleaned names for API calls."
            )

        unicode_tasks = [a for a in anomalies if a['type'] == 'unicode_normalization']
        if unicode_tasks:
            recommendations.append(
                f"ℹ️  Found {len(unicode_tasks)} tasks with Unicode normalization issues. "
                "NFC normalization applied automatically."
            )

        if not anomalies:
            recommendations.append("✅ No parsing anomalies detected. All task names cleaned.")

        return recommendations

def main():
    # Example usage with test dump
    test_dump = """
# OMNIFOCUS [2026-06-07]

INBOX:
   • AI OSをセットアップするために必要なものがすべて揃っています  #avail
   • Codex app をMacBook Airに。 (ae1b3600) #avail
   • プロンプトを書かないでループでやっている (b67a23ad) #avail
"""

    parser = OmniFocusDumpParser(verbose=True)
    result = parser.parse_dump(test_dump)
    report = parser.generate_report()

    print("\n" + "=" * 80)
    print("PARSE REPORT")
    print("=" * 80)
    print(json.dumps(report, indent=2, ensure_ascii=False))

    return report

if __name__ == '__main__':
    main()
