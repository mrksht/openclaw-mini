#!/usr/bin/env python3
"""Debug: test tool calling via Portkey."""
import json
from openclaw.config import get_portkey_client, DEFAULT_MODEL

client = get_portkey_client()

tools = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command to run"}
                },
                "required": ["command"],
            },
        },
    }
]

print(f"Model: {DEFAULT_MODEL}")
print(f"Tools: {json.dumps(tools, indent=2)}")
print()

response = client.chat.completions.create(
    model=DEFAULT_MODEL,
    messages=[
        {"role": "system", "content": "You are a helpful assistant. Always use tools when the user asks you to run commands. Do not describe what you would do - actually call the tool."},
        {"role": "user", "content": "Please run the ls command"},
    ],
    tools=tools,
    max_tokens=1024,
)

choice = response.choices[0]
print(f"finish_reason: {choice.finish_reason}")
print(f"content: {repr(choice.message.content)}")
print(f"tool_calls: {choice.message.tool_calls}")
if choice.message.tool_calls:
    for tc in choice.message.tool_calls:
        print(f"  tool: {tc.function.name}({tc.function.arguments})")
else:
    print("NO TOOL CALLS - model responded with text only")
    print(f"Full message: {choice.message}")
