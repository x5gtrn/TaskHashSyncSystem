#!/usr/bin/env python3
"""
Task Hash Generator - CRC32 based task identification

Generates unique hashes for tasks across GitHub Issues, Obsidian Vault, and OmniFocus
using CRC32 for lightweight identification (8 hex digits).

Payload format inspired by Git object headers:
  payload = f"task {len(source_id.encode())}\0{source_id}".encode()
  hash = format(zlib.crc32(payload) & 0xFFFFFFFF, '08x')
"""

import zlib
import re
from typing import Tuple


def compute_hash(source_id: str) -> str:
    """
    Generate a CRC32-based hash for a given source_id.

    Args:
        source_id: Unique identifier string (e.g., "github:x5gtrn/LIFE#1:TaskName")

    Returns:
        8-character hex string hash
    """
    # Format payload similar to Git object header
    payload = f"task {len(source_id.encode())}\0{source_id}".encode()

    # Compute CRC32 and convert to 8-digit hex
    hash_value = zlib.crc32(payload) & 0xFFFFFFFF
    return format(hash_value, '08x')


def make_github_source_id(owner: str, repo: str, issue_num: int, task_name: str) -> str:
    """
    Create a source_id for a GitHub Issue task.

    Args:
        owner: GitHub repository owner
        repo: GitHub repository name
        issue_num: Issue number
        task_name: Task or subtask name

    Returns:
        source_id string
    """
    return f"github:{owner}/{repo}#{issue_num}:{task_name}"


def make_vault_source_id(relative_path: str, task_name: str) -> str:
    """
    Create a source_id for a Vault task.

    Args:
        relative_path: Relative path from vault root (e.g., "Calendar/Daily/2026/04/2026-04-15.md")
        task_name: Task name

    Returns:
        source_id string
    """
    return f"vault:{relative_path}:{task_name}"


def append_hash(task_name: str, source_id: str) -> str:
    """
    Append hash to task name if not already present.

    Args:
        task_name: Original task name
        source_id: Source identifier for hash generation

    Returns:
        Task name with appended hash (e.g., "Task Name (3f88f98c)")
    """
    # Check if hash is already appended
    if has_hash(task_name):
        return task_name

    hash_value = compute_hash(source_id)
    return f"{task_name} ({hash_value})"


def has_hash(task_name: str) -> bool:
    """
    Check if a task name already has a hash appended.

    Pattern: " (XXXXXXXX)" where X is a hex digit

    Args:
        task_name: Task name to check

    Returns:
        True if hash pattern is found, False otherwise
    """
    pattern = r' \([0-9a-f]{8}\)$'
    return bool(re.search(pattern, task_name))


def extract_hash(task_name: str) -> str | None:
    """
    Extract hash from a task name.

    Args:
        task_name: Task name potentially containing hash

    Returns:
        Hash string (without parentheses) if found, None otherwise
    """
    pattern = r' \(([0-9a-f]{8})\)$'
    match = re.search(pattern, task_name)
    return match.group(1) if match else None


def remove_hash(task_name: str) -> str:
    """
    Remove hash suffix from a task name.

    Args:
        task_name: Task name with potential hash

    Returns:
        Task name without hash
    """
    pattern = r' \([0-9a-f]{8}\)$'
    return re.sub(pattern, '', task_name)


def extract_markdown_links(text: str) -> Tuple[str, list]:
    """
    Extract Markdown links from text.

    Parses Markdown link syntax [text](url) and returns cleaned text + URLs.

    Args:
        text: Text potentially containing Markdown links (e.g., "[Google](https://google.com)")

    Returns:
        Tuple of (cleaned_text, urls_list)
        - cleaned_text: Original text with [](url) syntax removed, keeping only display text
        - urls_list: List of extracted URLs
    """
    urls = []
    # Pattern: [text](url)
    pattern = r'\[([^\]]+)\]\(([^)]+)\)'

    def replace_link(match):
        """Replace [text](url) with just text, collect URL."""
        text_content = match.group(1)
        url = match.group(2)
        urls.append(url)
        return text_content

    cleaned_text = re.sub(pattern, replace_link, text)
    return cleaned_text.strip(), urls


def clean_markdown_links(task_name: str) -> str:
    """
    Remove Markdown link syntax from task name, keeping only display text.

    Args:
        task_name: Task name potentially containing Markdown links

    Returns:
        Cleaned task name with [text](url) → text
    """
    cleaned, _ = extract_markdown_links(task_name)
    return cleaned


def get_markdown_urls(text: str) -> list:
    """
    Extract all URLs from Markdown link syntax.

    Args:
        text: Text potentially containing Markdown links

    Returns:
        List of URLs found
    """
    _, urls = extract_markdown_links(text)
    return urls


if __name__ == "__main__":
    # Test examples
    print("=== Task Hash Generator Tests ===\n")

    # GitHub example
    github_id = make_github_source_id("x5gtrn", "LIFE", 1, "Revolut")
    github_hash = compute_hash(github_id)
    print(f"GitHub source_id: {github_id}")
    print(f"GitHub hash: {github_hash}")
    print(f"Appended task name: {append_hash('Revolut', github_id)}\n")

    # Vault example
    vault_id = make_vault_source_id("Calendar/Daily/2026/04/2026-04-15.md", "YouTube Channel...")
    vault_hash = compute_hash(vault_id)
    print(f"Vault source_id: {vault_id}")
    print(f"Vault hash: {vault_hash}")
    print(f"Appended task name: {append_hash('YouTube Channel...', vault_id)}\n")

    # Test has_hash
    task_with_hash = "Test Task (3f88f98c)"
    print(f"Task with hash: '{task_with_hash}'")
    print(f"has_hash(): {has_hash(task_with_hash)}")
    print(f"extract_hash(): {extract_hash(task_with_hash)}")
    print(f"remove_hash(): '{remove_hash(task_with_hash)}'")
