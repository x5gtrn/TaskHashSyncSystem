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
- Issue body tasks + comment tasks (if formatted as `- [ ]`) = Project tasks (all with TaskHash)
  - **Note**: Comments without checkbox-formatted tasks do NOT generate metadata
  - Only comments containing `- [ ] Task` format are processed
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
   - **Issue comments**: Only extract tasks formatted as `- [ ] Task name`
   - Comments without checkbox tasks do NOT generate metadata
2. **Scan ONLY Calendar/ folder in Vault** (Daily Notes, time-based notes)
   - Excludes: Atlas/, Efforts/, x/ (knowledge, projects, scripts)
3. Extract unchecked tasks: `- [ ] Task name` format
4. Generate TaskHash for each task
5. Detect parent-child relationships via indentation
6. **Write TaskHash back to Vault Daily Notes** (NEW: STEP 2.5)
   - Appends hash to original task lines: `- [ ] Task (hash)`
   - Ensures Vault and OmniFocus stay synchronized
   - Idempotent: safe to re-run multiple times
7. Output `tasks_to_sync.json`
8. Check `sync_state.json` to skip already-synced tasks

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
- Extracts tasks from body AND all comments (checkbox format only: `- [ ] Task`)
- Each issue becomes an OmniFocus Project
- Comment tasks become subtasks with project hierarchy
- **Smart Comment Handling**: Comments without checkbox tasks do not generate metadata
  - Prevents clutter from non-task comments (e.g., discussion, links, notes)

**Issue Updates**:
- Uses `gh issue edit` for batch updates
- Pattern: `- [ ] TaskName` → `- [x] TaskName`
- Preserves TaskHash in task name

### 11. OmniFocus All-Tasks Scan → Vault/GitHub Reflection

**Purpose**: Detect every TaskHash-less task across ALL OmniFocus tasks (Inbox + every Project)
and route each one to the correct destination.

**Why scan all tasks, not just Inbox?**
- A user may add tasks directly to a native Project (Later, Someday, etc.) in OmniFocus without a TaskHash.
- Scanning only the Inbox misses those tasks — they would never reach the Vault.
- Scanning all tasks ensures complete bidirectional coverage.

**Detection**: Any OmniFocus task whose name does **not** contain a `(hash)` suffix.

**Process** (automated via `scan_omnifocus_inbox.py`):
1. Claude calls `mcp__omnifocus-local-server__dump_database`
2. Claude normalizes all incomplete tasks into `all_tasks_raw.json`:
   ```json
   {"tasks": [{"id": "OFTaskID", "name": "Task Name", "due_date": null, "parent_name": "Later"}]}
   ```
3. Claude runs `python3 scan_omnifocus_inbox.py --tasks all_tasks_raw.json`
   - Filters tasks without TaskHash
   - Generates TaskHash using `task_hash.py`
   - Routes each task based on parent Project (see routing rules below)
   - Updates sync_state.json
   - Outputs `inbox_rename_requests.json`
4. Claude reads `inbox_rename_requests.json` and calls `edit_item` for each task
   - **Appends TaskHash to OmniFocus task name** (mandatory for tracking)
5. Task is now tracked with `(hash)` in both OmniFocus AND Vault/GitHub

**Routing Rules**:
```
TaskHash-less Task (no hash in name):
├─ Has parent Project?
│  ├─ YES: Parent Project has TaskHash? (= GitHub Issue Project in sync_state)
│  │  ├─ YES → github_issue_child → Add to GitHub Issue body
│  │  └─ NO  → vault_task → Add to today's Vault Daily Note
│  └─ NO (true Inbox task) → vault_task → Add to today's Vault Daily Note
```

**Important Notes**:
- This is the REVERSE of Vault→OmniFocus flow
- Only untracked tasks (no hash) are processed; already-tracked tasks are skipped
- Due dates sync from OmniFocus to Vault (📅 emoji)
- Completion status updates via reverse_sync.py
- ✅ Fully automated as STEP 3 of the sync workflow

### 11.5. TaskHash-less OmniFocus Task Routing

**Scope**: Applies to ALL OmniFocus tasks — Inbox tasks AND tasks inside any Project.

**Classification logic** (implemented in `scan_omnifocus_inbox.py`):

1. **Scan ALL tasks** from `all_tasks_raw.json` (output of `dump_database`)
2. **Filter** for tasks without TaskHash in their name
3. **For each hashless task**, inspect `parent_name`:
   - Extract hash from `parent_name` using `extract_hash(parent_name)`
   - Look up hash in `sync_state.json`
   - If `task_type == "github_project"` → classify as `github_issue_child`
   - Otherwise (no hash in parent, or parent not in state) → classify as `vault_task`

**Routing details**:

| Classification | Condition | Action |
|----------------|-----------|--------|
| `github_issue_child` | Parent Project name contains a TaskHash that maps to `github_project` in sync_state | Add `- [ ] task_name (hash)` to GitHub Issue body |
| `vault_task` | Parent has no TaskHash, or parent has TaskHash but is NOT a github_project, or no parent | Add `- [ ] task_name (hash)` to today's Vault Daily Note |

**Example Scenario**:
```
OmniFocus All Tasks (TaskHash-less):
  • Implement OAuth flow (no hash, parent: "転職活動: フリーランスから正規雇用へ (60c6d084)")
  • Clean desk (no hash, parent: "Later")
  • Buy milk (no hash, no parent / Inbox)

Processing:
  Task A: "Implement OAuth flow"
    → parent_name = "転職活動: フリーランスから正規雇用へ (60c6d084)"
    → extract_hash → "60c6d084"
    → sync_state["60c6d084"].task_type = "github_project"  ← GitHub Issue Project
    → CLASSIFY: github_issue_child (Issue #2)
    → ACTION: Add to GitHub Issue #2: - [ ] Implement OAuth flow (hash)
    → Rename OmniFocus task: "Implement OAuth flow" → "Implement OAuth flow (hash)"

  Task B: "Clean desk"
    → parent_name = "Later"
    → extract_hash("Later") → None  ← no TaskHash in parent name
    → CLASSIFY: vault_task
    → ACTION: Add to today's Vault Daily Note: - [ ] Clean desk (hash)
    → Rename OmniFocus task: "Clean desk" → "Clean desk (hash)"

  Task C: "Buy milk"
    → no parent (Inbox task)
    → CLASSIFY: vault_task
    → ACTION: Add to today's Vault Daily Note: - [ ] Buy milk (hash)
    → Rename OmniFocus task: "Buy milk" → "Buy milk (hash)"
```

**Key Rules**:
1. **Scan all tasks** — Inbox-only scanning is insufficient; check every Project
2. **Never create orphaned TaskHash-less tasks** — All OmniFocus tasks must receive a TaskHash
3. **GitHub Issue takes priority** — If task is child of GitHub Issue Project, route to Issue before Vault
4. **Generate hash before commit** — Create TaskHash immediately when classifying
5. **Update OmniFocus task name** — Append hash via `edit_item` (essential for tracking)
6. **Idempotency** — Tasks already carrying a hash are skipped entirely

### 12. Manual Sync Trigger

**Design**: No automatic/scheduled sync. All sync is triggered manually by the user via the keyword **"sync tasks"**.

#### How It Works

When the user says **"sync tasks"** or equivalent command:

1. **Hook fires automatically** (`.claude/hooks/skill_sync.sh`):
   - Detects the sync keyword in the user's prompt
   - Runs `prepare_sync.py` to scan Vault + GitHub Issues for new tasks and existing Issue updates
   - Outputs results and instructs Claude to run the full workflow

2. **Claude executes all sync steps without waiting for confirmation**:

#### STEP 0.5 — Existing Issue Updates Detection
- Call: `detect_existing_issue_updates()` in `prepare_sync.py`
- **Detects changes in already-synced GitHub Issues**:
  - Finds all `github_project` entries in `sync_state.json`
  - For each Issue, fetches current content from GitHub API
  - Compares current tasks with synced state:
    - **New tasks** without TaskHash detected
    - **Deleted tasks** removed from Issue
    - **Completion state changes** ([x] marked in GitHub but open in sync_state)
- Generates `existing_issue_updates.json` with:
  - `completion_changes`: Tasks that changed from open → completed in GitHub
  - `new_tasks`: Tasks added to Issue without hashes (requires hash generation + OmniFocus creation)
  - `deleted_tasks`: Tasks removed from Issue
- **Output**: `existing_issue_updates.json` ready for Claude to process

**Why this matters**: Ensures GitHub Issue updates (new comments, task completions) are reflected in OmniFocus without requiring full Issue re-sync. Previously, existing Issues were skipped entirely.

#### STEP 1 — Forward Sync (Vault/GitHub → OmniFocus)
- Read `tasks_to_sync.json` (output of `prepare_sync.py`)
- If new tasks exist: run `python3 sync_to_omnifocus.py`
  - This outputs `precheck_requests.json` — a list of existence checks Claude MUST perform
- **PRE-EXISTENCE CHECK (mandatory, prevents duplicates)**:
  - Read `precheck_requests.json`
  - For **each item** in `checks[]`: call `mcp__omnifocus-local-server__get_task_by_id` with `taskName`
  - **If found** in OmniFocus → record the existing `id` in `sync_state.json`, remove item from the batch
  - **If absent** → keep item in the batch
- Call `mcp__omnifocus-local-server__batch_add_items` with the **filtered** batch (absent items only)
- Update `sync_state.json` with new OmniFocus IDs

#### STEP 2 — Reverse Sync (OmniFocus → Vault/GitHub)
- Call MCP: `mcp__omnifocus-local-server__filter_tasks` with `completedToday=true`
- Save result as **`completed_tasks_raw.json`** in the format:
  ```json
  {"completed_tasks": ["Task Name (hash)", "Another Task (hash)"]}
  ```
  *(plain list `[...]` is also accepted)*
- Run `python3 reverse_sync.py --completed-tasks completed_tasks_raw.json`
- Reflects completed tasks back to Vault checkboxes and GitHub Issue checkboxes

#### STEP 3 — All-Tasks Scan (OmniFocus All Tasks → Vault Daily Note / GitHub)
- Call MCP: `mcp__omnifocus-local-server__dump_database`
- Extract ALL incomplete tasks (Inbox + every Project) and normalize into **`all_tasks_raw.json`**:
  ```json
  {"tasks": [{"id": "OFTaskID", "name": "Task Name", "due_date": null, "parent_name": "ProjectName"}]}
  ```
  Include `parent_name` = the containing Project's name (omit or `null` for true Inbox tasks)
- Run `python3 scan_omnifocus_inbox.py --tasks all_tasks_raw.json`
- Routing rules applied by the script:
  - Task has **no TaskHash** AND parent Project **has no TaskHash** (or no parent) → add to today's Vault Daily Note
  - Task has **no TaskHash** AND parent Project **has a TaskHash** (= GitHub Issue Project) → add to GitHub Issue body
- For each new task, call MCP: `mcp__omnifocus-local-server__edit_item` to append TaskHash to OmniFocus task name

**Example**:
```
User: "sync tasks"
Claude:
  [Hook runs prepare_sync.py automatically]
  STEP 1: tasks_to_sync.json → OmniFocus (new tasks pushed)
  STEP 2: OmniFocus completed → Vault/GitHub (checkboxes updated)
  STEP 3: OmniFocus all tasks scanned → Vault Daily Note / GitHub (new hashless tasks routed)
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

All metadata is removed before hash calculation to ensure consistency.
The **single source of truth** is `clean_task_name_for_hash()` in `task_hash.py`:

```python
def clean_task_name_for_hash(task_name: str) -> str:
    """Remove ALL metadata — call this before computing any TaskHash."""
    cleaned = clean_markdown_links(task_name)           # [text](url) → text
    cleaned = re.sub(r'\s+📅\s+\d{4}-\d{2}-\d{2}', '', cleaned)   # 📅 removed
    cleaned = re.sub(r'\s+\[due::\s*\d{4}-\d{2}-\d{2}\]', '', cleaned)  # [due::] removed
    cleaned = remove_hash(cleaned)                      # (XXXXXXXX) removed
    return cleaned.strip()
```

Cleaning steps applied in order:
1. **Markdown links**: `[text](url)` → `text`; URL extracted to OmniFocus note field
2. **Due date (emoji)**: `📅 YYYY-MM-DD` → removed
3. **Due date (bracket)**: `[due:: YYYY-MM-DD]` → removed
4. **Existing hash**: ` (XXXXXXXX)` → removed

**Example**:
```
Input:  "[Buy Groceries](https://store.com) 📅 2026-05-15 (a1b2c3d4)"
Output: "Buy Groceries"
Hash:   compute_hash("vault:path.md:Buy Groceries")
OmniFocus:  Name: Buy Groceries (hash)
            Note: https://store.com
            Due:  2026-05-15
```

**Write-back behaviour** (`update_vault_files_with_hashes` in `prepare_sync.py`):
When appending a hash to a vault line, the function searches for the task's **display text**.
Because vault lines may use either `plain text` or `[text](url)` Markdown link syntax, the
regex pattern matches both forms:
```
(- \[ \] (?:\[)?{display_text}(?:\]\([^\)\n]+\))?) ...
```
The `[text](url)` wrapper is preserved intact in the output. Without this, tasks written with
Markdown link syntax would never have their hash appended to the vault file.

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
├── sync_to_omnifocus.py         # Forward sync: resolves hashes, outputs precheck + batch (STEP 1)
├── reverse_sync.py              # Reverse sync: reflects completions to GitHub/Vault (STEP 2)
├── scan_omnifocus_inbox.py      # All-tasks scan: routes hashless tasks → Vault/GitHub (STEP 3)
├── sync_state.json              # Sync state tracking (primary key: TaskHash)
├── tasks_to_sync.json           # Prepared tasks waiting for sync (output of prepare_sync.py)
├── precheck_requests.json       # Pre-existence checks Claude MUST run before batch_add_items
├── completed_tasks_raw.json     # Input to reverse_sync.py (Claude writes)
├── all_tasks_raw.json           # Input to scan_omnifocus_inbox.py (Claude writes from dump_database)
└── inbox_rename_requests.json   # Output of scan_omnifocus_inbox.py (Claude reads + executes)
```

**Documentation**:
- [[x/Scripts/TaskHashSyncSystem/README.md]] - Main specification document

**Removed Files** (May 4, 2026):
- ~~run_complete_sync.py~~ — Redundant orchestrator (Claude handles 3-step execution)
- ~~update_sync_state.py~~ — State updates now integrated into sync_to_omnifocus.py and reverse_sync.py

**Removed Files** (May 5, 2026):
- ~~scan_missing_taskhashes.py~~ — Diagnostic scanner; `prepare_sync.py` covers the same detection
- ~~test_system.py~~ — Obsolete test script
- ~~completed_today.json~~ — Temp file (cleaned up)
- ~~completed_today_sync.json~~ — Temp file (cleaned up)
- ~~completed_today_with_projects.json~~ — Temp file (cleaned up)
- ~~inbox_tasks_to_sync.json~~ — Temp file (cleaned up)
- ~~test_completed.json~~ — Temp file (cleaned up)
- ~~completed_tasks.json~~ — Temp file (cleaned up)
- ~~completed_tasks_from_omnifocus.json~~ — Temp file (cleaned up)
- ~~mcp_batch_add_request.json~~ — Temp file (cleaned up)
- ~~new_tasks_hashes.json~~ — Temp file (cleaned up)
- ~~scan_omnifocus_report.json~~ — Temp file (cleaned up)
- ~~tasks_resolved.json~~ — Temp file (cleaned up)

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
13. **OmniFocus native Project container exclusion**: Every OmniFocus Project has an identically-named first child task acting as a container (e.g., project "あとでやる - Later" has child "あとでやる - Later"). These containers MUST NEVER receive a TaskHash and MUST NEVER be added to the Vault Daily Note. Detection rule: `remove_hash(task_name).strip() == remove_hash(parent_name).strip()` → skip entirely in `scan_omnifocus_inbox.py`.

## Current Implementation Status

### ✅ Completed (v2.5 - May 5, 2026)
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
- **TaskHash-less task automatic routing** ✨ (FULLY IMPLEMENTED)
  - ✅ Automatic detection of orphaned TaskHash-less tasks
  - ✅ GitHub Issue routing (tested & verified)
  - ✅ TaskHashless Project routing to Vault (implemented in scan_omnifocus_inbox.py)
  - ✅ Full bidirectional routing (complete)

#x/claude
