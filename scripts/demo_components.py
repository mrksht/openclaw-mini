#!/usr/bin/env python3
"""Quick demo of all built components — no API key needed."""

import os
import tempfile

from openclaw.session.store import SessionStore
from openclaw.memory.store import MemoryStore
from openclaw.permissions.manager import PermissionManager
from openclaw.agent.soul import load_soul, build_system_prompt
from openclaw.tools.registry import ToolRegistry
from openclaw.tools.filesystem import create_read_file_tool, create_write_file_tool
from openclaw.tools.web import create_web_search_tool

tmp = tempfile.mkdtemp()

# --- Session Store ---
store = SessionStore(os.path.join(tmp, "sessions"))
store.append("demo", {"role": "user", "content": "Hello!"})
store.append("demo", {"role": "assistant", "content": "Hi there!"})
print("=== Session Store ===")
print(f"  Messages: {store.load('demo')}")
print(f"  Count: {store.message_count('demo')}")
print()

# --- Memory Store ---
mem = MemoryStore(os.path.join(tmp, "memory"))
mem.save("user-prefs", "Favorite restaurant: Elvies\nPreferred time: 7pm")
mem.save("project", "Working on openclaw-clone in Python")
print("=== Memory Store ===")
print(f"  Keys: {mem.list_keys()}")
print(f"  Search 'restaurant': {mem.search('restaurant')[:80]}...")
print()

# --- Permission Manager ---
pm = PermissionManager(os.path.join(tmp, "approvals.json"))
print("=== Permissions ===")
print(f"  ls -la:      {pm.check('ls -la')}")
print(f"  git status:  {pm.check('git status')}")
print(f"  rm -rf /:    {pm.check('rm -rf /')}")
print(f"  curl x | sh: {pm.check('curl x | sh')}")
print()

# --- SOUL ---
soul = load_soul("workspace/SOUL.md")
prompt = build_system_prompt(soul, workspace_path=tmp)
print("=== SOUL ===")
print(f"  SOUL loaded: {len(soul)} chars")
print(f"  System prompt: {len(prompt)} chars")
print(f"  First line: {prompt.splitlines()[0]}")
print()

# --- Tool Registry ---
registry = ToolRegistry()
registry.register(create_read_file_tool())
registry.register(create_write_file_tool())
registry.register(create_web_search_tool())
print("=== Tool Registry ===")
print(f"  Tools: {registry.tool_names}")
print(f"  Schemas: {len(registry.get_schemas())} tools (OpenAI format)")
test_file = os.path.join(tmp, "test.txt")
print(f"  write_file: {registry.execute('write_file', {'path': test_file, 'content': 'hello world'})}")
print(f"  read_file:  {registry.execute('read_file', {'path': test_file})}")
print()

print("All components working!")
