# Task Synchronization System (OmniFocus ↔ GitHub ↔ Vault)

## Overview

A **bidirectional task synchronization system** with three distinct sync domains:

1. **GitHub Issues ↔ OmniFocus Projects**: GitHub Issues are Projects in OmniFocus
2. **Vault Daily Notes ↔ OmniFocus Inbox**: Daily Notes contain Inbox tasks only
3. **State Management**: CRC32-based TaskHash (8-digit hex) for immutable task identification

Each task receives a unique **TaskHash** (e.g., `(73801d05)`) that **never changes**, regardless of task content modifications. This ensures reliable tracking across systems.

## Core Components

### 1. TaskHash - Immutable Task Identification

**Definition**: A CRC32 hash generated once per task, immutable for the task's lifetime.

**Generation** (`task_hash.py`):
- **Algorithm**: CRC32 based on `task {size}\0{source_id}` format
- **Format**: 8-digit lowercase hexadecimal
- **Source ID format**: 
  - GitHub: `github:owner/repo#issue_num:task_name`
  - Vault: `vault:relative/path/to/file.md:task_name`
  - GitHub comments: `github:owner/repo#issue_num:comment#N:task_name`
- **Immutability**: Once generated, TaskHash never changes even if task name/content is modified
- **Uniqueness**: Same source_id always produces same hash (idempotent)

**Key Property**: TaskHash is the source of truth for task identity across all systems. The task name can change, due dates can change, but TaskHash remains constant.

### 2. Domain Separation

**GitHub Issues (Projects)**:
- Syncs with OmniFocus **Projects** (not Inbox)
- **Issue title itself becomes a Project** with a TaskHash
- Issue body tasks + comment tasks = Project tasks (all with TaskHash)
- **Not synced to Vault** (managed in GitHub only)
- All tasks in Issue body must be formatted with checkboxes: `- [ ] Task name (hash)`

**Vault Daily Notes (Inbox)**:
- Contains Inbox tasks only
- No Project tasks in Daily Notes
- Tasks organized by calendar date
- Syncs with OmniFocus **Inbox**

**Example**:
```
GitHub Issue #42: Setup Financial Accounts (a7f3c942)
- [x] Connect Revolut Account (b2d8e641)
- [ ] Add Credit Card Details (c5e1a392)
- [ ] Set Up Bank Transfers (d9f4c125)

OmniFocus:
  P: Setup Financial Accounts (a7f3c942)  ← Issue title as Project
     • Connect Revolut Account (b2d8e641) ✅  ← Issue body task
     • Add Credit Card Details (c5e1a392)    ← Issue body task
     • Set Up Bank Transfers (d9f4c125)      ← Issue body task
  P: Deferred Projects (e2a7b314)         ← Vault Daily Note Project
     • Process backlog items (f6c3d927)
  INBOX:
     • Watch Training Videos (g8b1e564)  ← Vault Daily Note task
     • Learn Japanese Grammar (h4d9f782) ← Vault Daily Note task
        • Master Hiragana Characters (i7c2a401) ← Child task (indented in Vault)
```

### 3. GitHub Issue to Project Conversion

**When adding a new GitHub Issue**:

The Issue title and all tasks within it must receive TaskHashes to enable synchronization:

1. **Issue Title TaskHash Generation**:
   - Create Issue with title, e.g., "Setup Financial Accounts"
   - Generate source_id: `github:owner/repo#issue_num:Setup Financial Accounts` (without hash)
   - Compute TaskHash using task_hash.py
   - **Update Issue title** to include hash: `Setup Financial Accounts (a7f3c942)`

2. **Issue Body Task HashGeneration**:
   - Format all tasks with checkboxes: `- [ ] Task name` or `- [x] Task name`
   - For each task, generate source_id: `github:owner/repo#issue_num:Task name`
   - Compute TaskHash and append to task name: `- [ ] Task name (hash)`
   - **Update Issue body** with hashes appended to all tasks

3. **Workflow**:
   ```bash
   # 1. Create/edit GitHub Issue (title + task list in checkboxes)
   # 2. Run prepare_sync.py to generate and validate hashes
   # 3. Update Issue title and body with hashes
   # 4. Run prepare_sync.py again - should show "already synced"
   # 5. Claude adds to OmniFocus as Project + child tasks
   ```

4. **OmniFocus Result**:
   - Project created with Issue title + hash
   - All tasks added as child tasks of Project
   - Each task linked to Issue via URL in Project note
   - Task relationships maintained via parentTaskHash in sync_state.json

**Example Conversion**:
```
GitHub Issue Before:
  Title: Setup Financial Accounts
  Body:
  - [x] Connect Revolut Account
  - [ ] Add Credit Card Details
  - [ ] Set Up Bank Transfers

GitHub Issue After:
  Title: Setup Financial Accounts (a7f3c942)
  Body:
  - [x] Connect Revolut Account (b2d8e641)
  - [ ] Add Credit Card Details (c5e1a392)
  - [ ] Set Up Bank Transfers (d9f4c125)

OmniFocus Result:
  P: Setup Financial Accounts (a7f3c942)
     • Connect Revolut Account (b2d8e641) ✅
     • Add Credit Card Details (c5e1a392)
     • Set Up Bank Transfers (d9f4c125)
```

**Important Notes**:
- TaskHashes must be added to both Issue title AND task names
- prepare_sync.py automatically removes existing hashes before recalculating, preventing duplicate hashes
- Never manually calculate hashes; always use task_hash.py
- TaskHash format: 8-digit lowercase hexadecimal (e.g., `73801d05`)

### 4. Parent-Child Relationships (`parentTaskHash`)

**Hierarchy Tracking**: Uses `parentTaskHash` instead of `parentTaskName` for robust parent references.

**Why TaskHash for parents?**
- Task names can change; hashes never do
- If parent name changes, relationship is preserved
- Decouples structure from content

**Indentation in Vault**:
- Tabs/spaces indicate hierarchy
- Parent task at level 0, children at level 1, grandchildren at level 2, etc.
- Automatically detected by `prepare_sync.py`

**Example**:
```markdown
## Tasks
- [ ] Learn Japanese Grammar (h4d9f782)     [Level 0]
	- [ ] Master Hiragana Characters (i7c2a401) [Level 1, parent: h4d9f782]
	- [ ] Learn Katakana Basics (j5f8b634)     [Level 1, parent: h4d9f782]
		- [ ] Practice Katakana Writing (k9e3c171) [Level 2, parent: j5f8b634]
```

**OmniFocus Structure**:
```
INBOX:
   • Learn Japanese Grammar (h4d9f782)
      • Master Hiragana Characters (i7c2a401)
      • Learn Katakana Basics (j5f8b634)
         • Practice Katakana Writing (k9e3c171)
```

### 5. Forward Sync (GitHub/Vault → OmniFocus)

**Data Preparation** (`prepare_sync.py`):
1. Scan GitHub Issues (body + all comments)
2. Scan Vault Daily Notes (all `.md` files)
3. Extract unchecked tasks: `- [ ] Task name` format
4. Generate TaskHash for each task
5. Detect parent-child relationships via indentation
6. Output `tasks_to_sync.json`
7. Check `sync_state.json` to skip already-synced tasks

**OmniFocus Addition** (`sync_to_omnifocus.py` + MCP):
1. Resolve `parentTaskHash` → `parentTaskId` using sync_state.json
2. Use `mcp__omnifocus-local-server__add_omnifocus_task()` or `batch_add_items()`
3. Set parent via `parentTaskId`
4. Update `sync_state.json` with OmniFocus task IDs

**Key Rule**: 
- Project tasks (GitHub) → OmniFocus Projects (skip Vault)
- Inbox tasks (Vault) → OmniFocus Inbox (maintain hierarchy)

### 6. Reverse Sync (OmniFocus → GitHub/Vault)

**Completion Reflection** (`reverse_sync.py`):
1. Query OmniFocus for completed tasks via MCP `filter_tasks(completedToday=true)`
2. Match completed tasks to source locations using TaskHash
3. Update checkboxes in GitHub Issues and Vault files
4. Sync due dates (if changed in OmniFocus)
5. Add completion dates to Vault tasks
6. Update `sync_state.json` with completion timestamp

**Project Task Routing**:
- **Project with TaskHash** (created from GitHub Issue) → Reverse-sync to GitHub Issue
- **Project without TaskHash** (Later and other OmniFocus native) → Treat as Vault Inbox
  - Reflect due date to Vault if present: `- [ ] Task (hash) 📅 2026-05-03`
  - Sync if due date is changed/deleted in OmniFocus

**Completion Date Format**:
- Append completion date to Vault Daily Notes: `- [x] Task (hash) 📅 due 2026-05-03 ✅ 2026-05-01`
- Format: `✅ YYYY-MM-DD` (after TaskHash, to end of line)
- Do not overwrite if completion date already exists (idempotent)

### 7. URL and Markdown Link Handling

**Markdown Link Processing** (`task_hash.py`):
- Detects Markdown links: `[text](url)` format
- Extracts URLs to OmniFocus note field
- Cleans task name to contain only display text
- Removes emoji and metadata before hash generation

**Example**:
```
Input:  - [ ] [Buy Groceries](https://grocerystore.com) 📅 2026-05-15
Clean:  Buy Groceries
Hash:   Based on "Buy Groceries" (without URL/date)
OmniFocus:
  Name: Buy Groceries (hash)
  Note: https://grocerystore.com
```

**Due Date Handling**:
- Emoji format: `📅 YYYY-MM-DD` (removed before hash generation)
- OmniFocus is source of truth for due dates
- Synced bidirectionally in state management

### 8. State Management (`sync_state.json`)

**Schema per task**:
```json
{
  "task_hash_value": {
    "source_id": "vault:Calendar/Daily/2026/05/2026-05-01.md:task_name",
    "of_task_id": "omnifocus_id_or_pending",
    "of_task_name": "Task Name (hash_value)",
    "status": "open|completed|dropped",
    "task_type": "vault_task|github_task|github_comment_task|project",
    "parent_task_hash": "parent_hash_value",  # if has parent
    "due_date": "YYYY-MM-DD",                 # if applicable
    "synced_at": "2026-05-01T03:53:20.129036",
    "completed_at": "2026-05-01T04:04:49.824399"  # if completed
  }
}
```

**Key behaviors**:
- TaskHash is the primary key (guarantees uniqueness)
- `source_id` encodes full origin information (never shown in OmniFocus note)
- `task_type` categorizes sync domain (vault, github, project, etc.)
- `status` tracks lifecycle (open → completed → dropped)
- `parent_task_hash` maintains hierarchy even if parent name changes
- Timestamps provide audit trail
- **Idempotency**: Re-running sync skips hashes already in state

### 9. Vault Scanning & Hierarchy Detection

**File Scanning** (`prepare_sync.py`):
- Recursively scans all `.md` files in vault root
- Excludes: `x/Templates/`, `x/Scripts/`, `.obsidian/`, files with "Example"
- Extracts unchecked tasks via regex: `- \[ \]\s*(.+?)(?:\n|$)`

**Hierarchy Detection**:
- Tab/space indentation indicates parent-child relationships
- Parent stack maintained during parsing
- Converts indentation to `parent_task_hash` reference
- Handles arbitrary nesting depth (parent, child, grandchild, etc.)

**Task Type Filtering**:
- Tasks with `parent_task_hash` → Part of Project, skip from Vault sync
- Top-level tasks → Inbox tasks, sync to OmniFocus Inbox
- GitHub Issue tasks → Synced to Projects only

### 10. GitHub Integration

**Issue Detection**:
- Uses GitHub CLI: `gh issue list` and `gh issue view`
- Extracts tasks from body AND all comments
- Each issue becomes an OmniFocus Project
- Comment tasks become subtasks with project hierarchy

**Issue Updates**:
- Uses `gh issue edit` for batch updates
- Pattern: `- [ ] TaskName` → `- [x] TaskName`
- Preserves TaskHash in task name

## Workflow

**User adds task to Vault Daily Note**:
```
1. Edit Calendar/Daily/2026/05/2026-05-01.md
   Add: - [ ] Buy coffee (or [Buy coffee](url) 📅 2026-05-05)

2. Run: python3 x/Scripts/TaskHashSyncSystem/prepare_sync.py
   → Detects new task
   → Generates TaskHash
   → Outputs tasks_to_sync.json

3. Ask Claude to sync:
   → Claude runs sync_to_omnifocus.py
   → Resolves parentTaskHash → parentTaskId
   → Adds to OmniFocus Inbox
   → Updates sync_state.json

4. Complete task in OmniFocus
   → Mark as done

5. Run: python3 x/Scripts/TaskHashSyncSystem/reverse_sync.py
   → Detects completion via TaskHash
   → Updates Daily Note checkbox
   → Updates sync_state.json
```

**User adds new GitHub Issue (full conversion)**:
```
1. Create GitHub Issue with title and task list
   Title: New Project Name
   Body:
   - [ ] Task 1
   - [ ] Task 2
   - [ ] Task 3

2. Ask Claude to sync (GitHub Issue → OmniFocus):
   → Claude generates TaskHash for Issue title
   → Claude generates TaskHash for each task
   → Claude updates Issue title and body with hashes
   → Claude creates Project in OmniFocus
   → Claude adds all tasks as Project children
   → Claude updates sync_state.json

3. Complete tasks in OmniFocus
   → Mark tasks as done

4. Run: python3 x/Scripts/TaskHashSyncSystem/reverse_sync.py
   → Updates GitHub Issue checkboxes
   → Updates sync_state.json with completion timestamps
```

**User adds tasks to existing GitHub Issue**:
```
1. Edit GitHub Issue body or comments
   Add: - [ ] New task

2. Run: python3 x/Scripts/TaskHashSyncSystem/prepare_sync.py
   → Detects new GitHub task
   → Generates TaskHash for new task
   → Outputs tasks_to_sync.json

3. Ask Claude to sync:
   → Adds new task to OmniFocus Project
   → Updates sync_state.json

4. Complete in OmniFocus

5. Run: python3 x/Scripts/TaskHashSyncSystem/reverse_sync.py
   → Updates GitHub Issue checkbox
```

## Implementation Notes

### prepare_sync.py Deduplication Logic

The `prepare_sync.py` script automatically removes existing TaskHashes before recalculating, preventing hash collisions when Issue titles or task names already contain hashes:

**Issue Title Hash Deduplication**:
```python
# GitHub Issue title may already contain hash
title = "Setup Financial Accounts (a7f3c942)"

# Step 1: Remove hash to get clean title
title_without_hash = remove_hash(title)  # → "Setup Financial Accounts"

# Step 2: Calculate hash using clean title
source_id = make_github_source_id(owner, repo, issue_num, title_without_hash)
hash_value = compute_hash(source_id)  # → "a7f3c942"

# Step 3: Verify against sync_state.json
issue_already_synced = is_synced(hash_value, state)  # → True (already synced)
```

**Key Implementation Details**:
1. `remove_hash()` strips the " (XXXXXXXX)" suffix if present
2. Hash calculation always uses the clean name (without existing hash)
3. Enables idempotent re-runs: script produces same hash regardless of current title format
4. Prevents "Prepared N tasks" output when all tasks are already synced

### Task Name Cleaning

All metadata is removed before hash calculation to ensure consistency:
- Markdown links: `[text](url)` → extract URL to note field, use only `text` for hash
- Due dates: `📅 YYYY-MM-DD` → removed before hash
- Task hashes: ` (XXXXXXXX)` → removed before hash

This ensures hash stability even if task metadata changes.

## Error Handling & Robustness

- **Pattern matching**: Handles Markdown links, emoji metadata, indentation
- **Dry-run mode**: All scripts support `--dry-run` to preview changes
- **Verbose logging**: `--verbose` flag shows detailed operation traces
- **Idempotency**: Safe to re-run multiple times
- **Task type filtering**: Automatically skips Project tasks in Vault sync
- **Hash deduplication**: `prepare_sync.py` removes existing hashes before recalculating

## Current Statistics

**Implemented features**:
- ✅ Immutable TaskHash generation (CRC32)
- ✅ GitHub Issue → OmniFocus Project conversion
- ✅ Issue title TaskHash generation and update
- ✅ Issue body task TaskHash generation and update
- ✅ Forward sync (GitHub/Vault → OmniFocus)
- ✅ Reverse sync (OmniFocus → GitHub/Vault)
- ✅ Parent-child hierarchy via parentTaskHash
- ✅ Markdown link extraction to note field
- ✅ Due date synchronization (📅 emoji)
- ✅ Indentation-based hierarchy detection
- ✅ Domain separation (Projects vs. Inbox)
- ✅ Multi-level nesting support
- ✅ State management with audit trail
- ✅ Project task filtering (Vault exclusion)
- ✅ TaskHash validation on sync
- ✅ Hash deduplication in prepare_sync.py
- ✅ **TaskHash-less Project handling** (Later → Vault as Inbox)
- ✅ **Completion date tracking** (`✅ YYYY-MM-DD`)
- ✅ **Due date reflection** in Vault format (`📅 YYYY-MM-DD`)
- ✅ **Bi-directional due date sync** (OmniFocus ↔ Vault)
- ✅ **Indentation & trailing space handling** (robust regex)

## Files Location

```
x/Scripts/TaskHashSyncSystem/
├── README.md                    # Complete specification document
├── task_hash.py                 # TaskHash generation + utilities
├── prepare_sync.py              # Data preparation engine
├── sync_to_omnifocus.py         # OmniFocus sync helper
├── reverse_sync.py              # Reverse sync engine
├── sync_state.json              # Sync state tracking
├── tasks_to_sync.json           # Prepared tasks waiting for sync
└── [other support scripts]

For complete system specification, see [[x/Scripts/TaskHashSyncSystem/README.md]]
```

## MCP Integration

Uses `omnifocus-local-server` MCP with these tools:
- `add_omnifocus_task()` - Add single task with parent reference
- `batch_add_items()` - Batch add tasks/projects
- `edit_item()` - Rename/modify tasks (for TaskHash updates)
- `filter_tasks()` - Query completed tasks for reverse sync
- `get_task_by_id()` - Retrieve task details by name or ID
- `dump_database()` - Get full database structure for verification

## Design Principles

1. **TaskHash is immutable**: Never changes after initial creation
2. **ParentTaskHash is canonical**: Hierarchy depends on hash, not name
3. **Source_id in sync_state only**: Never exposed in OmniFocus note
4. **URL in note only**: Extracted from Markdown links, not in task name
5. **Metadata removed before hash**: Due dates, URLs, emoji excluded
6. **Domain separation**: Projects managed in GitHub, Inbox in Vault
7. **Idempotent operations**: Safe to run sync multiple times
8. **Project routing**: TaskHash-less Projects (Later) treated as Vault Inbox tasks
9. **Date positioning in Vault**: Due date (📅) before completion date (✅)
10. **Robust pattern matching**: Handle indentation, trailing spaces, multi-line tasks

## Current Implementation Status

### ✅ Completed (v1.0)
- TaskHash-less Project handling (Later → Vault as Inbox)
- Completion date tracking (`✅ YYYY-MM-DD`)
- Due date synchronization (Vault ↔ OmniFocus)
- Due date reflection with proper formatting
- Bi-directional date sync (OmniFocus source of truth)
- Indentation and trailing space handling
- Project type detection via sync_state

### 📋 Future Enhancements

- [ ] Scheduled sync via cron jobs (automatic periodic synchronization)
- [ ] Bidirectional GitHub issue state sync
- [ ] Comment task status updates
- [ ] Performance optimization for large issue sets
- [ ] Conflict detection (task modified in multiple places)
- [ ] Tag propagation (GitHub labels ↔ OmniFocus tags)

---

#x/claude
