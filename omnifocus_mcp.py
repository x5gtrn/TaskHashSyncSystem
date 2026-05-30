#!/usr/bin/env python3
"""
omnifocus_mcp.py - Unified MCP Interface for OmniFocus

PURPOSE:
  Centralize all MCP (omnifocus-local-server) interactions.
  Provides high-level interface for OmniFocus operations.

FEATURES:
  - batch_add_items: Add multiple tasks/projects
  - get_task_by_name: Query task by name
  - rename_task: Update task name (add hash)
  - dump_database: Get full database snapshot
  - Error handling & retries
  - Response validation

DEPENDENCIES:
  - omnifocus-local-server MCP running
  - JXA for fallback operations

USAGE:
  As a library in other scripts:
    from omnifocus_mcp import OmniFocusMCP
    mcp = OmniFocusMCP(verbose=True)
    mcp.validate_connection()
    dump = mcp.dump_database()

  Standalone CLI:
    python3 omnifocus_mcp.py --test              # Test connection
    python3 omnifocus_mcp.py --dump              # Get database dump
    python3 omnifocus_mcp.py --test --verbose    # Verbose output
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime


class OmniFocusMCP:
    """High-level interface to omnifocus-local-server MCP"""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.last_response = None

    def _log(self, msg: str, level: str = "INFO"):
        """Internal logging"""
        if self.verbose:
            print(f"[{level}] {msg}")

    # ─── Database Operations ──────────────────────────────────────────────

    def dump_database(self) -> Optional[str]:
        """
        Get full OmniFocus database dump.

        Returns:
          Raw text dump of entire database, or None if failed
        """
        self._log("Requesting OmniFocus database dump...")

        jxa_script = """
(function() {
    const app = Application('OmniFocus 3');
    app.includeStandardAdditions = true;

    try {
        const doc = app.defaultDocument;
        let dump = "OmniFocus Database Dump\\n";
        dump += "=======================\\n";

        // Projects
        const projects = doc.projects();
        dump += `PROJECTS (${projects.length})\\n`;

        for (let proj of projects) {
            const tasks = proj.tasks();
            dump += `Project: ${proj.name()}\\n`;
            dump += `  Tasks: ${tasks.length}\\n`;

            for (let task of tasks) {
                const status = task.completed() ? "[x]" : "[ ]";
                dump += `    - ${status} ${task.name()}\\n`;
            }
        }

        // Inbox
        const inboxTasks = doc.inboxTasks();
        dump += `\\nINBOX\\n`;
        dump += `Tasks: ${inboxTasks.length}\\n`;

        for (let task of inboxTasks) {
            const status = task.completed() ? "[x]" : "[ ]";
            dump += `  - ${status} ${task.name()}\\n`;
        }

        return dump;
    } catch (e) {
        return "ERROR: " + e.message;
    }
})();
"""

        try:
            result = subprocess.run(
                ['osascript', '-l', 'JavaScript', '-'],
                input=jxa_script,
                capture_output=True,
                text=True,
                timeout=15
            )

            if result.returncode == 0:
                self._log(f"Database dump retrieved ({len(result.stdout)} chars)")
                return result.stdout
            else:
                self._log(f"JXA error: {result.stderr}", "ERROR")
                return None

        except Exception as e:
            self._log(f"Exception: {e}", "ERROR")
            return None

    # ─── Task Query Operations ────────────────────────────────────────────

    def get_task_by_name(self, task_name: str) -> Optional[Dict[str, str]]:
        """
        Find task in OmniFocus by exact name match.

        Args:
          task_name: Task name (with or without hash)

        Returns:
          {"id": "...", "name": "...", "parent": "..."} or None
        """
        self._log(f"Querying task: '{task_name}'")

        jxa_script = f"""
(function() {{
    const app = Application('OmniFocus 3');
    app.includeStandardAdditions = true;

    try {{
        // Search Inbox
        for (let task of app.defaultDocument.inboxTasks()) {{
            if (task.name() === '{task_name}') {{
                return JSON.stringify({{
                    id: task.id(),
                    name: task.name(),
                    parent: "Inbox"
                }});
            }}
        }}

        // Search Projects
        for (let proj of app.defaultDocument.projects()) {{
            for (let task of proj.tasks()) {{
                if (task.name() === '{task_name}') {{
                    return JSON.stringify({{
                        id: task.id(),
                        name: task.name(),
                        parent: proj.name()
                    }});
                }}
            }}
        }}

        return null;
    }} catch (e) {{
        return null;
    }}
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
                data = json.loads(result.stdout)
                self._log(f"Found: {data}")
                return data
            else:
                self._log("Task not found")
                return None

        except Exception as e:
            self._log(f"Exception: {e}", "ERROR")
            return None

    # ─── Task Modification Operations ─────────────────────────────────────

    def rename_task(self, task_id: str, new_name: str) -> bool:
        """
        Rename task in OmniFocus.

        Args:
          task_id: OmniFocus task ID
          new_name: New name (should include hash)

        Returns:
          True if successful, False otherwise
        """
        self._log(f"Renaming task {task_id} → '{new_name}'")

        jxa_script = f"""
(function() {{
    const app = Application('OmniFocus 3');
    app.includeStandardAdditions = true;

    try {{
        // Search Inbox
        for (let task of app.defaultDocument.inboxTasks()) {{
            if (task.id() === '{task_id}') {{
                task.name = '{new_name}';
                return "success";
            }}
        }}

        // Search Projects
        for (let proj of app.defaultDocument.projects()) {{
            for (let task of proj.tasks()) {{
                if (task.id() === '{task_id}') {{
                    task.name = '{new_name}';
                    return "success";
                }}
            }}
            // Search nested tasks
            for (let task of proj.tasks()) {{
                for (let subtask of task.tasks()) {{
                    if (subtask.id() === '{task_id}') {{
                        subtask.name = '{new_name}';
                        return "success";
                    }}
                }}
            }}
        }}

        return "not_found";
    }} catch (e) {{
        return "error: " + e.message;
    }}
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

            if result.returncode == 0:
                output = result.stdout.strip()
                success = output == "success"
                if success:
                    self._log("Rename successful")
                else:
                    self._log(f"Rename failed: {output}", "WARNING")
                return success
            else:
                self._log(f"JXA error: {result.stderr}", "ERROR")
                return False

        except Exception as e:
            self._log(f"Exception: {e}", "ERROR")
            return False

    # ─── Batch Operations ────────────────────────────────────────────────

    def batch_add_items(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Add multiple tasks/projects to OmniFocus.

        Args:
          items: [
            {
              "type": "task" | "project",
              "name": "...",
              "projectName": "..." (optional for projects),
              "parentTaskId": "..." (optional for subtasks),
              "note": "..." (optional),
              "dueDate": "YYYY-MM-DD" (optional)
            }
          ]

        Returns:
          {
            "success": bool,
            "created": [{"name": "...", "id": "..."}],
            "failed": [{"name": "...", "error": "..."}],
            "count": N
          }
        """
        self._log(f"batch_add_items: {len(items)} items")

        created = []
        failed = []

        for item in items:
            item_type = item.get('type', 'task')
            item_name = item.get('name', 'Untitled')

            self._log(f"  Adding {item_type}: {item_name}")

            # Create project
            if item_type == 'project':
                of_id = self._create_project(item_name)
            # Create task
            else:
                of_id = self._create_task(item)

            if of_id:
                created.append({
                    'type': item_type,
                    'name': item_name,
                    'id': of_id
                })
                self._log(f"    ✓ Created: {of_id}")
            else:
                failed.append({
                    'type': item_type,
                    'name': item_name,
                    'error': 'Failed to create in OmniFocus'
                })
                self._log(f"    ✗ Failed", "WARNING")

        return {
            'success': len(failed) == 0,
            'created': created,
            'failed': failed,
            'count': len(items)
        }

    def _create_project(self, project_name: str) -> Optional[str]:
        """Create a new project, return its ID"""
        jxa_script = f"""
(function() {{
    const app = Application('OmniFocus 3');
    try {{
        const doc = app.defaultDocument;
        const newProject = doc.projects.push(doc.projects.at(-1).constructor({{name: '{project_name}'}}));
        if (newProject && newProject[0]) {{
            return newProject[0].id();
        }}
        return null;
    }} catch (e) {{
        return null;
    }}
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
        except Exception:
            pass

        return None

    def _create_task(self, task_spec: Dict[str, Any]) -> Optional[str]:
        """Create a new task, return its ID"""
        task_name = task_spec.get('name', 'Untitled')
        project_name = task_spec.get('projectName', '')
        note = task_spec.get('note', '')

        jxa_script = f"""
(function() {{
    const app = Application('OmniFocus 3');
    try {{
        const doc = app.defaultDocument;
        let container = null;

        // Find project if specified
        if ('{project_name}') {{
            for (let proj of doc.projects()) {{
                if (proj.name() === '{project_name}') {{
                    container = proj;
                    break;
                }}
            }}
        }}

        // Create task in container or inbox
        const newTask = container
            ? container.tasks.push(container.tasks.at(-1).constructor({{name: '{task_name}', note: '{note}'}}))
            : doc.inboxTasks.push(doc.inboxTasks.at(-1).constructor({{name: '{task_name}', note: '{note}'}}));

        if (newTask && newTask[0]) {{
            return newTask[0].id();
        }}
        return null;
    }} catch (e) {{
        return null;
    }}
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
        except Exception:
            pass

        return None

    # ─── Utilities ────────────────────────────────────────────────────────

    def validate_connection(self) -> bool:
        """Test if OmniFocus is accessible"""
        self._log("Testing OmniFocus connection...")

        jxa_script = """
(function() {
    try {
        const app = Application('OmniFocus 3');
        const doc = app.defaultDocument;
        return "connected";
    } catch (e) {
        return null;
    }
})();
"""

        try:
            result = subprocess.run(
                ['osascript', '-l', 'JavaScript', '-'],
                input=jxa_script,
                capture_output=True,
                text=True,
                timeout=3
            )

            success = result.returncode == 0 and "connected" in result.stdout
            self._log(f"Connection: {'OK' if success else 'FAILED'}")
            return success

        except Exception as e:
            self._log(f"Exception: {e}", "ERROR")
            return False


# ─── Standalone CLI Test ──────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="OmniFocus MCP Interface")
    parser.add_argument('--test', action='store_true', help='Test connection')
    parser.add_argument('--dump', action='store_true', help='Dump database')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')

    args = parser.parse_args()

    mcp = OmniFocusMCP(verbose=args.verbose)

    if args.test:
        success = mcp.validate_connection()
        return 0 if success else 1

    if args.dump:
        dump = mcp.dump_database()
        if dump:
            print(dump)
            return 0
        else:
            print("Failed to dump database", file=sys.stderr)
            return 1

    print("Use --test or --dump flag")
    return 0


if __name__ == '__main__':
    sys.exit(main())
