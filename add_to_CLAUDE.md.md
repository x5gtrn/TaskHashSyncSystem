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

**OmniFocus Projects without TaskHash (Later, Someday, etc.)**:
- **Project names are NOT synced as tasks** (critical distinction)
- Project names managed in `## Projects` section of Vault (metadata only)
- Prevents confusion with GitHub Issue-derived Projects
- Only child tasks of these Projects are synced to Vault as Inbox tasks
- Example: "Later" Project container name is NOT a task; child tasks ARE tasks

**Vault Daily Notes (Calendar/ folder - Inbox)**:
- **ONLY Calendar/ folder is synced** (Daily Notes, time-based notes)
- Contains Inbox tasks only (excludes Atlas, Efforts, x/)
- **Project containers listed in `## Projects` section (not as tasks)**
- Regular tasks in `## Tasks` section organized by date
- Syncs with OmniFocus **Inbox**

**Example**:
```
GitHub Issue #42: Setup Financial Accounts (a7f3c942)
- [x] Connect Revolut Account (b2d8e641)
- [ ] Add Credit Card Details (c5e1a392)
- [ ] Set Up Bank Transfers (d9f4c125)

OmniFocus:
  P: Setup Financial Accounts (a7f3c942)  ← Issue title as Project (GitHub)
     • Connect Revolut Account (b2d8e641) ✅  ← Issue body task
     • Add Credit Card Details (c5e1a392)    ← Issue body task
     • Set Up Bank Transfers (d9f4c125)      ← Issue body task

  P: Later                                   ← OmniFocus Native Project (no TaskHash)
     • Later                                   ← Container name (NOT a task)
     • Process backlog items (f6c3d927)       ← Child task (synced to Vault)
     • Review old notes (g7d2e893)            ← Child task (synced to Vault)

  INBOX:
     • Watch Training Videos (g8b1e564)      ← Vault task
     • Learn Japanese Grammar (h4d9f782)     ← Vault task
        • Master Hiragana Characters (i7c2a401) ← Child task (indented in Vault)

Vault Daily Note:
  ## Tasks
  - [ ] Watch Training Videos (g8b1e564)
  - [ ] Learn Japanese Grammar (h4d9f782)
     - [ ] Master Hiragana Characters (i7c2a401)
  - [ ] Process backlog items (f6c3d927)      ← Synced from Later Project
  - [ ] Review old notes (g7d2e893)           ← Synced from Later Project

  ## Projects
  Project containers (NOT synced as tasks):
  - Later                                      ← Container only (NOT in sync list)
  - Someday                                    ← Container only (NOT in sync list)
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

### 3.5. Automatic Processing of GitHub Issues without TaskHash

**MANDATORY RULE**: When GitHub Issues **without TaskHash in the title** are detected, Claude **MUST automatically process them immediately** — never skip or defer this:

**Automatic Processing Workflow**:
1. **Scan GitHub Issues** for any missing TaskHashes in titles
2. **Generate TaskHash for Issue title** using `task_hash.py`
3. **Generate TaskHash for all Issue body tasks** using `task_hash.py`
4. **Update GitHub Issue**:
   - Update title to include TaskHash: `Issue Title (hash)`
   - Update all tasks in body to include hashes: `- [ ] Task Name (hash)`
   - Use `gh issue edit` command
5. **Create OmniFocus Project** with `batch_add_items()`:
   - Create Project with Issue title + hash
   - Create child tasks for each Issue body task
   - Add GitHub Issue URL to Project note
6. **Update sync_state.json**:
   - Record Issue title as Project entry
   - Record all Issue body tasks as child task entries
   - Set `task_type: "github_project"` for title, `task_type: "github_task"` for body tasks
   - Set `parent_task_hash: <issue_hash>` for all body tasks
   - Set `status: "open"` for all new entries

**Why This Matters**:
- Ensures **zero GitHub Issues are unsynced** — any Issue created in GitHub must be immediately integrated
- Prevents orphaned Issues that exist only in GitHub without OmniFocus Project
- Maintains **bidirectional consistency**: GitHub is source of truth, OmniFocus is working copy, Vault is archive
- TaskHash enables reliable reverse sync when tasks are completed

**Example**:
```
Detected Issue #2: "Product Roadmap Q4" (NO HASH)
→ Generate: (60c6d084)
→ Update GitHub title: "Product Roadmap Q4 (60c6d084)"
→ Generate body task hashes: (35efa56a), (62d90568)
→ Update GitHub body with hashes
→ Create OmniFocus Project "Product Roadmap Q4 (60c6d084)"
→ Add child tasks to OmniFocus Project
→ Update sync_state.json with all 3 entries
```

**Integration with Manual Sync**:
- This processing happens **before** the 3-step sync workflow
- During manual sync (user says "sync tasks"), if any Issues lack TaskHash, they are automatically processed first
- After automatic processing, the normal 3-step sync continues (Forward, Reverse, Inbox)

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
- [ ] Complete Q4 Product Planning (h4d9f782)     [Level 0]
	- [ ] Review market research (i7c2a401) [Level 1, parent: h4d9f782]
	- [ ] Define feature roadmap (j5f8b634)     [Level 1, parent: h4d9f782]
		- [ ] Prioritize bug fixes (k9e3c171) [Level 2, parent: j5f8b634]
```

**OmniFocus Structure**:
```
INBOX:
   • Complete Q4 Product Planning (h4d9f782)
      • Review market research (i7c2a401)
      • Define feature roadmap (j5f8b634)
         • Prioritize bug fixes (k9e3c171)
```

### 5. Forward Sync (GitHub/Vault → OmniFocus)

**Data Preparation** (`prepare_sync.py`):
1. Scan GitHub Issues (body + all comments)
2. **Scan ONLY Calendar/ folder in Vault** (Daily Notes, time-based notes)
   - Excludes: Atlas/, Efforts/, x/ (knowledge, projects, scripts)
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
- Inbox tasks (Vault Calendar/ folder) → OmniFocus Inbox (maintain hierarchy)

### 6. Reverse Sync (OmniFocus → GitHub/Vault)

**Completion Reflection** (`reverse_sync.py`):
1. Query OmniFocus for completed tasks via MCP `filter_tasks(completedToday=true)`
2. Match completed tasks to source locations using TaskHash
3. Update checkboxes in GitHub Issues and Vault files
4. Sync due dates (if changed in OmniFocus)
5. Add completion dates to Vault tasks
6. Update `sync_state.json` with completion timestamp

**Project Task Routing**:
- **GitHub Issue Project** (created from GitHub Issues) → Sync back to GitHub Issue
- **TaskHashless Project** (Native OmniFocus projects like "Later"):
  - **Project container names are NOT synced as tasks** ← NEW: Project container is metadata only
  - Project names are listed in Vault `## Projects` section (not as tasks)
  - **Only child tasks of Projects are synced to Vault as Inbox tasks**
  - Due dates are reflected in Vault if present: `- [ ] Task (hash) 📅 2026-05-03`
  - If due date changes or is deleted in OmniFocus, sync reflects the change
  - **Purpose**: Distinguish between GitHub Issue Projects and TaskHashless Projects

**Completion Date Format**:
- Add completion dates to Vault Daily Notes: `- [x] Task (hash) 📅 due 2026-05-03 ✅ 2026-05-01`
- Format: `✅ YYYY-MM-DD` (after TaskHash, at end of line)
- Do not overwrite existing completion dates (idempotent)

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
- **SCOPES TO CALENDAR FOLDER ONLY** — scans `Calendar/*.md` files recursively
- Does NOT scan:
  - `Atlas/` (knowledge, MOCs, references)
  - `Efforts/` (project metadata)
  - `x/` (scripts, templates, AI-generated content)
- Extracts unchecked tasks via regex: `- \[ \]\s*(.+?)(?:\n|$)`
- Generates immutable TaskHash for each task

**Hierarchy Detection**:
- Tab/space indentation indicates parent-child relationships
- Parent stack maintained during parsing
- Converts indentation to `parent_task_hash` reference
- Handles arbitrary nesting depth (parent, child, grandchild, etc.)

**Task Type Filtering**:
- **Project container tasks** (in `## Projects` section, e.g., "Later", "Someday") → Skipped; not synced
- **Children of Project containers** → Also skipped (they belong to the Project, not Vault Inbox)
- **Top-level Daily Note tasks** → Synced to OmniFocus Inbox
- **Nested Daily Note tasks** (children of real tasks) → Synced to OmniFocus Inbox with `parentTaskHash` for hierarchy
- **GitHub Issue tasks** → Synced to OmniFocus Projects only (not Vault)

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

### 11. OmniFocus Inbox → Vault Reflection (Manual via Claude)

**Purpose**: Sync OmniFocus Inbox tasks (TaskHash-less) to Vault Daily Notes.

**Why separate?**
- GitHub Issues: Full task lists → OmniFocus Projects
- Vault Daily Notes: Source of truth for Inbox tasks
- OmniFocus Inbox: Working space; Vault is the archive
- This flow: OmniFocus native tasks → Vault organization

**Detection**: OmniFocus task names **without** `(hash)` suffix

**Process** (Automated via `scan_omnifocus_inbox.py`):
1. Claude calls `mcp__omnifocus-local-server__get_inbox_tasks`
2. Claude saves result as `inbox_tasks_raw.json`
3. Claude runs `python3 scan_omnifocus_inbox.py --inbox-tasks inbox_tasks_raw.json`
   - Detects tasks without TaskHash
   - Generates TaskHash using `task_hash.py`
   - Adds to today's Vault Daily Note (creates if missing)
   - Updates sync_state.json
   - Outputs `inbox_rename_requests.json`
4. Claude reads `inbox_rename_requests.json` and calls `edit_item` for each task
   - **Appends TaskHash to OmniFocus task name** (mandatory for tracking)
5. Task now tracked with `(hash)` in both OmniFocus AND Vault

**Example Workflow**:
```
User: "I have these in the Later project.
       Please add them to today's Daily Note:
       - Learn Mandarin (due: 2026-05-15)
       - Fix broken link"

Claude:
1. Generate TaskHash:
   - source_id: vault:Calendar/Daily/2026/05/2026-05-01.md:Learn Mandarin
   - hash: (computed)
   
2. Add to Vault Daily Note:
   - [ ] Learn Mandarin (hash) 📅 2026-05-15
   - [ ] Fix broken link (hash)

3. Update sync_state.json:
   {
     "hash1": {
       "source_id": "vault:Calendar/Daily/...:Learn Mandarin",
       "of_task_id": "omnifocus_id",
       "of_task_name": "Learn Mandarin (hash1)",
       "status": "open",
       "task_type": "vault_task",
       "due_date": "2026-05-15",
       "synced_at": "..."
     },
     "hash2": {
       "source_id": "vault:Calendar/Daily/...:Fix broken link",
       "of_task_id": "omnifocus_id",
       "of_task_name": "Fix broken link (hash2)",
       "status": "open",
       "task_type": "vault_task",
       "synced_at": "..."
     }
   }
```

**Current Status**:
- ✅ Manual process works (tested & verified)
- ⚠️ Requires explicit user request to Claude
- ✅ Automated scanner (`scan_omnifocus_inbox.py`) — implemented

**Important Notes**:
- This is the REVERSE of Vault→OmniFocus flow
- Use when OmniFocus is your daily driver but Vault is your archive
- Only untracked tasks (no hash) should be synced this way
- Due dates sync from OmniFocus to Vault (📅 emoji)
- Completion status updates via reverse_sync.py

### 11.5. TaskHash-less OmniFocus Task Routing (New)

**Problem**: When a user adds a task to OmniFocus (Inbox or Project) without TaskHash, the task must be classified and synced to the correct destination:
- **If parent is TaskHash-less Project** (Later, Someday, etc.) → Sync to Vault Daily Note as Inbox task
- **If parent is GitHub Issue Project** (TaskHash-bearing) → Add to GitHub Issue as new task
- **If no parent (Inbox task)** → Sync to Vault Daily Note as Inbox task

**Detection & Classification** (`scan_omnifocus_inbox.py` extended):

1. **Query OmniFocus for TaskHash-less tasks**:
   ```
   For each Inbox task without (hash) suffix:
     a. Detect if task has a parent task
     b. If parent exists:
        - Query parent task by ID/name
        - Check if parent name matches a GitHub Issue Project (by checking sync_state.json)
        - If match found: classify as "github_issue_child"
        - If no match: classify as "project_child"
     c. If no parent: classify as "inbox_standalone"
   ```

2. **Routing Logic**:
   ```
   TaskHash-less Task (no hash):
   ├─ Has parent task?
   │  ├─ YES: Parent in sync_state as github_project?
   │  │  ├─ YES → Route to GitHub Issue (add to Issue body)
   │  │  └─ NO  → Route to Vault Daily Note (with parent indication)
   │  └─ NO: → Route to Vault Daily Note (as Inbox task)
   ```

3. **GitHub Issue Addition Workflow** (for github_issue_child tasks):
   - Identify parent Project's source_id: `github:owner/repo#issue_num:...`
   - Extract issue number from source_id
   - Generate TaskHash for new task: `source_id = github:owner/repo#issue_num:task_name`
   - Add to GitHub Issue body as: `- [ ] task_name (hash)`
   - Create OmniFocus task with hash (rename existing task)
   - Update sync_state.json with new task entry

**Example Scenario**:
```
OmniFocus Inbox (TaskHash-less):
  • Implement OAuth flow (no hash, parent: Backend API Project)
  • Setup monitoring dashboard (no hash, no parent)

Processing:
  Task A:
    → Parent = "Backend API (60c6d084)"
    → sync_state shows: task_hash=60c6d084, source_id=github:x5gtrn/LIFE#2:...
    → CLASSIFY: github_issue_child
    → ACTION: Add to GitHub Issue #2 body as new task
    → Generate hash for "Implement OAuth flow"
    → Update Issue: - [ ] Implement OAuth flow (hash)
    → Rename OmniFocus task: "Implement OAuth flow" → "Implement OAuth flow (hash)"

  Task B:
    → No parent
    → CLASSIFY: inbox_standalone
    → ACTION: Add to today's Vault Daily Note
    → Generate hash for "Setup monitoring dashboard"
    → Add to Vault: - [ ] Setup monitoring dashboard (hash)
    → Rename OmniFocus task: "Setup monitoring dashboard" → "Setup monitoring dashboard (hash)"
```

**Implementation in `scan_omnifocus_inbox.py`**:
```python
# Step 1: Get all Inbox tasks (including TaskHash-less)
inbox_tasks = get_inbox_tasks()

# Step 2: Filter for TaskHash-less tasks
hashless_tasks = [t for t in inbox_tasks if not has_hash(t['name'])]

# Step 3: For each TaskHash-less task, determine routing
for task in hashless_tasks:
    parent_info = get_parent_task(task['id'])
    
    if parent_info:
        parent_hash = extract_hash(parent_info['name'])
        
        if parent_hash and is_github_project(parent_hash, sync_state):
            # Route to GitHub Issue
            issue_info = get_github_issue_from_parent_hash(parent_hash, sync_state)
            add_to_github_issue(issue_info, task)
            
        else:
            # Route to Vault (TaskHashless Project child)
            add_to_vault_daily_note(task, parent_indication=parent_info['name'])
    else:
        # Route to Vault (Inbox standalone)
        add_to_vault_daily_note(task)
```

**Key Rules**:
1. **Never create orphaned TaskHash-less tasks** — All OmniFocus tasks must eventually receive a TaskHash
2. **GitHub Issue takes priority** — If task is child of GitHub Issue Project, add to Issue before Vault
3. **Generate hash before commit** — Create TaskHash immediately when classifying, before adding to destination
4. **Update OmniFocus task name** — Append hash to task name in OmniFocus (essential for tracking)
5. **Idempotency** — If task already has hash, skip processing

### 12. Manual Sync Trigger

**Design**: No automatic/scheduled sync. All sync is triggered manually by the user via the keyword **"sync tasks"**.

#### How It Works

When the user says **"sync tasks"** or equivalent command:

1. **Hook fires automatically** (`.claude/hooks/skill_sync.sh`):
   - Detects the sync keyword in the user's prompt
   - Runs `prepare_sync.py` to scan Vault + GitHub Issues for new tasks
   - Outputs results and instructs Claude to run the full 3-step workflow

2. **Claude executes all 3 steps without waiting for confirmation**:

#### STEP 1 — Forward Sync (Vault/GitHub → OmniFocus)
- Read `tasks_to_sync.json` (output of `prepare_sync.py`)
- If new tasks exist: run `python3 sync_to_omnifocus.py`
- Adds new tasks to OmniFocus Inbox or Projects

#### STEP 2 — Reverse Sync (OmniFocus → Vault/GitHub)
- Call MCP: `mcp__omnifocus-local-server__filter_tasks` with `completedToday=true`
- Save result as **`completed_tasks_raw.json`** in the format:
  ```json
  {"completed_tasks": ["Task Name (hash)", "Another Task (hash)"]}
  ```
  *(plain list `[...]` is also accepted)*
- Run `python3 reverse_sync.py --completed-tasks completed_tasks_raw.json`
- Reflects completed tasks back to Vault checkboxes and GitHub Issue checkboxes

#### STEP 3 — Inbox Sync (OmniFocus Inbox → Vault Daily Note)
- Call MCP: `mcp__omnifocus-local-server__get_inbox_tasks`
- Save result as **`inbox_tasks_raw.json`** in the format:
  ```json
  {"tasks": [{"id": "OFTaskID", "name": "Task Name", "due_date": null}]}
  ```
  *(plain list `[...]` is also accepted)*
- Run `python3 scan_omnifocus_inbox.py --inbox-tasks inbox_tasks_raw.json`
- Adds new OmniFocus Inbox tasks (without TaskHash) to today's Vault Daily Note
- For each new task, call MCP: `mcp__omnifocus-local-server__edit_item` to append TaskHash to OmniFocus task name

**Example**:
```
User: "sync tasks"
Claude:
  [Hook runs prepare_sync.py automatically]
  STEP 1: tasks_to_sync.json → OmniFocus (new tasks pushed)
  STEP 2: OmniFocus completed → Vault/GitHub (checkboxes updated)
  STEP 3: OmniFocus Inbox → Vault Daily Note (new tasks added)
  → Reports results to user
```

#### Pre-Sync: Automatic GitHub Issue Processing
**Before executing the 3 steps above**, Claude **MUST automatically process any GitHub Issues missing TaskHash**:

1. **Detect**: Scan all GitHub Issues for TaskHash in title
2. **Generate**: Create TaskHash for Issue title and all body tasks
3. **Update**: Update GitHub Issue with hashes appended
4. **Create**: Add Project to OmniFocus with tasks as children
5. **Record**: Update sync_state.json with all entries

This ensures **every GitHub Issue has a TaskHash** before any sync occurs. See section **3.5. Automatic Processing of GitHub Issues without TaskHash** for details.

#### Hook Configuration
- **File**: `.claude/hooks/skill_sync.sh`
- **Config**: `.claude/settings.json`
- **Trigger patterns**: `sync tasks` | `skill sync` | manual user request
- **RemoteTrigger**: Disabled (was `trig_011of32NVNJqZ9Cbn5UWFp4D`, now `enabled: false`)

**IMPORTANT**: 
1. Claude must **first process any GitHub Issues without TaskHash** (automatic)
2. Then execute all 3 sync steps, regardless of whether `prepare_sync.py` found new tasks
3. Steps 2 and 3 are always necessary to reflect OmniFocus state

## Workflow

**User adds task to Vault Daily Note** (Calendar folder):
```
1. Edit Calendar/Daily/2026/05/2026-05-01.md (only Calendar/ folder is synced)
   Add: - [ ] Buy coffee (or [Buy coffee](url) 📅 2026-05-05)

2. Run: python3 x/Scripts/TaskHashSyncSystem/prepare_sync.py
   → Scans Calendar/ folder only
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

## Implemented Features


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
- ✅ **Automatic GitHub Issue TaskHash generation** (detect missing hashes, auto-process)
- ✅ **TaskHash-less task routing** (parent-aware classification & auto-sync)
  - GitHub Issue Project children → Auto-add to GitHub Issue
  - TaskHashless Project children → Auto-add to Vault Daily Note
  - Inbox standalone → Auto-add to Vault Daily Note
  - All routes ensure TaskHash assignment

## Files Location

**Active Runtime Files** (required for sync workflow):
```
x/Scripts/TaskHashSyncSystem/
├── README.md                    # Complete specification document
├── task_hash.py                 # TaskHash generation + utilities (used by all scripts)
├── prepare_sync.py              # Data preparation + GitHub Issue auto-processing (STEP 0)
├── sync_to_omnifocus.py         # Forward sync: resolves hashes, adds to OmniFocus (STEP 1)
├── reverse_sync.py              # Reverse sync: reflects completions to GitHub/Vault (STEP 2)
├── scan_omnifocus_inbox.py      # Inbox sync: adds new Inbox tasks to Vault (STEP 3)
├── sync_state.json              # Sync state tracking (primary key: TaskHash)
└── tasks_to_sync.json           # Prepared tasks waiting for sync (output of prepare_sync.py)
```

**Documentation**:
- [[x/Scripts/TaskHashSyncSystem/README.md]] - Main specification document

**Removed Files** (May 4, 2026):
- ~~run_complete_sync.py~~ — Redundant orchestrator (Claude handles 3-step execution)
- ~~update_sync_state.py~~ — State updates now integrated into sync_to_omnifocus.py and reverse_sync.py

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
8. **Project name exclusion**: TaskHashless Project container names are NOT synced as tasks
   - Only child tasks of TaskHashless Projects are synced
   - Prevents confusion with GitHub Issue-derived Projects
9. **Date positioning in Vault**: Due date (📅) before completion date (✅)
10. **Robust pattern matching**: Handle indentation, trailing spaces, multi-line tasks
11. **TaskHash-less task routing**: Automatic classification based on parent relationship
    - GitHub Issue Project child → Add to GitHub Issue
    - TaskHashless Project child → Add to Vault Daily Note
    - Inbox standalone → Add to Vault Daily Note
    - All routes must result in TaskHash assignment
12. **No orphaned tasks**: Every task in OmniFocus must have a TaskHash and source location

## Current Implementation Status

### ✅ Completed (v2.4 - May 4, 2026)
- Immutable TaskHash generation (CRC32)
- GitHub Issue → OmniFocus Project conversion
- Vault Daily Notes → OmniFocus Inbox sync
- OmniFocus completion → GitHub/Vault reflection
- Parent-child hierarchy via parentTaskHash
- Markdown link extraction to note field
- Due date synchronization (📅 emoji)
- Indentation-based hierarchy detection
- Domain separation (Projects vs. Inbox)
- State management with audit trail
- TaskHash-less Project handling (Later → Vault)
- Completion date tracking (`✅ YYYY-MM-DD`)
- **Full 3-step sync execution on manual trigger** ✨
- **Hook-based full sync trigger** ✨
- **Manual sync mode activated** ✨
- **TaskHash-less task automatic routing** ✨ (PARTIAL)
  - ✅ Manual detection of orphaned TaskHash-less tasks
  - ✅ GitHub Issue routing (tested & verified)
  - ⚠️ Automatic classification logic (in progress - see section 11.5)
  - ⚠️ Full bidirectional routing (needs implementation)
  
#x/claude
