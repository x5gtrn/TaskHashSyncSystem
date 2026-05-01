#!/usr/bin/env python3
"""
OmniFocus MCP (Model Context Protocol) Bridge

Uses omnifocus-local-server MCP for stable, feature-rich OmniFocus integration.
More reliable and feature-complete than AppleScript.
"""

from typing import Optional, Dict, List, Any


def add_omnifocus_project(
    name: str,
    note: str = ""
) -> Optional[str]:
    """
    Add a project to OmniFocus using MCP.

    Note: This function signature is designed to be called directly,
    but actual implementation requires calling the MCP tool.

    Args:
        name: Project name
        note: Project note/description

    Returns:
        Project ID if successful, None otherwise
    """
    # This is a placeholder - actual calls happen via the MCP tool
    # in the sync scripts
    return None


def add_task_to_inbox(
    name: str,
    note: str = ""
) -> Optional[str]:
    """
    Add a task to OmniFocus Inbox using MCP.

    Note: This function signature is designed to be called directly,
    but actual implementation requires calling the MCP tool.

    Args:
        name: Task name
        note: Task note/description

    Returns:
        Task ID if successful, None otherwise
    """
    # This is a placeholder - actual calls happen via the MCP tool
    # in the sync scripts
    return None


def add_subtask_to_project(
    project_id: str,
    name: str,
    note: str = ""
) -> Optional[str]:
    """
    Add a subtask to a project using MCP.

    Note: This function signature is designed to be called directly,
    but actual implementation requires calling the MCP tool.

    Args:
        project_id: Project ID
        name: Task name
        note: Task note/description

    Returns:
        Task ID if successful, None otherwise
    """
    # This is a placeholder - actual calls happen via the MCP tool
    # in the sync scripts
    return None


# MCP Tool Information for Reference
"""
Available OmniFocus MCP tools:

1. add_omnifocus_task(name, projectName, note, dueDate, deferDate, estimatedMinutes, flagged, tags)
   - Add task to Inbox or specific project
   - Returns task ID

2. add_project(name, folderName, note, dueDate, deferDate, sequential, tags)
   - Create a new project
   - Returns project ID

3. batch_add_items(items=[{type, name, projectName, ...}])
   - Add multiple tasks/projects at once
   - More efficient for bulk operations

4. edit_item(id, itemType, newName, newNote, newStatus, newDueDate, ...)
   - Edit existing task or project
   - Update any property

5. filter_tasks(projectFilter, tagFilter, taskStatus, dueDate, ...)
   - Advanced task filtering
   - Supports complex queries

6. get_inbox_tasks()
   - Get all Inbox tasks

7. dump_database()
   - Export all OmniFocus data
   - Useful for debugging

Note: When calling these tools from sync scripts, use the MCP tool directly
rather than these wrapper functions. Example:

    from mcp__omnifocus-local-server__add_project import add_project
    project_id = add_project(
        name="My Project",
        note="Description"
    )
"""

if __name__ == "__main__":
    print(__doc__)
    print("\nOmniFocus MCP Bridge loaded successfully.")
    print("Use MCP tools directly in sync scripts for actual operations.")
