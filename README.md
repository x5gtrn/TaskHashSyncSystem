# TaskHashSyncSystem - Complete Specification

A **bidirectional task synchronization system** that synchronizes tasks across OmniFocus, GitHub Issues, and Obsidian Vault using immutable CRC32-based task identification.

## Table of Contents

1. [System Overview](#system-overview)
2. [Core Concept: TaskHash](#core-concept-taskhash)
3. [Architecture](#architecture)
4. [Synchronization Domains](#synchronization-domains)
5. [Implementation Details](#implementation-details)
6. [Workflows](#workflows)
7. [Data Structures](#data-structures)
8. [Scripts Reference](#scripts-reference)
9. [Error Handling](#error-handling)
10. [Examples](#examples)

---

## System Overview

### Purpose

The TaskHashSyncSystem enables seamless bidirectional synchronization of tasks across three separate systems:

- **OmniFocus**: Task management and execution engine
- **GitHub Issues**: Project planning and issue tracking
- **Obsidian Vault**: Daily notes and inbox capture

### Key Principles

1. **Single Source of Truth Per Domain**: GitHub Issues are the authoritative source for Projects, Vault Daily Notes are the authoritative source for Inbox tasks
2. **Immutable Task Identity**: Once created, a TaskHash never changes, ensuring reliable cross-system tracking
3. **Metadata Preservation**: Task relationships, dates, and URLs are preserved across synchronization
4. **Idempotent Operations**: All sync operations can be safely re-run multiple times without creating duplicates

### Sync Domains

| Domain | Source System | Target System | Task Type |
|--------|---------------|---------------|-----------|
| **Projects** | GitHub Issues | OmniFocus Projects | Project + child tasks |
| **Inbox** | Obsidian Vault Daily Notes | OmniFocus Inbox | Individual tasks + hierarchy |
| **Completion** | OmniFocus | GitHub Issues + Vault Daily Notes | Checkbox updates |

---

## Core Concept: TaskHash

### Definition

A **TaskHash** is an 8-character lowercase hexadecimal value generated using CRC32 algorithm. It provides immutable, globally unique identification for any task across all systems.

### Generation Algorithm

```
payload = f"task {len(source_id.encode())}\0{source_id}"
hash = format(zlib.crc32(payload) & 0xFFFFFFFF, '08x')
```

**Example:**
```
source_id = "github:acme/roadmap#42:Design API authentication"
TaskHash  = "a7f3c942"

Task Name with Hash: "Design API authentication (a7f3c942)"
```

### Properties

| Property | Value | Rationale |
|----------|-------|-----------|
| **Format** | 8-digit hex | Compact, readable, minimal collision risk |
| **Algorithm** | CRC32 | Fast, deterministic, collisions acceptable |
| **Immutability** | Never changes | Enables stable cross-system references |
| **Idempotence** | Same source_id → Same hash | Enables safe re-runs and verification |

### Source ID Format

The source_id encodes complete task origin information:

```
GitHub Issue Task:
  github:owner/repo#issue_num:task_name
  Example: github:acme/roadmap#42:Design API authentication

GitHub Comment Task:
  github:owner/repo#issue_num:comment#N:task_name
  Example: github:acme/roadmap#42:comment#0:Add rate limiting

Vault Daily Note Task:
  vault:relative/path/to/file.md:task_name
  Example: vault:Calendar/Daily/2026/05/2026-05-01.md:Review design docs
```

---

## Architecture

### System Components

```
┌───────────────────────────────────────────────────────────┐
│                  TaskHashSyncSystem                       │
├───────────────────────────────────────────────────────────┤
│                                                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   GitHub     │  │  Obsidian    │  │  OmniFocus   │     │
│  │   Issues     │  │   Vault      │  │              │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│         ↓                 ↓                 ↓             │
│  ┌──────────────────────────────────────────────────┐     │
│  │        prepare_sync.py (Data Preparation)        │     │
│  │  • Scan GitHub Issues + Vault Daily Notes        │     │
│  │  • Generate TaskHashes                           │     │
│  │  • Detect parent-child relationships             │     │
│  │  • Output tasks_to_sync.json                     │     │
│  └──────────────────────────────────────────────────┘     │
│         ↓                                                 │
│  ┌──────────────────────────────────────────────────┐     │
│  │   sync_state.json (State Management)             │     │
│  │  • TaskHash → OmniFocus ID mapping               │     │
│  │  • Sync status tracking                          │     │
│  │  • Completion timestamps                         │     │
│  └──────────────────────────────────────────────────┘     │
│         ↓                                                 │
│  ┌──────────────────────────────────────────────────┐     │
│  │  sync_to_omnifocus.py (MCP Tasks Addition)       │     │
│  │  • Resolve parentTaskHash → parentTaskId         │     │
│  │  • Add tasks via MCP tools                       │     │
│  │  • Update sync_state.json with OmniFocus IDs     │     │
│  └──────────────────────────────────────────────────┘     │
│         ↓                                                 │
│  ┌──────────────────────────────────────────────────┐     │
│  │  reverse_sync.py (Completion Reflection)         │     │
│  │  • Query OmniFocus for completed tasks           │     │
│  │  • Update GitHub Issue checkboxes                │     │
│  │  • Update Vault Daily Note checkboxes            │     │
│  │  • Update sync_state.json                        │     │
│  └──────────────────────────────────────────────────┘     │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

### Key Files

| File | Purpose |
|------|---------|
| `task_hash.py` | TaskHash generation and utilities (core library) |
| `prepare_sync.py` | Scan GitHub Issues + Vault; generate TaskHashes; output tasks_to_sync.json |
| `sync_to_omnifocus.py` | Resolve parentTaskHash → parentTaskId; validate; output mcp_batch_add_request.json |
| `update_sync_state.py` | Update sync_state.json after MCP execution |
| `reverse_sync.py` | Sync completed tasks from OmniFocus back to GitHub/Vault |
| `scan_omnifocus_inbox.py` | Detect OmniFocus Inbox tasks without TaskHash; add to Vault Daily Note |
| `run_complete_sync.py` | Debug utility: `--check-only` (workflow state) / `--cleanup` (reset queue) |
| `test_system.py` | Test suite for validating system components |
| `sync_state.json` | Central sync state database (TaskHash → OmniFocus ID mapping) |
| `tasks_to_sync.json` | Queue: output of prepare_sync.py, consumed by sync_to_omnifocus.py |
| `tasks_resolved.json` | Intermediate: parentTaskHash resolved to parentTaskId |
| `mcp_batch_add_request.json` | Formatted MCP batch_add_items request for Claude |
| `inbox_rename_requests.json` | List of edit_item calls for Claude to rename OmniFocus tasks |

---

## Synchronization Domains

### Domain 1: GitHub Issues → OmniFocus Projects

**Scope:**
- Issue title becomes an OmniFocus Project
- Issue body tasks (checkboxes) become child tasks of the Project
- Issue comments can contain additional tasks (hierarchical structure possible)

**Requirements:**
1. Issue title must include TaskHash: `"Build Mobile App (c4a2f819)"`
2. All body tasks must have checkboxes: `- [ ] Task name (hash)`
3. All body tasks must include TaskHash
4. Issue URL is stored in Project note field

**Example:**

GitHub Issue #42:
```
Title: Build Mobile App (c4a2f819)

- [x] Design user interface (a7f3c942)
- [ ] Implement authentication (b2e5d641)
- [ ] Set up CI/CD pipeline (f1c8a034)
- [ ] Write API documentation (e9d4b127)
```

OmniFocus Result:
```
PROJECT: Build Mobile App (c4a2f819)
  URL: https://github.com/acme/roadmap/issues/42
  ├── Design user interface (a7f3c942) ✅
  ├── Implement authentication (b2e5d641)
  ├── Set up CI/CD pipeline (f1c8a034)
  └── Write API documentation (e9d4b127)
```

### Domain 2: Obsidian Vault Daily Notes → OmniFocus Inbox

**Scope:**
- Daily Notes contain Inbox tasks and Projects without TaskHash
  - eg. `Later`, `Someday` and so on
- **Important**: Project names (containers) are NOT synced as tasks
  - Project names listed in `## Projects` section are metadata only
  - Only child tasks of TaskHashless Projects are synced to Vault
  - This prevents confusion with GitHub Issue-derived Projects
- Task hierarchy determined by Markdown indentation (tabs)
- All tasks must have checkboxes: `- [ ] Task name (hash)`

**Requirements:**
1. Tasks organized by calendar date in `Calendar/Daily/YYYY/MM/YYYY-MM-DD.md`
2. Hierarchy levels: parent at level 0, children at level 1, grandchildren at level 2
3. All tasks must include TaskHash
4. Parent-child relationships tracked via `parentTaskHash` in sync_state.json

**Example:**

Vault Daily Note (2026-05-15):
```markdown
- [ ] Process email queue (d3a8f741)
	- [ ] Review urgent messages (a1c5e892)
	- [ ] Archive old emails (b7f2c341)
		- [ ] Configure email filters (c9e6a052)
- [ ] Team standup meeting (f4b1d623)
```

OmniFocus Result:
```
INBOX:
  ├── Process email queue (d3a8f741)
  │   ├── Review urgent messages (a1c5e892)
  │   └── Archive old emails (b7f2c341)
  │       └── Configure email filters (c9e6a052)
  └── Team standup meeting (f4b1d623)
```

### Domain 3: Completion Reflection (Bidirectional)

**When task completed in OmniFocus:**
1. reverse_sync.py queries OmniFocus for completed tasks
2. Matches TaskHash to source location
3. Updates checkbox in GitHub Issue or Vault Daily Note: `- [x]` 
4. Updates sync_state.json with completion timestamp

**Flow:**
```
OmniFocus: Mark task complete
    ↓
reverse_sync.py: Query completed tasks
    ↓
Match via TaskHash to source location
    ↓
GitHub Issue: Update checkbox   OR   Vault Daily Note: Update checkbox
    ↓
sync_state.json: Record completion timestamp
```

---

## Implementation Details

### TaskHash Generation Process

**Step 1: Create Task**
```
GitHub Issue Title: "Refactor database schema"
GitHub Issue #: 15
```

**Step 2: Build Source ID**
```
source_id = "github:acme/backend#15:Refactor database schema"
```

**Step 3: Compute Hash**
```python
from task_hash import compute_hash
hash = compute_hash(source_id)  # → "d8a3e641"
```

**Step 4: Append to Task Name**
```
Updated Title: "Refactor database schema (d8a3e641)"
```

**Step 5: Update Source System**
```
Commit changes to GitHub Issue title
```

### Deduplication Logic

If a task already contains a hash (e.g., during re-sync), prepare_sync.py automatically removes it before recalculating:

```python
title = "Refactor database schema (d8a3e641)"

# Remove existing hash
title_without_hash = remove_hash(title)
# → "Refactor database schema"

# Recalculate hash using clean title
source_id = make_github_source_id("acme", "backend", 15, title_without_hash)
hash = compute_hash(source_id)
# → "d8a3e641" (same hash, proves idempotence)
```

**Result:** prepare_sync.py detects "already synced" and outputs 0 new tasks.

### Task Name Metadata Cleaning

All metadata is stripped before hash calculation to ensure stability:

**Before Cleaning:**
```
- [ ] [Review docs](https://docs.example.com) 📅 2026-05-20 (old_hash)
```

**Cleaning Process:**
1. Extract Markdown link: `[Review docs]` → display text
2. Extract URL: `https://docs.example.com` → store in OmniFocus note
3. Remove emoji: `📅 2026-05-20` → remove
4. Remove existing hash: `(old_hash)` → remove

**After Cleaning:**
```
Review docs
```

**Hash Calculation:**
```
source_id = "vault:Calendar/Daily/2026/05/2026-05-20.md:Review docs"
hash = compute_hash(source_id)  # → "a2f8c531"
```

**Final Task Name:**
```
- [ ] Review docs (a2f8c531)
```

**OmniFocus Entry:**
```
Task Name: Review docs (a2f8c531)
Note: https://docs.example.com
Due Date: 2026-05-20
```

### Parent-Child Relationship Management

**Vault Indentation → parentTaskHash:**

```markdown
- [ ] Sprint planning (hash1)
	- [ ] Create task backlog (hash2)
	- [ ] Prioritize items (hash3)
		- [ ] Estimate story points (hash4)
```

**Detection Process:**
1. Parse indentation level (tabs/spaces)
2. Maintain parent stack as we scan
3. When task at level N found, parent is top of stack at level N-1
4. Record parentTaskHash in task entry

**sync_state.json:**
```json
{
  "hash2": {
    "parent_task_hash": "hash1"
  },
  "hash3": {
    "parent_task_hash": "hash1"
  },
  "hash4": {
    "parent_task_hash": "hash3"
  }
}
```

**OmniFocus Result:**
```
INBOX:
  └── Sprint planning (hash1)
      ├── Create task backlog (hash2)
      └── Prioritize items (hash3)
          └── Estimate story points (hash4)
```

---

## Workflows

### Workflow A: Create New GitHub Issue (Project)

**Goal:** Convert GitHub Issue into OmniFocus Project with child tasks

**Steps:**

1. **Create Issue on GitHub**
   ```
   Title: Launch Q2 Marketing Campaign
   Body:
   - [ ] Design ad creative
   - [ ] Set up campaign tracking
   - [ ] Schedule social media posts
   - [ ] Analyze performance metrics
   ```

2. **Request Claude to Sync**
   ```
   "Sync GitHub Issue #X to OmniFocus as Project with child tasks"
   ```

3. **Claude Execution**
   - Generates TaskHash for issue title
   - Updates issue title: `"Launch Q2 Marketing Campaign (e5b7a291)"`
   - Generates TaskHash for each body task
   - Updates issue body with hashes:
     ```
     - [ ] Design ad creative (a1f4c892)
     - [ ] Set up campaign tracking (b3d8e641)
     - [ ] Schedule social media posts (c2a9f734)
     - [ ] Analyze performance metrics (d6e1b825)
     ```
   - Creates Project in OmniFocus
   - Adds all tasks as Project children
   - Updates sync_state.json

4. **Result in OmniFocus**
   ```
   PROJECT: Launch Q2 Marketing Campaign (e5b7a291)
   URL: https://github.com/acme/ops/issues/18
   ├── Design ad creative (a1f4c892)
   ├── Set up campaign tracking (b3d8e641)
   ├── Schedule social media posts (c2a9f734)
   └── Analyze performance metrics (d6e1b825)
   ```

5. **Verification**
   ```bash
   python3 prepare_sync.py
   # Output: ✓ Prepared 0 tasks for sync
   # (All tasks already synced - proves idempotence)
   ```

### Workflow B: Add Tasks to Existing Issue

**Goal:** Add new tasks to an existing GitHub Issue Project

**Steps:**

1. **Edit GitHub Issue Body**
   ```
   Add new line:
   - [ ] Create monthly report
   ```

2. **Run prepare_sync.py**
   ```bash
   python3 prepare_sync.py
   ```
   - Detects new task: "Create monthly report"
   - Generates TaskHash: "f2c6a419"
   - Outputs to tasks_to_sync.json

3. **Request Claude to Sync New Tasks**
   ```
   "Sync new tasks from GitHub Issue #X to OmniFocus"
   ```

4. **Claude Execution**
   - Updates GitHub Issue body with hash:
     ```
     - [ ] Create monthly report (f2c6a419)
     ```
   - Adds task to OmniFocus Project
   - Updates sync_state.json

5. **Result**
   ```
   PROJECT: Launch Q2 Marketing Campaign (e5b7a291)
   ├── [existing tasks...]
   └── Create monthly report (f2c6a419)
   ```

### Workflow C: Add Task to Vault Daily Note

**Goal:** Add task to daily inbox, automatically synced to OmniFocus

**Steps:**

1. **Edit Vault Daily Note**
   ```
   Calendar/Daily/2026/05/2026-05-20.md:
   
   - [ ] Approve budget request
   - [ ] Schedule team lunch
   	- [ ] Check restaurant availability
   	- [ ] Send meeting invite
   ```

2. **Run prepare_sync.py**
   - Detects tasks with checkboxes
   - Generates TaskHashes
   - Outputs to tasks_to_sync.json

3. **Request Claude to Sync**
   ```
   "Sync today's tasks to OmniFocus Inbox"
   ```

4. **Claude Execution**
   - Adds tasks to OmniFocus Inbox
   - Sets up parent-child relationships
   - Updates sync_state.json

5. **Verification**
   ```
   OmniFocus INBOX:
   ├── Approve budget request (c8a1e932)
   └── Schedule team lunch (d2f5a647)
       ├── Check restaurant availability (e7b4c193)
       └── Send meeting invite (a1d9f486)
   ```

### Workflow D: Complete Task in OmniFocus

**Goal:** Reflect task completion back to source systems with dates

**Steps:**

1. **Mark Task Complete in OmniFocus**
   - Check "Approve budget request (c8a1e932)"
   - Task has due_date: 2026-05-25

2. **Run reverse_sync.py**
   ```bash
   python3 reverse_sync.py
   ```
   - Queries OmniFocus for completed tasks with due dates
   - Matches TaskHash to source location
   - Updates checkboxes in Vault Daily Note and GitHub Issues
   - **Note**: TaskHashless Project names are NOT synced (managed in `## Projects` section only)

3. **Result in Vault Daily Note**
   ```
   - [x] Approve budget request (c8a1e932) 📅 2026-05-25 ✅ 2026-05-20
   ```
   
   **Format Details:**
   - `[x]` = checked (completed)
   - `(c8a1e932)` = TaskHash
   - `📅 2026-05-25` = Due date (from OmniFocus, if set)
   - `✅ 2026-05-20` = Completion date (added automatically)

4. **Task Routing (Reverse Sync)**
   - **GitHub Issue tasks** (TaskHash in source_id) → GitHub Issue checkbox updated
   - **Vault inbox tasks** → Vault Daily Note updated with dates
   - **TaskHashless Project container tasks** (Project names) → **NOT synced** (metadata only)
     - Project names managed in separate `## Projects` section
     - Prevents confusion with GitHub Issue-derived Projects

5. **Result in sync_state.json**
   ```json
   {
     "c8a1e932": {
       "status": "completed",
       "completed_at": "2026-05-20T14:32:47.123456",
       "due_date": "2026-05-25",
       "project_name": "Later"
     }
   }
   ```

---

## Data Structures

### sync_state.json Schema

Central state database tracking all tasks across systems.

```json
{
  "task_hash_value": {
    "source_id": "github:acme/ops#18:Design ad creative",
    "of_task_id": "kU7YLg_riXV",
    "of_task_name": "Design ad creative (a1f4c892)",
    "status": "open|completed|dropped",
    "task_type": "github_task|github_comment_task|vault_task|project",
    "parent_task_hash": "e5b7a291",
    "due_date": "2026-05-25",
    "synced_at": "2026-05-15T10:30:00.000000",
    "completed_at": "2026-05-18T14:45:30.000000"
  }
}
```

**Field Definitions:**

| Field | Type | Description |
|-------|------|-------------|
| `source_id` | string | Encodes complete task origin (GitHub/Vault + path/issue) |
| `of_task_id` | string | OmniFocus internal task ID; "pending" if not yet added |
| `of_task_name` | string | Task name as displayed in OmniFocus with hash |
| `status` | enum | "open", "completed", or "dropped" |
| `task_type` | enum | Identifies source domain for filtering |
| `parent_task_hash` | string | TaskHash of parent task; omitted if top-level |
| `due_date` | date | ISO format YYYY-MM-DD; omitted if no due date |
| `synced_at` | datetime | ISO format with microseconds; initial sync timestamp |
| `completed_at` | datetime | ISO format with microseconds; when marked complete in OmniFocus |

### tasks_to_sync.json Schema

Output of prepare_sync.py; contains tasks ready for addition to OmniFocus.

```json
{
  "tasks": [
    {
      "type": "project",
      "name": "Launch Q2 Marketing Campaign (e5b7a291)",
      "note": "https://github.com/acme/ops/issues/18",
      "hash": "e5b7a291",
      "source_id": "github:acme/ops#18:Launch Q2 Marketing Campaign"
    },
    {
      "type": "task",
      "name": "Design ad creative (a1f4c892)",
      "note": "",
      "projectName": "Launch Q2 Marketing Campaign (e5b7a291)",
      "hash": "a1f4c892",
      "source_id": "github:acme/ops#18:Design ad creative"
    },
    {
      "type": "task",
      "name": "Estimate story points (f3c7a154)",
      "note": "https://confluence.internal/estimation-guide",
      "projectName": "Sprint planning (b2d9e146)",
      "parentTaskHash": "b2d9e146",
      "hash": "f3c7a154",
      "source_id": "vault:Calendar/Daily/2026/05/2026-05-15.md:Estimate story points"
    }
  ],
  "prepared_at": "2026-05-15T10:30:00.000000",
  "total_count": 3
}
```

---

## Scripts Reference

### task_hash.py

Utility library for TaskHash generation and manipulation.

**Key Functions:**

```python
# Core hash generation
compute_hash(source_id: str) -> str
  # Generate 8-digit hex hash from source_id
  # Example: "d8a3e641"

make_github_source_id(owner, repo, issue_num, task_name) -> str
  # Build GitHub source_id
  # Example: "github:acme/ops#18:Design ad creative"

make_vault_source_id(relative_path, task_name) -> str
  # Build Vault source_id
  # Example: "vault:Calendar/Daily/2026/05/2026-05-15.md:Review docs"

# Task name manipulation
append_hash(task_name, source_id) -> str
  # Add hash to task name if not already present
  # "Design ad creative" → "Design ad creative (a1f4c892)"

remove_hash(task_name) -> str
  # Strip hash suffix from task name
  # "Design ad creative (a1f4c892)" → "Design ad creative"

has_hash(task_name) -> bool
  # Check if task name contains hash
  # Pattern: " (XXXXXXXX)" where X is hex digit

extract_hash(task_name) -> str | None
  # Extract hash from task name
  # "Design ad creative (a1f4c892)" → "a1f4c892"

# Markdown link handling
extract_markdown_links(text) -> (cleaned_text, urls_list)
  # Parse Markdown links and extract URLs
  # "[Design guide](https://example.com)" → ("Design guide", ["https://example.com"])

clean_markdown_links(task_name) -> str
  # Remove Markdown link syntax, keep display text only
  # "[Design guide](https://example.com)" → "Design guide"

get_markdown_urls(text) -> list
  # Extract URLs from Markdown links
  # "[Design guide](https://example.com)" → ["https://example.com"]
```

### prepare_sync.py

Data preparation engine; scans GitHub Issues and Vault Daily Notes to detect new tasks.

**Usage:**
```bash
python3 prepare_sync.py
```

**Process:**
1. Fetch open GitHub Issues via `gh` CLI
2. Parse issue bodies and comments for tasks (checkbox format)
3. Scan Vault Daily Notes (all .md files)
4. Generate TaskHash for each new task
5. Check sync_state.json to skip already-synced tasks
6. Detect parent-child relationships via indentation
7. Output tasks_to_sync.json

**Output Example:**
```
Fetching issues from acme/ops...
Found 3 open issues

⊘ Issue #18: Launch Q2 Marketing Campaign - already synced
  ⊘ Subtask: Design ad creative (a1f4c892) - already synced
  → Subtask: Review competitor analysis (c5e2f714) [NEW]

Scanning vault at /path/to/vault...
Found 128 markdown files

Found 3 tasks in Calendar/Daily/2026/05/2026-05-15.md
  ⊘ Approve budget request (c8a1e932) - already synced
  → Prepare presentation slides (d3a9f621) [NEW]
  → Schedule team lunch (d2f5a647) - already synced

✓ Prepared 2 tasks for sync
Output: /path/to/tasks_to_sync.json
```

### sync_to_omnifocus.py

Helper script to resolve parent-child relationships and validate tasks before adding to OmniFocus.

**Usage:**
```bash
python3 sync_to_omnifocus.py [--dry-run] [--verbose]
```

**Process:**
1. Load sync_state.json for parent task ID mappings
2. Load tasks_to_sync.json
3. Validate all tasks (required fields, hash format)
4. For each task with parentTaskHash: resolve → OmniFocus task ID
5. Generate `tasks_resolved.json` and `mcp_batch_add_request.json`

**Note:** Actual OmniFocus task addition is done via MCP tools (add_omnifocus_task, batch_add_items).

### update_sync_state.py

State management automation after MCP execution.

**Usage:**
```bash
python3 update_sync_state.py [--dry-run] [--verbose]
```

**Process:**
1. Load `tasks_resolved.json`
2. Extract TaskHash from each task
3. Add/update entries in `sync_state.json`
4. Clear `tasks_to_sync.json` (queue management)
5. Generate completion report

### run_complete_sync.py

Master orchestrator for the complete forward sync pipeline.

**Usage:**
```bash
python3 run_complete_sync.py             # Execute complete workflow
python3 run_complete_sync.py --check-only  # View current state only
python3 run_complete_sync.py --cleanup    # Reset for debugging
```

**Process:**
1. Check current state (tasks_to_sync.json)
2. Run sync_to_omnifocus.py (resolve + validate)
3. Output MCP execution instructions for Claude
4. Run update_sync_state.py (update state + clear queue)
5. Generate completion report

### scan_omnifocus_inbox.py

OmniFocus Inbox scanner for detecting new tasks without TaskHash.

**Usage:**
```bash
python3 scan_omnifocus_inbox.py --inbox-tasks <file> [--date YYYY-MM-DD] [--dry-run] [--verbose]
```

**Process:**
1. Load inbox tasks from JSON file (output of MCP get_inbox_tasks)
2. Detect tasks without TaskHash suffix
3. Generate TaskHash for each new task
4. Add new tasks to target Vault Daily Note
5. Update sync_state.json
6. Output `inbox_rename_requests.json` for Claude to call edit_item

### reverse_sync.py

Synchronizes task completion from OmniFocus back to GitHub Issues and Vault Daily Notes.

**Usage:**
```bash
python3 reverse_sync.py --completed-tasks <file>
```

**Process:**
1. Accept list of completed tasks from OmniFocus (via MCP query)
2. For each completed task:
   - Match TaskHash to source location in sync_state.json
   - Identify source system (GitHub Issue or Vault Daily Note)
   - Update checkbox: `- [ ]` → `- [x]`
   - Record completion timestamp
3. Update sync_state.json with completion records

**Example OmniFocus Query:**
```bash
# Get completed tasks today
mcp__omnifocus-local-server__filter_tasks(completedToday=true)
```

---

## Error Handling

### Idempotency Guarantees

All scripts are designed to be safely re-run multiple times:

**Problem:** User runs prepare_sync.py twice without syncing to OmniFocus
```bash
$ python3 prepare_sync.py
✓ Prepared 2 tasks for sync: {task1, task2}
# ... user forgets to sync ...
$ python3 prepare_sync.py
✓ Prepared 2 tasks for sync: {task1, task2}  # Same tasks, no change
```

**Solution:** sync_state.json tracks all synced tasks via source_id + hash combination.

### Hash Collision Detection

**Problem:** User manually edits task name, creating duplicate hash
```
Original: "Design API (a1f4c892)"  [synced to OmniFocus]
Edited:   "Design API v2 (a1f4c892)"  [manually added hash to avoid dupe]
```

**Solution:** prepare_sync.py uses source_id (not task name) for hash generation, so:
- Original: `source_id = "github:acme/ops#18:Design API"` → hash `a1f4c892`
- Edited: `source_id = "github:acme/ops#18:Design API v2"` → hash `DIFFERENT`

Hash collision avoided because it's based on source location + clean name, not task name.

### Missing Parent Error

**Problem:** Task has parentTaskHash but parent not yet synced
```json
{
  "f3c7a154": {
    "parent_task_hash": "UNKNOWN_HASH"
  }
}
```

**Solution:** sync_to_omnifocus.py logs warning and removes parentTaskHash:
```
⚠️  Warning: parentTaskHash 'UNKNOWN_HASH' not found in sync_state
Task 'Estimate story points (f3c7a154)' will be added as top-level
```

---

## Examples

### Example 1: Full Project Sync

**GitHub Issue Creation:**
```
Title: Implement OAuth 2.0 Integration
Issue #: 45
Repository: acme/auth-service

Body:
- [ ] Design OAuth flow diagram
- [ ] Implement authorization server
- [ ] Add token refresh mechanism
- [ ] Write security audit checklist
```

**Step 1: Generate Hashes**
```bash
python3 prepare_sync.py
```

**Output: tasks_to_sync.json**
```json
{
  "tasks": [
    {
      "type": "project",
      "name": "Implement OAuth 2.0 Integration (b7e3a514)",
      "note": "https://github.com/acme/auth-service/issues/45",
      "hash": "b7e3a514",
      "source_id": "github:acme/auth-service#45:Implement OAuth 2.0 Integration"
    },
    {
      "type": "task",
      "name": "Design OAuth flow diagram (a1f4c892)",
      "projectName": "Implement OAuth 2.0 Integration (b7e3a514)",
      "hash": "a1f4c892",
      "source_id": "github:acme/auth-service#45:Design OAuth flow diagram"
    },
    {
      "type": "task",
      "name": "Implement authorization server (c2d8e641)",
      "projectName": "Implement OAuth 2.0 Integration (b7e3a514)",
      "hash": "c2d8e641",
      "source_id": "github:acme/auth-service#45:Implement authorization server"
    },
    {
      "type": "task",
      "name": "Add token refresh mechanism (d5a9f734)",
      "projectName": "Implement OAuth 2.0 Integration (b7e3a514)",
      "hash": "d5a9f734",
      "source_id": "github:acme/auth-service#45:Add token refresh mechanism"
    },
    {
      "type": "task",
      "name": "Write security audit checklist (e8c1b825)",
      "projectName": "Implement OAuth 2.0 Integration (b7e3a514)",
      "hash": "e8c1b825",
      "source_id": "github:acme/auth-service#45:Write security audit checklist"
    }
  ],
  "prepared_at": "2026-05-15T10:30:00.000000",
  "total_count": 5
}
```

**Step 2: Update GitHub Issue**
```
Title: Implement OAuth 2.0 Integration (b7e3a514)

Body:
- [ ] Design OAuth flow diagram (a1f4c892)
- [ ] Implement authorization server (c2d8e641)
- [ ] Add token refresh mechanism (d5a9f734)
- [ ] Write security audit checklist (e8c1b825)
```

**Step 3: Sync to OmniFocus**
```
PROJECT: Implement OAuth 2.0 Integration (b7e3a514)
URL: https://github.com/acme/auth-service/issues/45
├── Design OAuth flow diagram (a1f4c892)
├── Implement authorization server (c2d8e641)
├── Add token refresh mechanism (d5a9f734)
└── Write security audit checklist (e8c1b825)
```

### Example 2: Hierarchical Daily Note Tasks

**Vault Daily Note (2026-05-20):**
```markdown
## Tasks

- [ ] Q2 Planning Session (b9f2c418)
	- [ ] Gather team input (a4e7d125)
	- [ ] Create timeline (c1f9a362)
		- [ ] Set milestone dates (d8b5e649)
		- [ ] Assign owners (e2a3f471)
	- [ ] Document roadmap (f7d1c894)

- [ ] Deploy version 2.5 (g5a8e123)
	- [ ] Run smoke tests (h1d6f745)
	- [ ] Monitor error logs (i9c2b387)
```

**OmniFocus Result:**
```
INBOX:
├── Q2 Planning Session (b9f2c418)
│   ├── Gather team input (a4e7d125)
│   ├── Create timeline (c1f9a362)
│   │   ├── Set milestone dates (d8b5e649)
│   │   └── Assign owners (e2a3f471)
│   └── Document roadmap (f7d1c894)
└── Deploy version 2.5 (g5a8e123)
    ├── Run smoke tests (h1d6f745)
    └── Monitor error logs (i9c2b387)
```

**sync_state.json Records:**
```json
{
  "b9f2c418": {
    "source_id": "vault:Calendar/Daily/2026/05/2026-05-20.md:Q2 Planning Session",
    "task_type": "vault_task"
  },
  "a4e7d125": {
    "source_id": "vault:Calendar/Daily/2026/05/2026-05-20.md:Gather team input",
    "parent_task_hash": "b9f2c418"
  },
  "c1f9a362": {
    "source_id": "vault:Calendar/Daily/2026/05/2026-05-20.md:Create timeline",
    "parent_task_hash": "b9f2c418"
  },
  "d8b5e649": {
    "source_id": "vault:Calendar/Daily/2026/05/2026-05-20.md:Set milestone dates",
    "parent_task_hash": "c1f9a362"
  },
  "e2a3f471": {
    "source_id": "vault:Calendar/Daily/2026/05/2026-05-20.md:Assign owners",
    "parent_task_hash": "c1f9a362"
  },
  "f7d1c894": {
    "source_id": "vault:Calendar/Daily/2026/05/2026-05-20.md:Document roadmap",
    "parent_task_hash": "b9f2c418"
  }
}
```

### Example 3: Task Completion Sync

**Scenario:** User marks "Design OAuth flow diagram (a1f4c892)" complete in OmniFocus

**OmniFocus Query Output:**
```
Completed Today:
- Design OAuth flow diagram (a1f4c892) at 2026-05-15 14:32:00
```

**reverse_sync.py Processing:**
1. Match TaskHash `a1f4c892` in sync_state.json
2. Find source_id: `github:acme/auth-service#45:Design OAuth flow diagram`
3. Identify source: GitHub Issue #45
4. Update GitHub Issue body:
   ```
   - [x] Design OAuth flow diagram (a1f4c892)
   ```
5. Update sync_state.json:
   ```json
   {
     "a1f4c892": {
       "status": "completed",
       "completed_at": "2026-05-15T14:32:00.000000"
     }
   }
   ```

**Result:**
- GitHub Issue #45 reflects completion: checkbox marked
- Vault Daily Notes (if any) reflect completion
- sync_state.json has completion record

---

## Design Principles

1. **TaskHash is Immutable**: Once generated, never changes. Enables reliable tracking.
2. **Source ID is Canonical**: Hash generated from source_id, not task name. Enables name changes without breaking sync.
3. **No Task Name Changes to Break Sync**: Deduplication logic (remove_hash) ensures hash calculation is stable.
4. **Parent-Child via Hash, Not Name**: Uses parentTaskHash, not parentTaskName. Enables parent name changes.
5. **Metadata Extraction**: URLs extracted to notes field, dates extracted to due_date field. Keeps task names clean.
6. **Idempotent Operations**: Safe to re-run; produces same results multiple times.
7. **Domain Separation**: GitHub Issues are Project source; Vault Daily Notes are Inbox source.

---

## Task Format Reference

### Vault Daily Note Task Format

**Standard Format:**
```
- [ ] Task Name (hash) [📅 due_date] [✅ completion_date]
```

**Examples:**

1. **Simple task (no dates):**
   ```
   - [ ] Review proposal (a1f4c892)
   ```

2. **Task with due date:**
   ```
   - [ ] Review proposal (a1f4c892) 📅 2026-05-25
   ```

3. **Completed task with due date and completion date:**
   ```
   - [x] Review proposal (a1f4c892) 📅 2026-05-25 ✅ 2026-05-20
   ```

4. **Task with hierarchy (Later project):**
   ```
   - [ ] Parent task (abc12345)
   	- [ ] Child task (def67890) 📅 2026-05-25
   		- [x] Grandchild task (ghi34567) ✅ 2026-05-20
   ```

**Field Positioning:**
- `(hash)` = TaskHash, immediately after task name (required)
- `📅 YYYY-MM-DD` = Due date, before completion date (optional)
- `✅ YYYY-MM-DD` = Completion date, always last (added by reverse_sync)

**Note:** All dates are in ISO format (YYYY-MM-DD)

---

## Implemented Features & Status

### ✅ Completed (v2.3)

- [x] Immutable TaskHash generation (CRC32)
- [x] GitHub Issue → OmniFocus Project conversion
- [x] Forward sync (GitHub/Vault → OmniFocus)
- [x] Reverse sync (OmniFocus → GitHub/Vault)
- [x] Parent-child hierarchy support (Vault nested tasks via parentTaskHash)
- [x] Due date synchronization (Vault ↔ OmniFocus)
- [x] Completion date tracking (✅ YYYY-MM-DD format)
- [x] TaskHash-less Project support (Later → Vault Inbox; Project container names not synced as tasks)
- [x] Indentation-based hierarchy detection
- [x] Markdown link extraction
- [x] State management with audit trail
- [x] Manual sync trigger via user keyword (Hook + Claude 3-step workflow)

### 📋 Future Enhancements

- [ ] Optional scheduled sync (currently manual-only by design)
- [ ] Conflict resolution (task modified in multiple systems)
- [ ] Tag propagation (sync tags between OmniFocus and GitHub labels)
- [ ] Comment integration (sync GitHub Issue comments to OmniFocus task notes)
- [ ] Performance optimization for large issue sets
- [ ] Web dashboard for sync status monitoring
- [ ] Bulk operations (sync multiple issues at once)

---

## Implementation Status

### Current State (v2.3 - May 4, 2026)

#### ✅ Fully Working

| Flow | Status | Component | Trigger |
|------|--------|-----------|---------|
| Vault Daily Notes → OmniFocus | ✅ Complete | `prepare_sync.py` + MCP | Manual sync |
| GitHub Issues → OmniFocus | ✅ Complete | `prepare_sync.py` + MCP | Manual sync |
| OmniFocus (completed) → Vault/GitHub | ✅ Complete | `reverse_sync.py` | Manual sync |
| OmniFocus Inbox → Vault Daily Note | ✅ Complete | `scan_omnifocus_inbox.py` | Manual sync |

#### Sync Trigger

All sync is initiated manually via user command (e.g., "sync tasks"):

1. Hook auto-runs `prepare_sync.py`
2. Claude executes all 3 steps: Forward → Reverse → Inbox Sync
3. Results reported to user

No scheduled/automatic sync. Manual trigger only by design.

#### ⚠️ Known Limitations

1. **GitHub Comment Integration**: Partial support
   - Status: Working but could be more robust

2. **Conflict Detection**: Not implemented
   - Status: No detection if task modified in multiple systems

3. **Performance**: Not optimized for large task sets
   - Concern: May need optimization at 1000+ tasks

---

## Roadmap

### Future Enhancements

- [ ] Tag propagation (GitHub labels ↔ OmniFocus tags)
- [ ] GitHub issue state sync (open/closed)
- [ ] Conflict detection and resolution
- [ ] Performance optimization for 1000+ tasks
- [ ] GitHub comment integration improvements

---

## Architecture Notes

### Design Decisions

1. **CRC32 over UUID**: Chose CRC32 for deterministic hash generation
   - Benefit: Same source always produces same hash
   - Trade-off: Lower collision resistance than UUID
   - Rationale: Idempotence more important than collision risk

2. **Source ID in State Only**: Never expose source_id in OmniFocus
   - Benefit: Clean task names without technical metadata
   - Trade-off: Must always reference sync_state.json for origin
   - Rationale: OmniFocus is UX-focused; tracking is separate

3. **Manual OmniFocus Inbox Sync**: By design, not automatic
   - Benefit: User controls which Inbox tasks sync to Vault
   - Trade-off: Requires explicit request
   - Rationale: OmniFocus Inbox is "working space"; Vault is "archive"
   - Future: Will add auto-detection with user override

4. **ParentTaskHash over ParentTaskName**: Use hash for hierarchy
   - Benefit: Relationships stable if parent name changes
   - Trade-off: Need state lookup for resolution
   - Rationale: Task names are mutable; hashes are immutable

---

## Support & Debugging

### Common Issues

**Issue:** prepare_sync.py shows "Prepared 0 tasks" even after adding new tasks to GitHub Issue

**Solution:**
1. Verify GitHub Issue title includes TaskHash
2. Verify all body tasks include TaskHash
3. Run `gh issue view <issue_num>` to confirm changes were saved
4. Check sync_state.json for existing entries matching source_id

**Issue:** Tasks in OmniFocus but not marked as synced in sync_state.json

**Solution:**
1. Manually run `sync_to_omnifocus.py` to resolve parent tasks
2. Verify OmniFocus task IDs match those in sync_state.json
3. Re-run prepare_sync.py to refresh state

**Issue:** Completion not reflected back to GitHub Issue

**Solution:**
1. Verify reverse_sync.py has access to GitHub credentials
2. Check that TaskHash in OmniFocus matches sync_state.json
3. Run reverse_sync.py with verbose output to debug

---

## Contributing

When modifying TaskHashSyncSystem:

1. **Do not change source_id format** - This breaks hash calculation for all existing tasks
2. **Do not remove TaskHash stripping logic** - Enables idempotence
3. **Always use task_hash.py** for hash operations - Ensures consistency
4. **Test with example tasks** - Use provided examples before deploying to live systems
5. **Update this README** when adding new features

---

**Version:** 2.4  
**Last Updated:** 2026-05-04  
**Maintained By:** [@x5gtrn](https://daisuke.masuda.tokyo)
