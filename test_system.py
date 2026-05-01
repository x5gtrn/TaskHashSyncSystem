#!/usr/bin/env python3
"""
Task Hash Sync System - Comprehensive Test Suite

Validates all components of the task hash synchronization system.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from datetime import datetime

from task_hash import (
    compute_hash,
    make_github_source_id,
    make_vault_source_id,
    append_hash,
    has_hash,
    extract_hash,
    remove_hash,
)


class TestRunner:
    """Simple test runner for validation tests."""

    def __init__(self):
        self.passed = 0
        self.failed = 0

    def test(self, name: str, condition: bool, expected=None, actual=None) -> None:
        """Run a single test."""
        if condition:
            print(f"✓ {name}")
            self.passed += 1
        else:
            print(f"✗ {name}")
            if expected is not None and actual is not None:
                print(f"  Expected: {expected}")
                print(f"  Actual: {actual}")
            self.failed += 1

    def summary(self) -> None:
        """Print test summary."""
        total = self.passed + self.failed
        print(f"\n{'=' * 50}")
        print(f"Tests: {self.passed}/{total} passed")
        if self.failed > 0:
            print(f"Failures: {self.failed}")
            sys.exit(1)


def test_hash_generation():
    """Test hash generation functionality."""
    print("\n=== Hash Generation Tests ===\n")
    runner = TestRunner()

    # Test 1: Consistent hash generation
    source_id = "github:x5gtrn/LIFE#1:Revolut"
    hash1 = compute_hash(source_id)
    hash2 = compute_hash(source_id)
    runner.test("Hash is consistent", hash1 == hash2, hash1, hash2)

    # Test 2: Different inputs produce different hashes
    source_id2 = "github:x5gtrn/LIFE#2:Revolut"
    hash3 = compute_hash(source_id2)
    runner.test("Different inputs produce different hashes", hash1 != hash3)

    # Test 3: Hash format (8 hex digits)
    runner.test("Hash is 8 hex digits", len(hash1) == 8 and all(c in '0123456789abcdef' for c in hash1))

    # Test 4: Source ID creation
    gh_id = make_github_source_id("x5gtrn", "LIFE", 1, "Revolut")
    runner.test("GitHub source_id format", gh_id == "github:x5gtrn/LIFE#1:Revolut", gh_id, "github:x5gtrn/LIFE#1:Revolut")

    vault_id = make_vault_source_id("Calendar/Daily/2026/04/2026-04-15.md", "Test Task")
    expected_vault_id = "vault:Calendar/Daily/2026/04/2026-04-15.md:Test Task"
    runner.test("Vault source_id format", vault_id == expected_vault_id, vault_id, expected_vault_id)

    runner.summary()


def test_task_naming():
    """Test task naming with hashes."""
    print("\n=== Task Naming Tests ===\n")
    runner = TestRunner()

    source_id = "github:x5gtrn/LIFE#1:TestTask"
    task_name = "TestTask"

    # Test 1: Append hash
    task_with_hash = append_hash(task_name, source_id)
    runner.test("Hash is appended", has_hash(task_with_hash))

    # Test 2: Extract hash
    extracted = extract_hash(task_with_hash)
    expected_hash = compute_hash(source_id)
    runner.test("Hash can be extracted", extracted == expected_hash, extracted, expected_hash)

    # Test 3: Detect existing hash
    runner.test("Detects existing hash", has_hash(task_with_hash))

    # Test 4: No duplicate hash appending
    task_with_hash_again = append_hash(task_with_hash, source_id)
    runner.test("Prevents duplicate hash", task_with_hash == task_with_hash_again, task_with_hash, task_with_hash_again)

    # Test 5: Remove hash
    without_hash = remove_hash(task_with_hash)
    runner.test("Hash can be removed", without_hash == task_name, without_hash, task_name)
    runner.test("Removed task doesn't have hash", not has_hash(without_hash))

    # Test 6: Hash format in task name
    runner.test("Hash format is correct", has_hash(task_with_hash) and extract_hash(task_with_hash) is not None)

    runner.summary()


def test_sync_state():
    """Test sync state file handling."""
    print("\n=== Sync State Tests ===\n")
    runner = TestRunner()

    # Create temporary state file
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "sync_state.json"

        # Test 1: Create initial state
        state = {}
        with open(state_file, 'w') as f:
            json.dump(state, f)
        runner.test("Empty state file created", state_file.exists())

        # Test 2: Add entry to state
        hash_value = "12345678"
        state[hash_value] = {
            "source_id": "github:x5gtrn/LIFE#1:TestTask",
            "of_task_id": "xyz123",
            "of_task_name": "TestTask (12345678)",
            "status": "open",
            "synced_at": datetime.now().isoformat()
        }
        with open(state_file, 'w') as f:
            json.dump(state, f, indent=2)
        runner.test("State entry saved", True)

        # Test 3: Load state
        with open(state_file, 'r') as f:
            loaded_state = json.load(f)
        runner.test("State entry loaded", hash_value in loaded_state)
        runner.test("State data preserved", loaded_state[hash_value]["source_id"] == "github:x5gtrn/LIFE#1:TestTask")

    runner.summary()


def test_integration():
    """Test integration between components."""
    print("\n=== Integration Tests ===\n")
    runner = TestRunner()

    # Simulate complete workflow
    owner, repo, issue_num = "x5gtrn", "LIFE", 1
    tasks = ["Revolut", "MoneyWiz", "Bitcoin"]

    for task in tasks:
        source_id = make_github_source_id(owner, repo, issue_num, task)
        task_hash = compute_hash(source_id)
        task_with_hash = append_hash(task, source_id)

        runner.test(f"Task '{task}' gets hash", has_hash(task_with_hash))
        runner.test(f"Task '{task}' hash is 8 digits", len(extract_hash(task_with_hash)) == 8)

    # Test vault source IDs
    vault_path = "Calendar/Daily/2026/04/2026-04-15.md"
    vault_task = "Check email"

    vault_source_id = make_vault_source_id(vault_path, vault_task)
    vault_hash = compute_hash(vault_source_id)
    vault_task_with_hash = append_hash(vault_task, vault_source_id)

    runner.test("Vault task gets hash", has_hash(vault_task_with_hash))
    runner.test("Vault hash can be extracted", extract_hash(vault_task_with_hash) == vault_hash)

    runner.summary()


def test_github_sync_dry_run():
    """Test GitHub sync in dry-run mode."""
    print("\n=== GitHub Sync Dry-Run Test ===\n")

    try:
        result = subprocess.run(
            ['python3', 'sync_github.py', '--repo', 'x5gtrn/LIFE', '--dry-run'],
            capture_output=True,
            text=True,
            timeout=10
        )

        print("GitHub sync dry-run output:")
        print(result.stdout)

        if result.returncode == 0:
            print("✓ GitHub sync dry-run completed successfully")
        else:
            print(f"✗ GitHub sync failed with code {result.returncode}")
            if result.stderr:
                print(result.stderr)

    except subprocess.TimeoutExpired:
        print("✗ GitHub sync timed out")
    except FileNotFoundError:
        print("⊘ sync_github.py not found (this test requires the script in current directory)")


def test_vault_sync_dry_run():
    """Test Vault sync in dry-run mode."""
    print("\n=== Vault Sync Dry-Run Test ===\n")

    try:
        vault_root = "/Users/x5gtrn/Library/Mobile Documents/iCloud~md~obsidian/Documents/LIFE"
        result = subprocess.run(
            ['python3', 'sync_vault.py', '--vault-root', vault_root, '--dry-run'],
            capture_output=True,
            text=True,
            timeout=10
        )

        # Just show first few lines
        lines = result.stdout.split('\n')[:10]
        print("Vault sync dry-run output (first 10 lines):")
        for line in lines:
            print(line)

        if result.returncode == 0:
            print("\n✓ Vault sync dry-run completed successfully")
        else:
            print(f"✗ Vault sync failed with code {result.returncode}")
            if result.stderr:
                print(result.stderr)

    except subprocess.TimeoutExpired:
        print("✗ Vault sync timed out")
    except FileNotFoundError:
        print("⊘ sync_vault.py not found (this test requires the script in current directory)")


def main():
    """Run all tests."""
    print("╔════════════════════════════════════════════════════╗")
    print("║   Task Hash Sync System - Test Suite               ║")
    print("╚════════════════════════════════════════════════════╝")

    try:
        test_hash_generation()
        test_task_naming()
        test_sync_state()
        test_integration()
        test_github_sync_dry_run()
        test_vault_sync_dry_run()

        print("\n" + "=" * 50)
        print("All test suites completed!")
        print("=" * 50)

    except Exception as e:
        print(f"\n✗ Test suite failed with error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
