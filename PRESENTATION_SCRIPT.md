# Mini OpenClaw Presentation Script
## Complete Speaking Guide (45 minutes)

**Title:** "From Chat to Action: Building AI Agents with Tool Use, Memory & Safety"

---

## 🎬 SECTION 1: INTRODUCTION (5 minutes)

### Slide 1: Title + Opening

**[Show title slide]**

"Good morning/afternoon everyone. Thanks for being here.

So, I'm Rakshit, and I come from a JavaScript background. Most of my career has been building web applications — React, Node, the usual suspects. 

But about six months ago, I got curious about AI agents. Not just chatbots that talk, but agents that actually *do* things. And I wanted to understand how they work under the hood.

Here's the honest part: I didn't really know Python well when I started this project. I built most of this with AI assistance — specifically Claude. And I think that's actually part of the story worth telling today.

What you're going to see is a working AI assistant framework called Mini OpenClaw. It's about 500 lines of core logic. It can run on Telegram, Slack, as a command-line REPL, or as an HTTP API. It has persistent memory, it can execute tools like shell commands and file operations, and it has safety mechanisms built in.

This isn't about comparing frameworks. This is about understanding the primitives — how do AI agents actually work? When you strip away all the abstractions, what's left?"

---

### Slide 2: What This Is

**[Show feature list slide]**

"So what is Mini OpenClaw?

It's a self-hosted AI assistant with these key features:

**Multi-channel support** — The same agent can run on Slack, Telegram, as a REPL in your terminal, or as an HTTP API. You're not locked into one interface.

**Persistent memory** — The agent can save facts and recall them across sessions. If you tell it something today, it remembers next week.

**Tool execution** — This is the key part. The agent doesn't just talk. It can run shell commands, read and write files, search the web, fetch data from APIs. It takes actions.

**Permission gating** — Because giving an AI the ability to run shell commands is scary, right? So there's a permission system that asks for human approval on dangerous operations.

**Scheduled tasks** — I call these 'heartbeats.' You can configure the agent to do things autonomously on a schedule. Like 'every morning at 9am, summarize what happened yesterday.'

And all of this core logic is about 500 lines of Python.

This isn't a production-grade framework. It's a learning project. But it works, and it helps you understand how AI agents actually operate."

---

### Slide 3: What We'll Cover Today

**[Show agenda slide]**

"Here's what we'll cover in the next 45 minutes:

First, **architecture** — we'll look at how all the pieces fit together. How do you structure an AI agent system?

Second, **tool-use patterns** — this is how you make LLMs actually do things instead of just generating text.

Third, **memory and session management** — how do you keep context across conversations without blowing up your token budget?

Fourth, **permission gating** — how do you balance autonomy with safety?

Fifth, **a live demo** — I'll actually run this thing and show you what it looks like in action.

Sixth, **code walkthrough** — we'll look at the actual implementation. No hand-waving, we'll read the code.

And finally, **lessons learned** — what I discovered going from JavaScript to Python with AI as a pair programmer.

Alright, let's dive in."

---

## 🏗️ SECTION 2: ARCHITECTURE (12 minutes)

### Slide 4: System Architecture

**[Show architecture diagram]**

"Let's start with the big picture. How is this thing architected?

At the top, you have **channels**. These are your interfaces to the outside world. Telegram, Slack, REPL, HTTP API. Each channel knows how to receive messages from its respective platform and send messages back.

Those channels feed into an **AgentRouter**. This is optional, but it's useful. The router can direct messages to different agents based on prefixes. So '/research' might go to one agent specialized in research, '/admin' might go to a different agent. For now, we'll focus on a single agent.

The heart of the system is the **Agent Loop**. This is where the magic happens. The agent loop does a few things:

1. It loads the conversation history from storage
2. It calls the LLM with that history plus the new message
3. The LLM might want to use tools, so we execute those tools
4. We feed the tool results back to the LLM
5. Repeat until the LLM is done
6. Save everything back to storage

Inside the agent loop, we have **tool execution**. These are functions the LLM can call. Run shell commands, read files, write files, search the web, save memories, search memories. Any Python function can be a tool.

Below that, we have three key components:

**SessionStore** — this persists conversation history as JSONL files. One file per session. Append-only writes, crash-safe, human-readable.

**PermissionManager** — this intercepts dangerous tool calls and asks a human for approval.

**HeartbeatScheduler** — this runs in a background thread and triggers agent prompts on a schedule.

The key architectural principles here are:

**Separation of concerns** — channels are completely separate from agent logic. You can run the same agent on different channels without changing anything.

**Composability** — everything is pluggable. Want a new channel? Implement the interface. Want a new tool? Register a function.

**Observability** — everything is logged as JSONL. When something breaks, you can just read the logs like text files. No database queries needed.

This is a simple architecture, but it works. And simplicity is underrated."

---

### Slide 5: Tool Use — The Core Mechanic

**[Show tool code example]**

"Alright, this is the most important concept. How do you make an LLM actually *do* things?

The answer is tool use, also called function calling.

Here's how it works:

When you call the LLM, you give it a list of tools. Each tool has a name, a description, and a schema for its parameters.

For example, here's a 'run_shell' tool:

```python
{
    "name": "run_shell",
    "description": "Execute a shell command",
    "parameters": {
        "command": {"type": "string", "description": "Shell command to run"}
    }
}
```

That's just JSON. The LLM sees this.

Now, when you send a message like 'Check the disk space', the LLM doesn't just respond with text. It responds with a tool call:

```python
tool_call(name="run_shell", args={"command": "df -h"})
```

It's generating structured data. It's saying 'I want to execute this function with these arguments.'

Your code then:
1. Executes the shell command
2. Gets the result (the output of df -h)
3. Sends that result back to the LLM
4. The LLM uses that information to formulate its final response

So the pattern is:
- LLM outputs structured JSON tool calls
- We execute them in our runtime (Python)
- Feed results back to the LLM
- Repeat until the LLM says 'I'm done'

This is how ChatGPT works when it's running code. This is how Claude works when it's using tools. This is how all modern AI agents work.

The beautiful thing is: you don't need to fine-tune the model. You don't need to train anything. You just describe your tools in JSON, and the LLM figures out when to use them.

That's the fundamental mechanism that makes AI agents possible."

---

### Slide 6: Memory System

**[Show directory structure]**

"Let's talk about memory.

One of the problems with AI agents is that LLMs are stateless. They don't remember anything between calls. Every time you call Claude or GPT, it's a fresh start.

So we have to manage state ourselves. And we have two types of state:

**Session history** — this is the conversation. All the back-and-forth messages. This is stored in `~/.mini-openclaw/sessions/` as JSONL files. One line per message. Append-only.

**Long-term memory** — this is facts that should persist across sessions. 'The user prefers tabs over spaces.' 'Project X uses Python 3.12.' This is stored as markdown files in `~/.mini-openclaw/memory/`.

The session history grows over time. And there's a problem: LLMs have context limits. Claude Sonnet 4.5 can handle 200K tokens, but that's expensive. Anthropic charges per token.

So when the session history gets too large — specifically, over 100K tokens — we automatically compact it. We use the LLM to summarize old messages, keep the recent ones, and replace the old ones with the summary.

This is done transparently. The user doesn't see it happen. But it means you can have multi-day conversations without hitting context limits or paying hundreds of dollars.

For memory search, right now it's just grep. Literally, we grep through markdown files. Is that fancy? No. Does it work? Yes. For a few thousand facts, grep is fine. If you needed to scale to millions of facts, you'd use embeddings and a vector database. But for v1, simple wins.

The key insight here is: good enough beats perfect. Markdown files and grep gets you 90% of the way there with 10% of the complexity."

---

### Slide 7: Permission Management

**[Show permission code]**

"Now let's talk about safety.

If you give an AI the ability to run shell commands, that's powerful. But it's also dangerous.

You don't want the AI to accidentally run `rm -rf /` because it misunderstood something. You don't want it downloading random scripts from the internet and piping them to bash.

So we have a permission manager.

Here's how it works:

```python
def check_permission(self, command: str) -> bool:
    dangerous_patterns = [
        r'\brm\b', r'\bmv\b', r'\bsudo\b', 
        r'\bcurl.*\|.*sh\b'
    ]
    
    if any(re.search(pat, command) for pat in dangerous_patterns):
        return self._prompt_human(command)
    return True
```

Before executing any shell command, we check it against a list of dangerous patterns. If it matches, we pause execution and prompt a human in the terminal:

```
The agent wants to run: rm old_data.txt
Allow this? (y/n):
```

You can approve or deny in real-time.

This is a tradeoff:

If you're **too strict**, the agent becomes useless. 'Sorry, I can't help with that.'

If you're **too loose**, the agent is dangerous. It can break things.

The solution is pattern matching plus human-in-the-loop for edge cases.

In this implementation, read operations auto-pass. `ls`, `cat`, `grep` — those are fine. Destructive operations like `rm`, `mv`, `sudo` — those require approval.

Is this perfect? No. A determined adversary could bypass this with command obfuscation. For production, you'd want proper sandboxing — Docker containers, gVisor, restricted command whitelists.

But for a personal assistant or a development tool, this strikes a good balance. The agent is useful but not dangerous."

---

## 🎥 SECTION 3: LIVE DEMO (10 minutes)

### Demo 1: REPL Mode

**[Switch to terminal, make sure font is large]**

"Alright, let's see this thing in action.

I'm going to run it in REPL mode, which is the simplest interface. It's just a command-line chat.

```bash
$ cd ~/Desktop/openclaw-mini
$ uv run openclaw repl
```

**[Wait for it to start]**

Okay, it's running. Let me start with a simple question.

```
You: Tell me about this project
```

**[Show the agent reading README.md and responding]**

See that? It didn't just make something up. It called the `read_file` tool, read the README.md, and then summarized it. That's tool use in action.

Now let me save a memory:

```
You: Save a memory: My favorite programming language is Python
```

**[Show the agent calling save_memory]**

It called the `save_memory` tool. That fact is now persisted to disk. Let me verify:

```
You: What did I just tell you about my favorite language?
```

**[Show the agent calling memory_search and recalling the fact]**

It called `memory_search`, found the memory, and recalled it. This works across sessions. If I quit and restart, it still remembers.

Let me try something more complex:

```
You: What's the largest file in this directory?
```

**[Show the agent calling run_shell with 'ls -lah']**

It ran `ls -lah`, got the output, parsed it, and told me the largest file. That's the agent using a tool to answer a question it couldn't otherwise answer.

Now let me try something dangerous:

```
You: Delete the README.md file
```

**[Show the permission prompt appearing]**

See that? It paused and asked me:

```
The agent wants to run: rm README.md
Allow this? (y/n):
```

I'm going to say no.

```
n
```

**[Show the agent getting permission denied]**

The agent got 'Permission denied' as the tool result, and it told the user it couldn't do it. That's the safety mechanism working.

This is the core loop. User message → LLM processes → tool calls → execute tools → results back to LLM → repeat."

---

### Demo 2: Heartbeat Scheduler

**[Open config.json in editor]**

"Now let me show you heartbeats.

Heartbeats are scheduled tasks. You define them in a config file:

```json
{
  "heartbeats": [
    {
      "name": "time-check",
      "schedule": "every 1 minute",
      "prompt": "Tell me the current time"
    }
  ]
}
```

This says: every 1 minute, send the agent this prompt autonomously.

When the agent is running, there's a background thread that watches the schedule. When it's time, it triggers the prompt, gets the agent's response, and sends it to the configured channel.

In production, you might use this for:
- 'Every hour, check if the production model has drifted'
- 'Every morning at 9am, summarize yesterday's logs'
- 'Every 5 minutes, check if the CI pipeline is failing'

The agent becomes autonomous. It's not just reactive to user messages. It's proactive."

---

### Demo 3: Multi-Channel

**[Show session file]**

"Last thing: persistence.

Let me show you the session file:

```bash
$ cat ~/.mini-openclaw/sessions/agent_main_user_repl.jsonl
```

**[Show the JSONL output]**

Every message is one line of JSON. You can see the user messages, assistant messages, tool calls, everything. It's human-readable.

If I stop the REPL and switch to Telegram or Slack, the same session continues. Same conversation history. Same memory. Different interface.

That's the power of separating channels from agent logic."

---

## 💻 SECTION 4: CODE DEEP DIVE (10 minutes)

### Focus Area 1: The Agent Loop

**[Open agent/loop.py in editor]**

"Alright, let's look at the actual code.

This is `agent/loop.py`, the heart of the system.

```python
def run_agent_turn(client, model, system_prompt, session_key, 
                   user_text, session_store, tool_registry, 
                   permission_manager, max_iterations=15):
```

This function runs one turn of the agent loop. It takes a user message, processes it, executes any tools, and returns the final response.

**Step 1: Load session history**

```python
messages = session_store.load(session_key)
messages.append({"role": "user", "content": user_text})
```

We load all previous messages from disk and append the new user message.

**Step 2: Check if compaction is needed**

```python
if estimate_tokens(messages) > 100_000:
    messages = compact(messages, client, model)
```

If the conversation is too long, we summarize old messages to save tokens.

**Step 3: The LLM loop**

```python
for iteration in range(max_iterations):
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system_prompt}] + messages,
        tools=tool_registry.get_schemas()
    )
```

We call the LLM. We pass it the system prompt, all the messages, and the list of available tools.

**Step 4: Check if we're done**

```python
if not response.tool_calls:
    break
```

If the LLM doesn't want to use any tools, we're done. Return the response.

**Step 5: Execute tools**

```python
for tool_call in response.tool_calls:
    result = tool_registry.execute(
        tool_call.name, 
        tool_call.arguments,
        permission_manager
    )
    messages.append(tool_result_message(result))
```

For each tool call, we execute it (with permission checks) and append the result as a new message. Then we loop back to step 3.

**Step 6: Persist everything**

```python
session_store.append_all(session_key, new_messages)
```

Finally, we save all the new messages to disk.

That's the entire agent loop. It's maybe 50 lines of code. This is the pattern used by every agentic system:

1. Call LLM
2. Execute tools
3. Feed results back
4. Repeat

The LLM is stateless. We manage all the state."

---

### Focus Area 2: JSONL Session Store

**[Open session/store.py]**

"Now let's look at how we persist sessions.

```python
def append(self, session_key: str, message: dict) -> None:
    path = self._path(session_key)
    with open(path, "a") as f:
        f.write(json.dumps(message) + "\n")
```

This is the append function. It's trivial. Open the file in append mode, write one line of JSON, done.

Why JSONL instead of a database?

**Append-only = crash-safe.** If the process crashes while writing, at most one line is corrupted. The rest of the file is fine.

**Human-readable.** You can cat the file and read it. No SQL queries needed.

**Simple.** No database setup, no migrations, no connection pools.

**Fast enough.** For ~10K messages per session, this is plenty fast.

Loading is equally simple:

```python
def load(self, session_key: str) -> list[dict]:
    messages = []
    with open(self._path(session_key)) as f:
        for line in f:
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # Skip corrupted lines
    return messages
```

Read the file line by line, parse each line as JSON, skip any corrupted lines. Done.

This is boring technology. But boring works. For v1, I'd rather spend time on features than database tuning."

---

### Focus Area 3: Tool Registry Pattern

**[Open tools/registry.py]**

"Last code piece: how do tools work?

```python
class ToolRegistry:
    def __init__(self):
        self._tools = {}
    
    def register(self, name: str, fn: Callable, schema: dict):
        self._tools[name] = {"fn": fn, "schema": schema}
```

The registry is just a dictionary. You register tools by giving them a name, a Python function, and a JSON schema.

```python
def get_schemas(self) -> list[dict]:
    return [tool["schema"] for tool in self._tools.values()]
```

This returns the schemas for all registered tools. We pass this to the LLM so it knows what tools are available.

```python
def execute(self, name: str, args: dict, permission_mgr) -> str:
    if name == "run_shell":
        if not permission_mgr.check_permission(args["command"]):
            return "Permission denied"
    
    result = self._tools[name]["fn"](**args)
    return str(result)
```

This executes a tool. It checks permissions if needed, calls the Python function, and returns the result as a string.

Adding a new tool is trivial. Let's say you want a tool to query a database:

```python
def query_db(sql: str) -> str:
    # Execute SQL, return results
    conn = psycopg2.connect(...)
    cursor = conn.execute(sql)
    return str(cursor.fetchall())

registry.register(
    name="query_db",
    fn=query_db,
    schema={
        "name": "query_db",
        "description": "Query the production database",
        "parameters": {
            "sql": {"type": "string", "description": "SQL query to execute"}
        }
    }
)
```

That's it. The LLM now knows about this tool and can use it.

The power of this pattern is extensibility. You don't modify the agent loop. You just register new functions. The LLM figures out when to use them based on the descriptions."

---

## 🌉 SECTION 5: PYTHON LESSONS (5 minutes)

### What Surprised Me About Python

**[Show comparison table slide]**

"Alright, let's talk about the JavaScript to Python journey.

I've been writing JavaScript for years. I know it well — closures, promises, prototype chains, the event loop, all the weird parts.

Python was new to me. Here's what surprised me:

**Dependency management:** In JavaScript, we have npm, yarn, pnpm — they're fast and reliable. Python has pip, poetry, pipenv, and lately uv. I used uv for this project. It's extremely fast. Way faster than pip. I was impressed.

**Type hints:** In JavaScript, if you want types, you use TypeScript, which is a separate language. You need a compiler. In Python, type hints are native. You just write them inline. No compilation step. This felt cleaner to me.

**Async:** JavaScript's async/await is everywhere. Most libraries are async-first. Python has asyncio, but the ecosystem is more mixed. Some libraries are sync, some are async, and mixing them is painful. I had to learn about event loops and executor pools. JavaScript's 'everything is async' is simpler.

**Error handling:** JavaScript has try-catch. Python has try-except. Same concept, different keyword. No biggie.

**Testing:** I used to use Jest in JavaScript. For this project, I used pytest. Pytest fixtures are amazing. They're better than Jest's setup/teardown. I'm a big fan.

**Packaging:** JavaScript has CommonJS vs ESM, which is a mess. Python has `pyproject.toml`, which is clean. I appreciated the simplicity.

Some candid moments:

I **still forget colons** after `if` statements. JavaScript doesn't use colons.

Understanding `__init__.py` took me a day. 'What is this file for? Why is it empty? Why do I need it?' Now I get it.

Python's simplicity for scripting is unmatched. I understand why people love it for data work.

And honestly, AI — specifically Claude — wrote about 60% of this code. I learned by reading what it wrote, modifying it, breaking it, and debugging together. That's a new way to learn a language, and it worked surprisingly well."

---

### How AI Assisted This Project

**[Keep same slide or next slide]**

"Let me be specific about how AI helped.

**Generated initial boilerplate:** I'd say 'Create a JSONL session store class' and it would scaffold the whole thing with docstrings and type hints. That's faster than writing it from scratch.

**Explained Python idioms:** I'd see something like `[x for x in items if x > 0]` and ask 'what is this?' It explained list comprehensions. Then I started using them everywhere.

**Debugged async issues:** I had a bug where the Telegram bot would hang. I gave Claude the stack trace. It said 'you're mixing sync and async, run this in an executor.' Fixed.

**Code reviews:** I'd write a function and ask 'is this idiomatic Python?' It would suggest improvements. 'Use a context manager here.' 'This should be a generator.' I learned Python style from AI feedback.

The key point is: AI makes language-switching less scary.

Five years ago, building this in a new language would have taken weeks of reading documentation, Stack Overflow, trial and error.

With AI, I got to working code faster, and I learned by doing. I'm not a Python expert now, but I shipped something real. That's powerful.

And I think this is relevant to everyone here. If you've been curious about Rust or Go or whatever, try building something with AI assistance. The barrier is lower than ever."

---

## 🚀 SECTION 6: REAL-WORLD EXTENSIONS (3 minutes)

### What You Could Build With This

**[Show examples slide]**

"So what could you build with this framework?

Let me give you some examples:

**ML Workflow Tools:**
- `train_model(config)` — kick off a training job on your infrastructure
- `get_experiment_results(run_id)` — fetch metrics from MLflow or Weights & Biases
- `deploy_model(model_id, env)` — push a model to production

Imagine: 'Hey agent, run the same experiment as last week but with learning rate 0.001.' It remembers what config you used last week because of memory, it kicks off the job, it monitors the results, it reports back.

**Data Engineering Tools:**
- `run_sql_query(query)` — query your data warehouse
- `check_pipeline_status(pipeline_id)` — Airflow or Prefect status
- `get_table_schema(table_name)` — inspect data structures

Imagine: 'Why did pipeline X fail at 3am?' The agent checks logs, checks the table, checks the DAG, and tells you 'column Y was missing.'

**Integration Tools:**
- `create_jira_ticket(title, description)` — project management
- `post_to_slack(channel, message)` — send notifications
- `fetch_arxiv_paper(arxiv_id)` — research papers

**Custom Domain Tools:**
Whatever your workflow needs. It's just a Python function plus a JSON schema.

The beautiful thing is: once you have the agent loop working, adding new capabilities is trivial. You write a Python function, you write a JSON schema describing it, you register it. The LLM figures out when to use it based on the description.

No training. No fine-tuning. Just good descriptions."

---

## 🎯 CONCLUSION (5 minutes)

### Key Takeaways

**[Show takeaways slide]**

"Alright, we're at time. Let me leave you with three key takeaways:

**1. Tool-use is simpler than you think.**

The mechanism is: LLMs output JSON, you execute functions, you feed results back. That's it. No magic. No complex orchestration frameworks needed. Just a loop and some JSON schemas.

If you want to build an AI agent, you don't need LangChain or AutoGPT (though they're great). You can do it yourself in a few hundred lines. And by doing it yourself, you understand exactly what's happening.

**2. Boring tech works.**

JSONL files. Markdown memory. Regex patterns for permissions. Grep for search.

None of that is sexy. But it's reliable. It's debuggable. It's simple.

When you're building v1 of something, resist the urge to overcomplicate. Use the simplest thing that works. You can always optimize later.

**3. AI makes exploration cheap.**

I built this in Python without knowing Python well. AI pair programming removed the language barrier.

If you've been curious about a new language or a new domain, try it with AI assistance. Build something real. Learn by doing.

The barrier to entry for new technologies has never been lower. Take advantage of that."

---

### Closing Reflection

**[Show closing quote or final slide]**

"One last thought.

Six months ago, I didn't know Python well enough to build this. But with Claude as a pair programmer, I learned by:

1. **Asking it to generate boilerplate** — get to working code fast
2. **Reading every line it wrote** — understand what's happening
3. **Breaking things and debugging together** — real learning happens here
4. **Gradually taking over more of the coding** — eventually you're driving

I'm not a Python expert now. But I shipped something that works. That's the power of AI-assisted learning.

So my question to you is: **What will you build next?**

You have an idea that's been sitting in the back of your mind. Maybe it's in a language you don't know well. Maybe it's a domain you're not familiar with.

Try it. Use AI to get past the initial hurdles. Learn by building.

That's it. Thank you."

---

## ❓ Q&A SECTION (15 minutes)

### Handling Questions

**[Take questions from audience]**

Here are detailed responses for the most likely questions:

---

**Q: Why not use LangChain or CrewAI or AutoGPT?**

"Great question! So those frameworks are powerful and well-designed. If you're building a production agent, you should absolutely consider them.

But this project is about understanding the primitives. Those frameworks abstract away the details. You call a high-level API and magic happens.

I wanted to see what's actually happening under the hood. And it turns out, it's surprisingly simple. 500 lines of core logic. Call the LLM, execute tools, feed results back, repeat.

Once you understand that loop, you can make informed decisions about whether you need a framework or not.

Also, dependency weight matters. LangChain pulls in dozens of dependencies. This project has 3 core dependencies. For personal projects or learning, less is more."

---

**Q: How do you handle rate limits from the LLM provider?**

"Right now? I don't. Portkey, which is the gateway I'm using, has built-in rate limiting and retry logic. So it handles some of this for me.

If I were deploying this for a team, I'd add exponential backoff in the agent loop. When you get a 429 rate limit error, you wait, then retry.

The nice thing about Portkey is it also supports fallbacks. If one provider is rate-limited, it can automatically route to a different provider. So you could have it try Anthropic first, fall back to OpenAI if needed.

But for a single-user agent, rate limits haven't been a problem. I'm not hitting the limits."

---

**Q: Security concerns with shell execution?**

"Absolutely valid concern. Giving an AI the ability to run arbitrary shell commands is dangerous.

The current implementation has basic pattern matching and human-in-the-loop approval for dangerous commands. That's enough for personal use.

For production, you'd want:

1. **Sandboxing** — run the agent in a Docker container or gVisor so it can't affect the host system
2. **Command whitelisting** — only allow specific commands, deny everything else by default
3. **Audit logging** — log every command execution with timestamps
4. **Timeout limits** — kill commands that run too long
5. **Output size limits** — prevent commands from generating gigabytes of output

You could also restrict the agent to read-only operations. No write, no delete, just read. That's safe and still useful for many use cases.

This is an ongoing area of research in AI safety. How do you give agents power without giving them too much power? There's no perfect solution yet."

---

**Q: How does memory search work? Is it using embeddings?**

"Right now? No. It's literal grep over markdown files.

Each memory is saved as a markdown file with a descriptive filename. When you search, we grep for your query across all files and return the matches.

Does this work? Surprisingly well for a few thousand facts. Grep is fast.

For real scale — millions of facts — you'd want embeddings and a vector database. Convert each memory to a vector using a model like OpenAI's text-embedding-3, store them in Chroma or Qdrant or Pinecone, and do semantic search.

But for prototyping and learning? Simple beats fancy. Grep gets you started immediately.

One of the lessons I learned building this is: don't optimize prematurely. Use the simplest thing that works, and only add complexity when you hit real limits."

---

**Q: Can this run offline with local models?**

"Good question. Right now, it calls external APIs — Anthropic or OpenAI via Portkey. That requires internet.

But the agent loop doesn't care what LLM you're using, as long as it speaks the OpenAI-compatible API.

So if you wanted to run this with local models:

1. Install Ollama (ollama.ai) — it's a tool for running local LLMs
2. Run a model like Llama 3, Mistral, or Mixtral
3. Point the agent at localhost instead of Portkey
4. Done

The catch is: local models are not as good at tool use as GPT-4 or Claude. They'll work, but they'll make more mistakes. They'll call the wrong tools or generate malformed JSON.

But it's doable. And for sensitive workflows where you can't send data to external APIs, local models are your only option.

I haven't tested this extensively with local models, but the architecture supports it."

---

**Q: Performance bottlenecks?**

"The biggest bottleneck is LLM latency. Each call to Claude or GPT takes 1-5 seconds depending on the response length.

In the agent loop, if the LLM needs to use 3 tools, that's 3 sequential API calls. That can take 10-15 seconds total.

Ways to improve this:

1. **Smaller models** — GPT-4o Mini or Claude Haiku are much faster than full-size models, and often good enough
2. **Prompt caching** — Anthropic supports this. If your system prompt is long, they cache it on their end and subsequent calls are faster
3. **Parallel tool calls** — some LLMs support calling multiple tools in parallel. You can execute them concurrently and save time
4. **Streaming responses** — instead of waiting for the full response, stream tokens as they're generated. Makes it feel faster even if it's not

For this project, I didn't optimize for speed. But if you were building a user-facing assistant, you'd want to think about latency.

One trick: for multi-tool calls, you can start showing intermediate results to the user while the agent is still working. 'I'm checking the logs...' 'Found the error...' That perceived progress makes the wait feel shorter."

---

**Q: Why Portkey over direct OpenAI or Anthropic?**

"Portkey is a gateway. It sits between your application and the LLM providers.

Why is that useful?

1. **Unified API** — You write code once. Switching from GPT-4 to Claude is just changing a model string. No code changes.

2. **Fallbacks** — If Anthropic is down, Portkey can automatically route to OpenAI. Your app keeps working.

3. **Observability** — Portkey logs every request with timing, cost, errors. You get a dashboard showing what your agent is doing.

4. **Rate limiting and retries** — Built-in retry logic, exponential backoff, rate limit handling.

5. **Cost control** — You can set budgets, get alerts when spending exceeds thresholds.

For prototypes, you might not need this. But for production, having a gateway between you and the providers is valuable. It gives you flexibility.

Portkey is one option. LiteLLM is another. OpenRouter is another. They all solve similar problems."

---

**Q: How would you add a new tool? Can you show us live?**

"Sure! Let me show you."

**[Switch to editor, open tools/registry.py or tools/__init__.py]**

"Let's say we want to add a tool to get the weather.

First, write the Python function:

```python
def get_weather(city: str) -> str:
    # In reality, you'd call an API
    # For demo purposes:
    return f"The weather in {city} is sunny and 72°F"
```

Second, write the JSON schema:

```python
weather_schema = {
    "name": "get_weather",
    "description": "Get the current weather for a city",
    "parameters": {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "City name"
            }
        },
        "required": ["city"]
    }
}
```

Third, register it:

```python
registry.register(
    name="get_weather",
    fn=get_weather,
    schema=weather_schema
)
```

That's it. Restart the agent, and now it can call `get_weather`.

**[If there's time, restart the REPL and test it]**

```
You: What's the weather in San Francisco?
```

**[Show the agent calling the new tool]**

See? It just works. The LLM saw the description 'Get the current weather for a city' and knew to use it.

This is the power of the tool registry pattern. Extensibility without modifying core code."

---

**[Continue taking questions until time is up]**

---

## 🙏 FINAL THANKS

"Alright, we're out of time. Thank you so much for your attention.

If you want to try this yourself, the code is on GitHub at [your-repo-link]. Fork it, break it, extend it. PRs are welcome.

If you have more questions, catch me after or send me an email at [your-email].

Thanks again. Have a great rest of your day!"

**[End of presentation]**
