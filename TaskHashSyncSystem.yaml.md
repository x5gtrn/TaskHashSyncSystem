---
title: TaskHashSyncSystem 設計仕様書
type: specification
format: yaml
version: v3.0
updated: 2026-07-14
tags:
  - x/claude
  - task-sync
  - specification
related:
  - "[[x/Scripts/TaskHashSyncSystem/README.md]]"
---

# TaskHashSyncSystem 設計仕様書（YAML 形式）

> OmniFocus ↔ GitHub Issues ↔ Obsidian Vault を結ぶ双方向タスク同期システムの全仕様。
> 本文書は人間・機械の双方が参照可能な単一の設計書として、YAML 形式で全体像を記述する。

```yaml
# =============================================================================
# TaskHashSyncSystem — 完全設計仕様書
# =============================================================================
meta:
  name: TaskHashSyncSystem
  purpose: >-
    OmniFocus・GitHub Issues・Obsidian Vault の3システム間で
    タスクを双方向同期する。各タスクは不変の TaskHash によって
    一意に識別され、内容が変わっても追跡が維持される。
  version: v3.0
  last_updated: "2026-07-14"
  language: python3
  location: x/Scripts/TaskHashSyncSystem/
  documentation:
    - README.md                   # 完全仕様書（本体）
    - TaskHashSyncSystem.yaml.md  # 本設計書
  design_philosophy:
    - "State Integrity First: 全操作の前に sync_state.json をクリーンにする"
    - "DELETE → INSERT → UPDATE → SELECT のDB操作順を厳守"
    - "TaskHash は不変（immutable）— 一度生成したら二度と変わらない"
    - "冪等性（idempotency）— 何度実行しても安全"
    - "ドメイン分離 — Project は GitHub、Inbox は Vault で管理"
    - "孤児タスクを作らない — 全 OmniFocus タスクは TaskHash と出自を持つ"

# -----------------------------------------------------------------------------
# 1. 中核概念: TaskHash（不変タスク識別子）
# -----------------------------------------------------------------------------
task_hash:
  definition: >-
    タスクごとに一度だけ生成される CRC32 ハッシュ。
    タスク名・期日・内容が変更されても不変。
  algorithm:
    method: CRC32
    payload_format: "task {size}\\0{source_id}"  # Git object header に着想
    computation: "format(zlib.crc32(payload) & 0xFFFFFFFF, '08x')"
    output_format: "8桁の小文字16進数（例: 73801d05）"
  properties:
    immutability: "生成後は不変。タスク名が変わってもハッシュは変わらない"
    uniqueness: "同一 source_id は常に同一ハッシュを生成（冪等）"
    role: "全システムを貫くタスク同一性の唯一の真実（source of truth）"
  source_id:
    description: "ハッシュ生成の元となる一意識別文字列"
    formats:
      github_issue:    "github:owner/repo#issue_num:task_name"
      github_comment:  "github:owner/repo#issue_num:comment#N:task_name"
      vault:           "vault:relative/path/to/file.md:task_name"
    examples:
      - "github:x5gtrn/LIFE#1:MoneyWizを完璧にする  → 73801d05"
      - "github:x5gtrn/LIFE#5:WoWJapanizerX          → c3a827fc"
      - "vault:Calendar/Daily/2026/05/2026-05-01.md:Buy coffee"
  helper_functions:  # task_hash.py が提供
    compute_hash:             "source_id → 8桁ハッシュ"
    make_github_source_id:    "(owner, repo, issue_num, task_name) → source_id"
    make_vault_source_id:     "(relative_path, task_name) → source_id"
    append_hash:              "タスク名にハッシュ付与（既存なら何もしない）"
    has_hash:                 "ハッシュ有無を判定 — 正規表現 ' ?\\([0-9a-f]{8}\\)$'"
    extract_hash:             "タスク名からハッシュ抽出（無ければ None）"
    remove_hash:              "タスク名からハッシュ接尾辞を除去"
    clean_task_name_for_hash: "ハッシュ計算前に全メタデータを除去（唯一の正規化関数）"

# -----------------------------------------------------------------------------
# 2. タスク名の正規化（ハッシュ計算前のクリーニング）
# -----------------------------------------------------------------------------
task_name_cleaning:
  function: clean_task_name_for_hash
  source_of_truth: task_hash.py
  rationale: "メタデータを除去してから計算することでハッシュの安定性を保証"
  cleaning_order:
    1_markdown_links:   "[text](url) → text（URL は OmniFocus の note 欄へ抽出）"
    2_due_date_emoji:   "📅 YYYY-MM-DD → 除去"
    3_due_date_bracket: "[due:: YYYY-MM-DD] → 除去"
    4_existing_hash:    " (XXXXXXXX) → 除去"
  example:
    input:  "[Buy Groceries](https://store.com) 📅 2026-05-15 (a1b2c3d4)"
    cleaned: "Buy Groceries"
    hash_basis: "compute_hash('vault:path.md:Buy Groceries')"
    omnifocus_result:
      name: "Buy Groceries (hash)"
      note: "https://store.com"
      due:  "2026-05-15"

# -----------------------------------------------------------------------------
# 3. ドメイン分離（3つの同期領域）
# -----------------------------------------------------------------------------
domains:
  - id: github_projects
    name: "GitHub Issues ↔ OmniFocus Projects"
    mapping: "GitHub Issue のタイトル = OmniFocus の Project"
    rules:
      - "Issue タイトル自体が TaskHash 付き Project になる"
      - "Issue body のタスク + コメントのタスク = Project の子タスク"
      - "コメントは '- [ ] タスク' 形式のみ処理（それ以外はメタデータ生成しない）"
      - "Vault には同期しない（GitHub でのみ管理）"
      - "全タスクはチェックボックス形式: '- [ ] Task name (hash)'"

  - id: vault_inbox
    name: "Vault Daily Notes ↔ OmniFocus Inbox"
    mapping: "Calendar/ フォルダの Daily Note = OmniFocus Inbox タスク"
    rules:
      - "Calendar/ フォルダのみ同期対象（Atlas/・Efforts/・x/ は除外）"
      - "Inbox タスクのみを含む"
      - "'## Tasks' セクションに日付別で通常タスクを記述"
      - "'## Projects' セクションにプロジェクトコンテナ名を記述（タスクではない）"

  - id: taskhashless_projects
    name: "TaskHash を持たない OmniFocus ネイティブ Project（Later, Someday 等）"
    mapping: "Project 名はタスクとして同期しない（メタデータのみ）"
    rules:
      - "Project コンテナ名（Later 等）はタスクとして同期されない"
      - "Project 名は Vault の '## Projects' セクションに列挙"
      - "Project の子タスクのみが Vault Inbox タスクとして同期される"
      - "GitHub Issue 由来 Project との混同を防ぐ"

# -----------------------------------------------------------------------------
# 4. sync_state.json（状態管理）
# -----------------------------------------------------------------------------
sync_state:
  file: sync_state.json
  primary_key: TaskHash
  guarantees:
    - "TaskHash が一意性を保証する主キー"
    - "source_id は出自の全情報を保持（OmniFocus の note には出さない）"
    - "冪等性 — 既存ハッシュはスキップ"
  schema:
    task_hash_value:
      source_id:        "出自識別子（例: vault:Calendar/.../2026-05-01.md:task）"
      of_task_id:       "OmniFocus タスクID または 'pending'"
      of_task_name:     "OmniFocus 上のタスク名（hash付き）"
      status:           "open | completed | dropped"
      task_type:        "vault_task | github_task | github_comment_task | github_project | project"
      parent_task_hash: "親タスクのハッシュ（階層がある場合）"
      due_date:         "YYYY-MM-DD（該当時）"
      synced_at:        "ISO8601 タイムスタンプ"
      completed_at:     "ISO8601 タイムスタンプ（完了時）"
  example_entry:
    "73801d05":
      source_id: "github:x5gtrn/LIFE#1:MoneyWizを完璧にする"
      of_task_id: "nOI1DB5LSHs"
      of_task_name: "MoneyWizを完璧にする (73801d05)"
      status: open
      task_type: github_project
      synced_at: "2026-06-08T00:20:00.000000"

# -----------------------------------------------------------------------------
# 5. 親子階層（parentTaskHash）
# -----------------------------------------------------------------------------
hierarchy:
  key_field: parent_task_hash
  rationale: >-
    親参照に名前ではなくハッシュを使う。名前は変わりうるがハッシュは不変なので、
    親名が変わっても関係が保たれる。構造を内容から切り離す。
  vault_detection:
    method: "タブ/スペースのインデントで階層を検出"
    levels: "Level 0（親）→ Level 1（子）→ Level 2（孫）… 任意の深さ"
    parser: "prepare_sync.py が親スタックを維持しながら解析"
  example:
    vault: |
      ## Tasks
      - [ ] Complete Q4 Planning (h4d9f782)        [Level 0]
      	- [ ] Review market research (i7c2a401)     [Level 1, parent: h4d9f782]
      	- [ ] Define roadmap (j5f8b634)             [Level 1, parent: h4d9f782]
      		- [ ] Prioritize bugs (k9e3c171)         [Level 2, parent: j5f8b634]
    omnifocus: |
      INBOX:
        • Complete Q4 Planning (h4d9f782)
           • Review market research (i7c2a401)
           • Define roadmap (j5f8b634)
              • Prioritize bugs (k9e3c171)

# -----------------------------------------------------------------------------
# 6. Project 完了ポリシー（重要ルール）
# -----------------------------------------------------------------------------
project_completion_policy:
  critical_rule: "子タスクの完了は Project 完了をトリガーしない"
  project_completes_only_when:
    - "ユーザーが OmniFocus で明示的に Project を完了にした時"
    - "GitHub Issue がクローズされた時（逆同期で反映）"
  rationale:
    - "増分作業をサポート — 完了後も新タスクが頻繁に追加される"
    - "関心の分離 — タスク完了（末端）≠ Project 完了（コンテナ状態）"
    - "プロジェクト文脈の保持 — 完了状態はユーザー制御下に置く"
  implementation:
    - "sync_state.json で Project エントリは子状態と独立に status を保持"
    - "reverse_sync.py は子完了に基づいて Project status を更新しない"

# -----------------------------------------------------------------------------
# 7. 順方向同期（GitHub/Vault → OmniFocus）
# -----------------------------------------------------------------------------
forward_sync:
  data_preparation:
    script: prepare_sync.py
    steps:
      - "GitHub Issues をスキャン（body + 全コメント、チェックボックスタスクのみ）"
      - "Vault の Calendar/ フォルダのみをスキャン"
      - "未チェックタスク '- [ ] Task' を抽出"
      - "各タスクの TaskHash を生成"
      - "インデントで親子関係を検出"
      - "TaskHash を Vault Daily Note に書き戻す（STEP 2.5, 冪等）"
      - "tasks_to_sync.json を出力"
      - "sync_state.json を参照して同期済みタスクをスキップ"
  omnifocus_addition:
    scripts:
      - sync_to_omnifocus.py
      - sync_to_omnifocus_v2.py  # v3.0: MCP 実行 + 実IDキャプチャ
    mcp_tools:
      - mcp__omnifocus__add_omnifocus_task
      - mcp__omnifocus__batch_add_items
    steps:
      - "parentTaskHash → parentTaskId を sync_state.json で解決"
      - "batch_add_items で追加、親を parentTaskId で設定"
      - "sync_state.json を OmniFocus タスクIDで更新（pending → 実ID）"
  routing_rule:
    - "GitHub Project タスク → OmniFocus Projects（Vault はスキップ）"
    - "Vault Inbox タスク → OmniFocus Inbox（階層維持）"
  deduplication:
    description: "prepare_sync.py は再計算前に既存ハッシュを除去し衝突を防ぐ"
    steps:
      - "remove_hash() で ' (XXXXXXXX)' 接尾辞を除去"
      - "常にクリーンな名前でハッシュ計算 → 冪等な再実行"

# -----------------------------------------------------------------------------
# 8. 逆方向同期（OmniFocus → GitHub/Vault）
# -----------------------------------------------------------------------------
reverse_sync:
  script: reverse_sync.py
  completion_reflection:
    steps:
      - "MCP filter_tasks(completedToday=true) で完了タスク取得"
      - "TaskHash で出自を照合"
      - "GitHub Issue / Vault のチェックボックスを更新"
      - "期日を同期（OmniFocus が真実）"
      - "Vault タスクに完了日を追加"
      - "sync_state.json に完了タイムスタンプ記録"
  project_task_routing:
    github_issue_project:
      - "GitHub Issue のチェックボックスへ子タスク完了を反映"
      - "⚠️ Project 完了は逆同期に反映しない（Project 完了ポリシー参照）"
    taskhashless_project:
      - "Project コンテナ名はタスクとして同期しない（メタデータのみ）"
      - "子タスクのみ Vault Inbox タスクとして同期"
      - "期日変更/削除も反映"
  completion_date_format:
    pattern: "- [x] Task (hash) 📅 due 2026-05-03 ✅ 2026-05-01"
    rule: "✅ YYYY-MM-DD を末尾に。既存完了日は上書きしない（冪等）"
    ordering: "期日（📅）→ 完了日（✅）の順"

# -----------------------------------------------------------------------------
# 9. GitHub Issue → Project 変換
# -----------------------------------------------------------------------------
github_issue_conversion:
  trigger: "TaskHash を持たない Issue を検出したら即時・自動処理（必須）"
  workflow:
    1_issue_title_hash:
      - "source_id 生成: github:owner/repo#issue_num:Title"
      - "task_hash.py でハッシュ計算"
      - "Issue タイトルを更新: 'Title (hash)'"
    2_body_task_hash:
      - "全タスクをチェックボックス化: '- [ ] Task'"
      - "各タスクの source_id 生成 → ハッシュ計算 → 付与"
      - "Issue body を更新"
    3_omnifocus:
      - "batch_add_items で Project 作成 + 子タスク追加"
      - "Project note に Issue URL 追加"
    4_state:
      - "Issue タイトルを github_project として記録"
      - "body タスクを github_task として記録（parent_task_hash 付き）"
      - "status: open を設定"
  example:
    before:
      title: "Setup Financial Accounts"
      body: |
        - [x] Connect Revolut Account
        - [ ] Add Credit Card Details
    after:
      title: "Setup Financial Accounts (a7f3c942)"
      body: |
        - [x] Connect Revolut Account (b2d8e641)
        - [ ] Add Credit Card Details (c5e1a392)

# -----------------------------------------------------------------------------
# 10. OmniFocus 全タスクスキャン（Inbox + 全Project → Vault/GitHub）
# -----------------------------------------------------------------------------
all_tasks_scan:
  script: scan_omnifocus_inbox.py  # v3: scan_omnifocus_inbox_v3.py
  purpose: "全 OmniFocus タスクから TaskHash 無しを検出し正しい宛先へ振り分け"
  why_all_tasks: >-
    ユーザーが Inbox 以外（ネイティブ Project）に直接タスクを追加する場合があるため、
    Inbox だけでなく全タスクをスキャンして完全な双方向カバレッジを確保する。
  detection: "名前に (hash) 接尾辞を持たない全タスク"
  process:
    - "MCP dump_database を呼ぶ"
    - "生テキストを omnifocus_dump.txt に保存（単一 Write）"
    - "scan_omnifocus_inbox.py --dump-file omnifocus_dump.txt を実行"
    - "parse_omnifocus_dump.py が text → all_tasks_raw.json へ自動変換"
    - "TaskHash 無しをフィルタ → ハッシュ生成 → 振り分け"
    - "sync_state.json 更新、Vault Daily Note 書き込み"
    - "JXA で OmniFocus タスク名を自動リネーム"
  routing_rules:
    has_parent_project:
      parent_has_taskhash:  # sync_state で github_project
        result: github_issue_child
        action: "GitHub Issue body に '- [ ] task (hash)' を追加"
      parent_no_taskhash:
        result: vault_task
        action: "task の added_date の Daily Note に追加（fallback: today）"
    no_parent:  # 真の Inbox タスク
      result: vault_task
      action: "added_date の Daily Note に追加（fallback: today）"
  key_rules:
    - "全タスクをスキャン（Inbox のみでは不十分）"
    - "孤児 TaskHash 無しタスクを作らない"
    - "GitHub Issue が優先 — Issue Project 子なら Vault より先に Issue へ"
    - "分類時に即ハッシュ生成"
    - "OmniFocus タスク名を JXA で自動更新（fallback のみ手動 edit_item）"
    - "既にハッシュ付きのタスクは完全にスキップ（冪等）"

# -----------------------------------------------------------------------------
# 11. OmniFocus ネイティブ Project コンテナの除外
# -----------------------------------------------------------------------------
container_exclusion:
  problem: >-
    全 OmniFocus Project は同名の最初の子タスク（コンテナ）を持つ。
    例: Project "Later" は "Later" という子タスクを持つ。
  rule:
    - "コンテナは TaskHash を受け取らない"
    - "コンテナは Vault Daily Note に追加しない"
  detection: "remove_hash(task_name).strip() == remove_hash(parent_name).strip() → 完全スキップ"

# -----------------------------------------------------------------------------
# 12. 重複 TaskHash 防止（PLAN B + C, v2.6）
# -----------------------------------------------------------------------------
duplicate_prevention:
  incident:
    date: "2026-05-28"
    symptom: "'Do Something (25c093b3)' が Inbox と Project に同時出現"
    root_cause: >-
      Vault から Inbox に同期後、同じタスクをネイティブ Project の子として追加。
      旧ロジックが既ハッシュ持ちタスクをフィルタしなかった。
  phase_1_skip_logic:  # detect_new_tasks()
    - "名前にTaskHashを含むか正規表現でチェック: ' ?\\([0-9a-f]{8}\\)$'"
    - "抽出ハッシュが sync_state に存在するか（重複排除）"
    - "コンテナタスクをスキップ（name == parent_name）"
    - "GitHub Project 子をスキップ"
    - "追跡済みbase名をスキップ"
  phase_2_validation:  # validate_no_duplicate_hashes()
    - "全 OmniFocus タスクを重複ハッシュ検査"
    - "発見時は同期を停止し手動クリーンアップを強制"
  phase_3_parent_check:  # detect_parent_mismatch()
    - "タスクの親が sync_state 記録と一致しないと警告"
  recovery_protocol:
    - "ユーザーが不要な重複を OmniFocus から手動削除"
    - "次回同期で重複検査がPASS"
    - "sync_state.json は次回実行で自動修正"

# -----------------------------------------------------------------------------
# 13. GitHub Issue ステータス逆転バグ修正（v2.7）
# -----------------------------------------------------------------------------
status_desync_fix:
  version: v2.7
  date: "2026-05-30"
  problem: "GitHub で [ ] 未チェックだが OmniFocus では [x] 完了のまま"
  root_cause: >-
    reverse_sync.py が OmniFocus→GitHub 完了のみ処理し、
    GitHub→OmniFocus のステータス逆転（GitHubで再度未チェック）を無視していた。
  fix:
    - "reverse_sync.py に --existing-issue-updates パラメータ追加"
    - "process_existing_issue_updates() で completion_changes を処理"
    - "update_omnifocus_task_status() で JXA 経由に OmniFocus 更新"
    - "STEP 2 を 2.1（完了反映）と 2.2（ステータス変更）に分割"
  result: "sync_state.json と GitHub Issue が真実。OmniFocus が自動追従"

# -----------------------------------------------------------------------------
# 14. OmniFocus 削除カスケード（v2.8, PRE-STEP）
# -----------------------------------------------------------------------------
deletion_cascade:
  version: v2.8
  date: "2026-05-30"
  script: detect_deleted_omnifocus_tasks.py
  execution_position: "最初（PRE-STEP）— STEP 1 の前"
  problem: "ユーザーが OmniFocus からタスクを手動削除すると GitHub/Vault に孤児が残る"
  process:
    - "omnifocus_dump.txt を解析"
    - "sync_state.json にあるが dump に無いタスクを検出"
    - "各削除タスクを GitHub Issue から削除（update_issue_body.py --remove-task）"
    - "Vault Daily Note から削除（正規表現行削除）"
    - "sync_state.json からエントリ削除"
  why_pre_step:
    - "順方向操作の前に状態をクリーンにする"
    - "ハッシュ衝突リスク回避（旧/新の混在なし）"
    - "エラー処理の単純化（削除は独立）"
    - "DB ベストプラクティス: DELETE before INSERT"
  safety:
    - "--dry-run で削除プレビュー"
    - "--verbose で詳細ログ"
    - "update_issue_body.py 使用（安全なアトミック操作）"

# -----------------------------------------------------------------------------
# 15. 手動同期トリガー "sync tasks" と実行順序
# -----------------------------------------------------------------------------
manual_sync:
  design: "自動/スケジュール同期なし。ユーザーの 'sync tasks' で手動起動"
  hook:
    file: .claude/hooks/skill_sync.sh
    config: .claude/settings.json
    trigger_patterns: ["sync tasks", "skill sync", "手動リクエスト"]
    action: "prepare_sync.py を実行し Claude に全ワークフロー実行を指示"
  execution_order:
    pre_sync:
      name: "GitHub Issue 自動処理"
      desc: "TaskHash 無し Issue を検出 → ハッシュ生成 → 更新 → Project作成 → state記録"
    pre_step:
      name: "削除タスク検出 & カスケード削除"
      script: detect_deleted_omnifocus_tasks.py
      input: omnifocus_dump.txt
      result: "sync_state.json をクリーンに"
    step_0_5:
      name: "既存 Issue 更新検出"
      function: "detect_existing_issue_updates() in prepare_sync.py"
      output: existing_issue_updates.json
      detects: [completion_changes, new_tasks, deleted_tasks]
    step_1:
      name: "順方向同期（Vault/GitHub → OmniFocus）"
      steps:
        - "tasks_to_sync.json を読む"
        - "sync_to_omnifocus.py 実行 → precheck_requests.json 出力"
        - "各チェック項目を get_task_by_id で存在確認（重複防止・必須）"
        - "存在すれば id を state に記録しバッチから除外、無ければ残す"
        - "batch_add_items をフィルタ済みバッチで呼ぶ"
        - "sync_state.json を新IDで更新"
    step_2_1:
      name: "OmniFocus 完了を GitHub/Vault へ反映"
      input: completed_tasks_raw.json  # filter_tasks(completedToday=true)
      command: "python3 reverse_sync.py --completed-tasks completed_tasks_raw.json"
    step_2_2:
      name: "GitHub Issue ステータス変更を OmniFocus へ同期"
      input: existing_issue_updates.json
      command: "python3 reverse_sync.py --existing-issue-updates existing_issue_updates.json"
    step_3:
      name: "全タスクスキャン（OmniFocus → Vault/GitHub）"
      steps:
        - "dump_database を呼び omnifocus_dump.txt に保存"
        - "scan_omnifocus_inbox.py --dump-file omnifocus_dump.txt 実行"
        - "TaskHash 無しを振り分け（親無ハッシュ→Vault、親ハッシュ有→GitHub）"
  atomic_order: "DELETE → INSERT → UPDATE → SELECT"

# -----------------------------------------------------------------------------
# 16. GitHub Issue body 編集の絶対ルール
# -----------------------------------------------------------------------------
github_body_editing:
  forbidden:
    rule: "Claude は 'gh issue edit --body \"...\"' で手動組み立て body を渡してはならない"
    reason: >-
      手動組み立ては Issue body 全体を文脈に保持して再構築する必要があり、
      他 Issue のタスクが混入するエラーを招く。
  required:
    tool: update_issue_body.py
    reason: "GitHub から現在の body を取得し指定した diff のみ適用。他行は不変"
    operations:
      "--add-task 'Task (hash)'":      "新規トップレベルタスクを追加"
      "--add-child 'Parent' 'Child'":  "親とその既存子の後に子を挿入"
      "--remove-task 'hash'":          "(hash) を含む行を削除"
      "--check-task 'hash'":           "[ ] → [x]"
      "--uncheck-task 'hash'":         "[x] → [ ]"
      "--dry-run":                     "書き込まずに diff プレビュー"
    best_practice: "複数変更時は必ず --dry-run で先に検証"

# -----------------------------------------------------------------------------
# 17. URL・Markdown リンク処理
# -----------------------------------------------------------------------------
url_handling:
  markdown_links:
    detection: "[text](url) 形式"
    action: "URL を OmniFocus note 欄へ抽出、タスク名は display text のみに"
  due_dates:
    emoji_format: "📅 YYYY-MM-DD（ハッシュ計算前に除去）"
    source_of_truth: "OmniFocus が期日の真実。双方向同期"
  example:
    input:  "- [ ] [Buy Groceries](https://grocerystore.com) 📅 2026-05-15"
    clean:  "Buy Groceries"
    omnifocus:
      name: "Buy Groceries (hash)"
      note: "https://grocerystore.com"

# -----------------------------------------------------------------------------
# 18. MCP 統合
# -----------------------------------------------------------------------------
mcp_integration:
  server: omnifocus-local-server
  tools:
    add_omnifocus_task: "親参照付きで単一タスク追加"
    batch_add_items:    "タスク/プロジェクトを一括追加"
    edit_item:          "タスクのリネーム/変更（TaskHash 更新用）"
    filter_tasks:       "逆同期用に完了タスクをクエリ"
    get_task_by_id:     "名前/IDでタスク詳細取得"
    dump_database:      "検証用に全DB構造取得"

# -----------------------------------------------------------------------------
# 19. ファイル構成
# -----------------------------------------------------------------------------
files:
  runtime_scripts:
    task_hash.py:                      "TaskHash 生成 + ユーティリティ（全スクリプトが使用）"
    prepare_sync.py:                   "データ準備 + GitHub Issue 自動処理（STEP 0）"
    sync_to_omnifocus.py:              "順方向同期: ハッシュ解決 + precheck/batch 出力（STEP 1）"
    reverse_sync.py:                   "逆同期: 完了を GitHub/Vault へ反映（STEP 2）"
    scan_omnifocus_inbox.py:           "全タスクスキャン: ハッシュ無し → Vault/GitHub（STEP 3）"
    detect_deleted_omnifocus_tasks.py: "削除検出 & カスケード削除（PRE-STEP）"
    update_issue_body.py:              "⚠️ 全 GitHub Issue body 編集に必須"
    parse_omnifocus_dump.py:           "dump text → all_tasks_raw.json 変換"
  v3_scripts:
    detect_phantom_tasks.py:       "PHASE1: OmniFocus に存在しない pending タスク除去"
    emergency_hash_inbox_tasks.py: "PHASE1: 未ハッシュ Inbox タスク自動ハッシュ化"
    omnifocus_mcp.py:              "PHASE2: 統一 MCP ラッパー"
    sync_to_omnifocus_v2.py:       "PHASE2: batch_add_items 実行 + 実IDキャプチャ"
    scan_omnifocus_inbox_v3.py:    "PHASE3: トランザクション的エラー処理付き再設計スキャン"
    validate_sync_consistency.py:  "PHASE3: 乖離検出（phantom/orphan/duplicate）+ --fix 自動修正"
    run_full_sync.py:              "PHASE4: 全フェーズ統括メインエントリ"
  state_and_data:
    sync_state.json:             "同期状態追跡（主キー: TaskHash）"
    tasks_to_sync.json:          "同期待ちの準備済みタスク（prepare_sync.py 出力）"
    precheck_requests.json:      "batch_add_items 前の存在チェック一覧"
    completed_tasks_raw.json:    "reverse_sync.py への入力"
    omnifocus_dump.txt:          "dump_database の生テキスト"
    all_tasks_raw.json:          "scan_omnifocus_inbox.py が自動生成（手動編集禁止）"
    inbox_rename_requests.json:  "scan の出力（監査ログ、リネームは自動適用）"
    existing_issue_updates.json: "既存 Issue 更新の検出結果"
    repositories.json:           "対象 GitHub リポジトリ設定"

# -----------------------------------------------------------------------------
# 20. 設計原則（不変の指針）
# -----------------------------------------------------------------------------
design_principles:
  1:  "TaskHash は不変 — 初回生成後は決して変わらない"
  2:  "ParentTaskHash が正典 — 階層は名前ではなくハッシュに依存"
  3:  "source_id は sync_state のみ — OmniFocus note には出さない"
  4:  "URL は note のみ — Markdown リンクから抽出、タスク名には含めない"
  5:  "ハッシュ前にメタデータ除去 — 期日・URL・絵文字を除外"
  6:  "ドメイン分離 — Project は GitHub、Inbox は Vault"
  7:  "冪等操作 — 何度実行しても安全"
  8:  "Project 名除外 — TaskHashless Project コンテナ名はタスクとして同期しない"
  9:  "Vault の日付順序 — 期日（📅）→ 完了日（✅）"
  10: "堅牢なパターンマッチ — インデント・末尾空白・複数行タスクに対応"
  11: "TaskHash 無しタスクの自動振り分け — 親関係に基づく分類"
  12: "孤児タスクなし — 全 OmniFocus タスクは TaskHash と出自を持つ"
  13: "ネイティブ Project コンテナ除外 — name == parent_name はスキップ"
  14: "added_date が Daily Note の宛先を決める — today ではなく作成日"
  15: "重複 TaskHash 防止 — 複数箇所に同一ハッシュを許さない（PLAN B+C）"

# -----------------------------------------------------------------------------
# 21. ユーザー運用ガイドライン
# -----------------------------------------------------------------------------
user_guidelines:
  correct_task_creation:
    - location: "Vault Daily Notes (Calendar/Daily/YYYY/MM/YYYY-MM-DD.md)"
      note: "OmniFocus Inbox へ自動同期、TaskHash 自動生成"
    - location: "GitHub Issues"
      note: "タイトル + チェックボックスタスク、TaskHash 自動生成"
  wrong_task_creation:
    - location: "OmniFocus UI 直接（Inbox/Project）"
      why: "同期を壊し孤児タスクを作る。Vault バックアップも GitHub 記録もない"
      recovery: "'sync tasks' 実行 → 自動ハッシュ化で Vault に追加・OmniFocus をリネーム"
  post_sync_validation:
    - "全 OmniFocus タスクが TaskHash を持つ"
    - "全 TaskHash が sync_state.json に存在"
    - "全 Vault タスクが対応する OmniFocus エントリを持つ"
    - "カバレッジ: 全タスクの 100%"
  troubleshooting:
    "OmniFocus に TaskHash 無しタスク": "'sync tasks' → 自動ハッシュ化で修正"
    "タスクが Vault に出ない": "作成日の Daily Note を確認（today とは限らない）"
    "同期が不完全に見える": "'sync tasks' を再実行して再検証・自動修復"

# -----------------------------------------------------------------------------
# 22. バージョン履歴
# -----------------------------------------------------------------------------
version_history:
  v2.5:
    date: "2026-05-05"
    highlights:
      - "不変 TaskHash 生成（CRC32）"
      - "GitHub Issue → OmniFocus Project 変換"
      - "Vault Daily Notes → OmniFocus Inbox 同期"
      - "完了・期日の双方向同期、階層検出、ドメイン分離"
      - "TaskHashless Project 対応（Later → Vault）"
      - "フック起点の手動フル同期トリガー"
  v2.6:
    date: "2026-05-28"
    highlights:
      - "PLAN B: scan_omnifocus_inbox.py の強化スキップロジック"
      - "PLAN C: 重複検出・防止（validate_no_duplicate_hashes / detect_parent_mismatch）"
  v2.7:
    date: "2026-05-30"
    highlights:
      - "GitHub ステータス逆転バグ修正（reverse_sync.py 双方向対応）"
      - "STEP 2.2 追加、--existing-issue-updates パラメータ"
  v2.8:
    date: "2026-05-30"
    highlights:
      - "OmniFocus 削除カスケード（detect_deleted_omnifocus_tasks.py, PRE-STEP）"
  v3.0:
    date: "2026-05-30"
    highlights:
      - "PHASE1: 緊急クリーンアップ（phantom検出・緊急ハッシュ化）"
      - "PHASE2: MCP 実行層（実IDキャプチャ）"
      - "PHASE3: 堅牢な監視（consistency検証・自己修復）"
      - "PHASE4: run_full_sync.py で全フェーズ統括"
```
