#!/usr/bin/env python3
"""
OmniFocus AppleScript Bridge

Provides functions to interact with OmniFocus using AppleScript via osascript.
Enables adding tasks/projects and querying OmniFocus from Python.
"""

import subprocess
import json
from typing import Optional, Dict, List


def escape_applescript(s: str) -> str:
    """Escape special characters for AppleScript."""
    return s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')


def add_project_to_omnifocus(
    name: str,
    note: str = "",
    inbox: bool = False
) -> Optional[str]:
    """
    Add a project to OmniFocus using AppleScript.

    Args:
        name: Project name
        note: Project note/description
        inbox: If True, create in inbox instead of default location

    Returns:
        Project ID if successful, None otherwise
    """
    name_escaped = escape_applescript(name)
    note_escaped = escape_applescript(note) if note else ""

    # AppleScript to add a project (try both app names)
    script_template = """
tell application "{app_name}"
    tell default document
        set _project to make new project with properties {{name:"{name_escaped}"}}
        if "{note_escaped}" is not "" then
            set note of _project to "{note_escaped}"
        end if
        return id of _project
    end tell
end tell
"""

    for app_name in ["OmniFocus", "OmniFocus 3"]:
        script = script_template.format(app_name=app_name, name_escaped=name_escaped, note_escaped=note_escaped)
        try:
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            continue
        except FileNotFoundError:
            return None

    return None


def add_task_to_inbox(
    name: str,
    note: str = "",
    due_date: Optional[str] = None
) -> Optional[str]:
    """
    Add a task to OmniFocus inbox using AppleScript.

    Args:
        name: Task name
        note: Task note/description
        due_date: Due date in ISO format (YYYY-MM-DD)

    Returns:
        Task ID if successful, None otherwise
    """
    name_escaped = escape_applescript(name)
    note_escaped = escape_applescript(note) if note else ""

    # AppleScript to add a task (try both app names)
    script_template = """
tell application "{app_name}"
    tell default document
        set _task to make new inbox task with properties {{name:"{name_escaped}"}}
        if "{note_escaped}" is not "" then
            set note of _task to "{note_escaped}"
        end if
        return id of _task
    end tell
end tell
"""

    for app_name in ["OmniFocus", "OmniFocus 3"]:
        script = script_template.format(app_name=app_name, name_escaped=name_escaped, note_escaped=note_escaped)
        try:
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            continue
        except FileNotFoundError:
            return None

    return None


def add_subtask_to_project(
    project_id: str,
    name: str,
    note: str = ""
) -> Optional[str]:
    """
    Add a subtask to a specific project using AppleScript.

    Args:
        project_id: Project ID
        name: Task name
        note: Task note/description

    Returns:
        Task ID if successful, None otherwise
    """
    name_escaped = escape_applescript(name)
    note_escaped = escape_applescript(note) if note else ""

    # AppleScript to add a subtask (try both app names)
    script_template = """
tell application "{app_name}"
    tell default document
        set _project to first project whose id is "{project_id}"
        set _task to make new task with properties {{name:"{name_escaped}"}} at end of tasks of _project
        if "{note_escaped}" is not "" then
            set note of _task to "{note_escaped}"
        end if
        return id of _task
    end tell
end tell
"""

    for app_name in ["OmniFocus", "OmniFocus 3"]:
        script = script_template.format(app_name=app_name, project_id=project_id, name_escaped=name_escaped, note_escaped=note_escaped)
        try:
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            continue
        except FileNotFoundError:
            return None

    return None


def get_omnifocus_available() -> bool:
    """Check if OmniFocus is available on this system."""
    try:
        # Try both "OmniFocus" and "OmniFocus 3"
        for app_name in ["OmniFocus", "OmniFocus 3"]:
            result = subprocess.run(
                ['osascript', '-e', f'tell application "{app_name}" to return version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return True
        return False
    except:
        return False


if __name__ == "__main__":
    # Test
    print(f"OmniFocus available: {get_omnifocus_available()}")

    if get_omnifocus_available():
        print("\nTesting project creation...")
        project_id = add_project_to_omnifocus("Test Project", "This is a test")
        print(f"Project ID: {project_id}")

        if project_id:
            print("\nTesting subtask creation...")
            task_id = add_subtask_to_project(project_id, "Test Task", "Task note")
            print(f"Task ID: {task_id}")

        print("\nTesting inbox task creation...")
        inbox_task = add_task_to_inbox("Test Inbox Task", "Inbox task note")
        print(f"Inbox Task ID: {inbox_task}")
