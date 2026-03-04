# Agent Loop — `run_agent_turn()` Explained

> **File:** `src/openclaw/agent/loop.py`

## The Big Picture

This function handles **one complete user interaction**: the user says something → the LLM thinks → maybe uses tools → responds. It's a loop because the LLM might need to call tools multiple times before giving a final answer.

```
User: "What files are in /tmp?"
  → LLM: "I'll run ls /tmp" (tool call)
    → Tool executes: "file1.txt  file2.log"
  → LLM: "There are 2 files in /tmp: file1.txt and file2.log" (final answer)
```

---

## Visual Flow

```
run_agent_turn("What files are in /tmp?")
│
├─ Load session history from JSONL
├─ Compact if > 100k tokens
├─ Append user message
├─ Build tiered context [system + cold + warm + hot]
│
├─ LOOP iteration 1:
│   ├─ Call LLM ──────────────────────────────► Portkey/OpenAI API
│   ├─ Response: tool_call(shell, "ls /tmp")
│   ├─ Execute: shell("ls /tmp") → "file1.txt\nfile2.log"
│   ├─ Save assistant msg + tool result to JSONL
│   └─ Append to api_messages, continue loop
│
├─ LOOP iteration 2:
│   ├─ Call LLM (now sees tool result) ───────► Portkey/OpenAI API
│   ├─ Response: "There are 2 files: ..." (finish_reason="stop")
│   ├─ Save to JSONL
│   └─ return "There are 2 files: ..."
│
└─ Done
```

---

## Step-by-Step Walkthrough

### 1. Function Signature

```python
def run_agent_turn(
    client,              # the Portkey/OpenAI client object
    model: str,          # which LLM model to use
    system_prompt: str,  # SOUL.md + workspace context
    session_key: str,    # unique ID like "agent:main:repl:repl"
    user_text: str,      # what the user typed
    session_store,       # loads/saves conversation history (JSONL files)
    tool_registry,       # knows what tools exist and how to run them
    max_turns: int = 20, # safety limit — max 20 LLM calls per turn
    on_tool_use = None,  # optional callback to print tool usage
    compaction_threshold = 100_000,  # token limit before summarizing
    memory_store = None, # long-term memory for cold-tier injection
    hot_turns: int = 20, # how many recent turns to keep verbatim
) -> str:                # returns the final text response
```

### 2. Load Conversation History

```python
messages = _sanitize_loaded_messages(session_store.load(session_key))
```

Reads from `~/.mini-openclaw/sessions/<session_key>.jsonl`. Returns something like:

```python
[
    {"role": "user", "content": "hello"},
    {"role": "assistant", "content": "Hi! How can I help?"},
    {"role": "user", "content": "list files"},
    {"role": "assistant", "content": "...", "tool_calls": [...]},
    {"role": "tool", "tool_call_id": "...", "content": "file1.txt"},
    {"role": "assistant", "content": "I found file1.txt"},
]
```

`_sanitize_loaded_messages` does two things:
- Fixes empty `content` fields (Anthropic/Bedrock rejects `null` content)
- Removes orphaned tool-call messages at the end (from past crashes where the tool result never got saved)

### 3. Compaction Check

```python
if estimate_tokens(messages) >= compaction_threshold:
    messages = compact(messages, client, model, threshold=compaction_threshold)
    session_store.save(session_key, messages)
```

If the conversation is getting too long (~100k tokens), it summarizes older messages into a shorter form. This prevents exceeding the LLM's context window. The compacted version **overwrites** the session file.

### 4. Add the User's New Message

```python
user_msg = {"role": "user", "content": user_text}
messages.append(user_msg)                    # add to in-memory list
session_store.append(session_key, user_msg)  # persist to JSONL file
```

Now `messages` has the full history + the new user message.

### 5. Build Tiered Context

```python
api_messages = build_tiered_context(
    system_prompt=system_prompt,
    messages=messages,
    memory_store=memory_store,
    hot_turns=hot_turns,
)
```

Builds the actual list sent to the LLM:

```python
[
    {"role": "system", "content": "You are Jarvis..."},      # system prompt
    {"role": "user", "content": "[MEMORY]\nkey1: ...\n..."},  # cold tier (long-term memory)
    {"role": "assistant", "content": "Understood..."},        # ack
    {"role": "user", "content": "[EARLIER CONTEXT]\n..."},    # warm tier (older turns)
    {"role": "assistant", "content": "Understood..."},        # ack
    # ... hot tier: last N turns verbatim ...
    {"role": "user", "content": "hello"},
    {"role": "assistant", "content": "Hi!"},
    {"role": "user", "content": "What files are in /tmp?"},   # ← newest message
]
```

**Important**: `messages` is the full history. `api_messages` is the shaped version sent to the LLM. They're separate lists.

### 6. Get Tool Schemas

```python
tools = tool_registry.get_schemas()
```

Returns JSON schemas the LLM needs to know about:

```python
[
    {"type": "function", "function": {"name": "shell", "parameters": {...}}},
    {"type": "function", "function": {"name": "read_file", "parameters": {...}}},
    ...
]
```

### 7. The Main Loop

```python
for _ in range(max_turns):    # up to 20 iterations
```

Each iteration = one LLM API call. The LLM might say "run this tool", get the result, then say "run another tool", get that result, then finally give a text answer. Each of those is one iteration.

### 8. Call the LLM

```python
kwargs = {
    "model": model,
    "messages": api_messages,
    "max_tokens": 4096,
}
if tools:
    kwargs["tools"] = tools

response = client.chat.completions.create(**kwargs)
choice = response.choices[0]
assistant_message = choice.message
```

Sends the full message array to the LLM. The response has:
- `choice.finish_reason` — `"stop"` (done talking) or `"tool_calls"` (wants to use a tool)
- `choice.message.content` — the text response (if any)
- `choice.message.tool_calls` — list of tools it wants to call (if any)

### 9. Serialize the Response

```python
serialized_msg = _serialize_assistant_message(assistant_message)
```

Converts the SDK object into a plain dict we can save to JSON:

```python
{"role": "assistant", "content": "Let me check...", "tool_calls": [{...}]}
```

### 10. Check: Is the LLM Done?

```python
has_tool_calls = choice.finish_reason in ("tool_calls", "tool_use") and assistant_message.tool_calls

if not has_tool_calls:
    messages.append(serialized_msg)
    session_store.append(session_key, serialized_msg)
    return assistant_message.content or ""
```

If `finish_reason` is `"stop"` — no tools, just a text answer. **Save it and return**. The function exits here for simple Q&A with no tool use.

### 11. Execute Tools

If we get here, the LLM wants tools. For each tool call:

```python
for tool_call in assistant_message.tool_calls:
    tool_name = tool_call.function.name           # e.g. "shell"
    tool_input = json.loads(tool_call.function.arguments)  # e.g. {"command": "ls /tmp"}

    result = tool_registry.execute(tool_name, tool_input)  # actually runs the command

    if on_tool_use:
        on_tool_use(tool_name, tool_input, result)  # print to terminal

    tool_result_msgs.append({
        "role": "tool",
        "tool_call_id": tool_call.id,   # links result back to the request
        "content": str(result),          # e.g. "file1.txt\nfile2.log"
    })
```

### 12. Persist Everything Atomically

```python
# Save assistant message (with tool_calls)
messages.append(serialized_msg)
session_store.append(session_key, serialized_msg)
api_messages.append(serialized_msg)

# Save all tool results
for tool_msg in tool_result_msgs:
    messages.append(tool_msg)
    session_store.append(session_key, tool_msg)
    api_messages.append(tool_msg)
```

The assistant message + **all its tool results** are saved together. This prevents the orphaned-tool-call problem (assistant says "call tool X" but the result is never recorded due to a crash).

Then the loop goes back to **step 8** — calls the LLM again with the tool results appended. The LLM sees the results and either:
- Calls more tools → loop continues
- Gives a text answer → exits at step 10

### 13. Safety Fallback

```python
return "(max tool turns reached)"
```

If the loop runs 20 times without the LLM giving a final answer, bail out. Prevents infinite loops.

---

## The Orphan Problem & Atomic Saves

### Without this pattern (broken)

```python
# ❌ Save assistant message IMMEDIATELY
session_store.append(session_key, serialized_msg)    # saved: assistant + tool_calls

# Then execute tools...
result = tool_registry.execute("shell", {"command": "ls /tmp"})

# 💥 CRASH HERE (power loss, exception, Ctrl+C)

# Never reaches this:
session_store.append(session_key, tool_result_msg)   # never saved
```

JSONL file now has:

```
{"role": "assistant", "tool_calls": [{"id": "call_1", ...}]}
← EOF, no tool result
```

Next session load → LLM sees "I asked for a tool" but never got the answer → confused / breaks.

### With the current pattern (safe)

```python
# ✅ Execute ALL tools first (nothing saved yet)
for tool_call in assistant_message.tool_calls:
    result = tool_registry.execute(tool_name, tool_input)
    tool_result_msgs.append(...)

# 💥 If crash happens ABOVE, nothing was saved.
#    Session file still ends at the user message. Clean state.

# Only AFTER all tools succeed, save everything:
session_store.append(session_key, serialized_msg)     # assistant + tool_calls
for tool_msg in tool_result_msgs:
    session_store.append(session_key, tool_msg)        # tool results
```

Two possible states on disk:

| Scenario | What's on disk | Clean? |
|---|---|---|
| Crash **during** tool execution | Nothing new saved — file ends at user message | Yes |
| No crash | Assistant + all tool results saved together | Yes |

If an orphan does slip through (crash between the `append` calls), `_sanitize_loaded_messages` cleans it up on the next load by removing trailing assistant messages that have `tool_calls` but no subsequent tool results.

---

## Concrete Multi-Tool Example

User asks: **"What's in /tmp and what's the date?"**

### Iteration 1

LLM returns two tool calls:

```python
choice.finish_reason = "tool_calls"
assistant_message.tool_calls = [
    ToolCall(id="call_1", function=Function(name="shell", arguments='{"command": "ls /tmp"}')),
    ToolCall(id="call_2", function=Function(name="shell", arguments='{"command": "date"}')),
]
```

Both tools execute. Saved to JSONL:

```
{"role": "assistant", "content": "Let me check both.", "tool_calls": [call_1, call_2]}
{"role": "tool", "tool_call_id": "call_1", "content": "file1.txt\nfile2.log"}
{"role": "tool", "tool_call_id": "call_2", "content": "Mon Mar  3 14:30:00 IST 2026"}
```

Loop continues → back to step 8.

### Iteration 2

LLM now sees the tool results and gives a final answer:

```python
choice.finish_reason = "stop"
assistant_message.content = "Here's what I found:\n- /tmp contains: file1.txt, file2.log\n- Current date: Mon Mar 3 14:30:00 IST 2026"
```

`has_tool_calls` is `False` → save and return. Done.

### Final JSONL session file

```
{"role": "user", "content": "What's in /tmp and what's the date?"}
{"role": "assistant", "content": "Let me check both.", "tool_calls": [...]}
{"role": "tool", "tool_call_id": "call_1", "content": "file1.txt\nfile2.log"}
{"role": "tool", "tool_call_id": "call_2", "content": "Mon Mar  3 14:30:00 IST 2026"}
{"role": "assistant", "content": "Here's what I found:\n- /tmp contains: ..."}
```

5 lines. 1 user message, 2 LLM calls, 2 tool results.

---

## Helper Functions

### `_serialize_tool_calls(tool_calls)`

Converts OpenAI SDK `ToolCall` objects into plain dicts for JSON storage.

### `_serialize_assistant_message(message)`

Converts an OpenAI `ChatCompletionMessage` into a serializable dict. Also replaces empty content with `"(no response)"` because Bedrock/Anthropic rejects null content.

### `_sanitize_loaded_messages(messages)`

Cleans up loaded session history:
1. Fixes empty `content` fields
2. Removes trailing orphaned assistant tool-call messages (from crashes)

Walks backwards from the end, popping any assistant message with `tool_calls` that has nothing after it.
