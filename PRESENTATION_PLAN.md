# Presentation Plan: Mini OpenClaw
## Building a Lightweight AI Assistant Framework

**Duration:** 45 minutes + 15 minutes Q&A  
**Audience:** Data Scientists, ML Enthusiasts, Python Programmers  
**Speaker Background:** JavaScript Developer exploring Python/AI

---

## 📋 Presentation Structure

### **Section 1: Introduction & Context** (5 minutes)

#### Slide 1: Who Am I & Why This Project?
- Brief intro: "JS developer curious about AI agents"
- **Honesty hook:** "Built with AI assistance — let's talk about that"
- What you'll see:
  - A working AI agent system from scratch
  - How LLM tool-use actually works under the hood
  - Real architecture decisions and tradeoffs

#### Slide 2: What This Is
- **Mini OpenClaw:** A self-hosted AI assistant with:
  - Multi-channel support (Slack, Telegram, REPL, HTTP)
  - Persistent memory across sessions
  - Tool execution with permission gating
  - Scheduled autonomous tasks (heartbeats)
  - ~500 lines of core logic
- **Not a framework comparison** — this is about understanding primitives

#### Slide 3: Wh— how the pieces fit together
2. Tool-use patterns — making LLMs actually do things
3. Memory & session management — keeping context
4. Permission gating — safety without lockdown
5. Live demo — watch it run
6. Code walkthrough — see how it's implemented
7. Lessons learned — JS → Python with AI assist
6. Lessons learned (JS → Python journey)

---

### **Section 2: Architecture Deep Dive** (12 minutes)

#### Slide 4: System Architecture Diagram
```
┌─────────────────────────────────────────────────────┐
│     Channels (Telegram/Slack/REPL/HTTP)             │
└────────────────┬────────────────────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────────────────┐
│            AgentRouter (Multi-agent)               │
│         Routes /research, /admin, etc.             │
└────────────────┬───────────────────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────────────────┐
│              Agent Loop (Core)                     │
│    ┌──────────────────────────────────┐            │
│    │  LLM (Claude/GPT via Portkey)    │            │
│    └───────────┬──────────────────────┘            │
│                │                                    │
│    ┌───────────▼──────────────────────┐            │
│    │  Tool Execution & Results        │            │
│    │  • Shell commands                 │            │
│    │  • File operations                │            │
│    │  • Web search                     │            │
│    │  • Memory (save/search)           │            │
│    │  • GitLab MR fetching             │            │
│    └──────────────────────────────────┘            │
└───────┬────────────────────────────────────────────┘
        │
┌───────▼────────────────────────────────────────────┐
│   SessionStore (JSONL + Auto-compaction)           │
│   PermissionManager (Approve dangerous ops)        │
│   HeartbeatScheduler (Cron-like tasks)             │
└────────────────────────────────────────────────────┘
```

**Key Talking Points:**
- **Separation of concerns:** Channels ≠ Agent logic
- **Composability:** Same agent, multiple frontends
- **Observability:** JSONL logs = easy debugging
ool Use — The Core Mechanic
**How it works:**
```python
# What the LLM sees:
tools = [
    {
        "name": "run_shell",
        "description": "Execute a shell command",
        "parameters": {
            "command": {"type": "string", "description": "Shell command to run"}
        }
    }
]

# What it generates:
# "I'll check the disk space"
# → tool_call(name="run_shell", args={"command": "df -h"})
```

**The Pattern:**
- LLM outputs structured JSON tool calls
- We execute them in our runtime
- Feed results back to LLM
- Repeat until done
- This is how ChatGPT, Claude, and all modern agents work
- LLM becomes the orchestration layer

#### Slide 6: Memory System — Simple but Effective
**Architecture:**
```
~/.mini-openclaw/
├── sessions/          # Conversation history (JSONL)
│   ├── agent_main_user_12345.jsonl
│   └── agent_main_user_67890.jsonl
└── memory/            # Long-term facts (Markdown)
    ├── project_X_details.md
    └── user_preferences.md
```

**Demo the compaction algorithm:**
- Token estimation using tiktoken
- Auto-summarization when > 100K tokens
- Preserves recent messages, summarizes old ones
Key Insight:** "Good enough" beats "perfect" — markdown + grep works for thousands of facts
**Audience Hook:** "Think of this as a simple vector DB alternative for prototypes"

#### Slide 7: Permission Management
**Code Walkthrough:**
```python
# In permissions/manager.py
def check_permission(self, command: str) -> bool:
    dangerous_patterns = [
        r'\brm\b', r'\bmv\b', r'\bsudo\b', 
        r'\bcurl.*\|.*sh\b'  # Pipe to shell
    ]
    
    if any(re.search(pat, command) for pat in dangerous_patterns):
        # Prompt operator in terminal
        return self._prompt_human(command)
    return True  # Auto-approve safe commands
```

**The Tradeoff:**
- Too strict → agent is useless
- Too loose → agent is dangerous
- Solution: Pattern matching + human-in-the-loop for risky commands
- Read operations auto-pass, destructive operations need approval

---

### **Section 3: Live Demo** (10 minutes)

#### Demo 1: REPL Mode (5 minutes)
**Show on terminal:**
```bash
$ uv run openclaw repl
You: Tell me about this project
Agent: [Reads README.md using file tool, summarizes]

You: Save a memory: My favorite ML library is scikit-learn
Agent: [Calls save_memory tool]

You: What did I just tell you?
Agent: [Calls memory_search, retrieves the fact]

You: Run 'ls -la' and tell me the largest file
Agent: [Calls run_shell, analyzes output]
```

**Highlight:**
- Live tool execution
- Memory persistence
- Natural language → structured actions

#### Demo 2: Heartbeat Scheduler (3 minutes)
**Show config.json:**
```json
{
  "heartbeats": [
    {
      "name": "daily-summary",
      "schedule": "every day at 9:00",
      "prompt": "Check recent memory entries and summarize key facts from yesterday"
    }
  ]
}
```

**Show logs/output:**
- Background thread executing on schedule
- Agent generates content autonomously
- Sent to configured channel (Telegram/Slack)

#### Demo 3: Multi-Channel (2 minutes)
**Quick switch between:**
- REPL → Same conversation
- Telegram → Same conversation continues
- Show session file: `cat ~/.mini-openclaw/sessions/agent_main_user_*.jsonl`

---

### **Section 4: Code Deep Dive** (10 minutes)

#### Focus Area 1: The Agent Loop
**Open `agent/loop.py` and walk through:**
```python
def run_agent_turn(client, model, system_prompt, session_key, 
                   user_text, session_store, tool_registry, 
                   permission_manager, max_iterations=15):
    
    # 1. Load session history
    messages = session_store.load(session_key)
    messages.append({"role": "user", "content": user_text})
    
    # 2. Check if compaction needed
    if estimate_tokens(messages) > 100_000:
        messages = compact(messages, client, model)
    
    # 3. LLM loop: call → tools → call → ...
    for iteration in range(max_iterations):
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt}] + messages,
            tools=tool_registry.get_schemas()
        )
        
        # If done, break
        if not response.tool_calls:
            break
            
        # Execute tools with permission checks
        for tool_call in response.tool_calls:
            result = tool_registry.execute(
                tool_call.name, 
                tool_call.arguments,
                permission_manager
            )
            messages.append(tool_result_message(result))
    
    # 4. Persist session
    session_store.append_all(session_key, new_messages)
```

**Key Insights for Audience:**
- Stateless LLM → we manage state
- Tool loop pattern (common in agent frameworks)
- Compaction = cost optimization

#### Focus Area 2: JSONL Session Store
**Why JSONL over SQLite/Postgres?**
- Append-only = crash-safe
- Human-readable for debugging
- Simple: no DB setup
- Scales to ~10K messages/session

**Code snippet from `session/store.py`:**
```python
def append(self, session_key: str, message: dict) -> None:
    path = self._path(session_key)
    with open(path, "a") as f:
        f.write(json.dumps(message) + "\n")

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

#### Focus Area 3: Tool Registry Pattern
**Open `tools/registry.py`:**
```python
class ToolRegistry:
    def __init__(self):
        self._tools = {}
    
    def register(self, name: str, fn: Callable, schema: dict):
        self._tools[name] = {"fn": fn, "schema": schema}
    
    def get_schemas(self) -> list[dict]:
        return [tool["schema"] for tool in self._tools.values()]
    
    def execute(self, name: str, args: dict, permission_mgr) -> str:
        if name == "run_shell":
            if not permission_mgr.check_permission(args["command"]):
                return "Permission denied"
        
        result = self._tools[name]["fn"](**args)
        return str(result)
```
The Power of This Pattern:**
- Add tools without touching agent loop
- LLM learns from tool descriptions
- No training required — just good descriptionsd)`
  - `trigger_airflow_dag(dag_id)`

---

### **Section 5: Python Lessons (JS Developer POV)** (5 minutes)

#### What Surprised Me About Python

**Slide with Comparisons:**

| Concept | JavaScript | Python | My Take |
|---------|-----------|--------|---------|
| **Dependency Management** | npm/yarn/pnpm | pip/poetry/uv | `uv` is blazing fast! |
| **Type Hints** | TypeScript (separate lang) | Native in Python 3.12+ | Less friction, loved it |
| **Async** | Promises/async-await | asyncio + sync mix | More manual, but powerful |
| **Error Handling** | Try-catch | Try-except | Same concept, different keywords |
| **Testing** | Jest | pytest | pytest fixtures >> Jest setup |
| **Packaging** | CommonJS/ESM hell | `pyproject.toml` | Simpler (when using uv) |

**Candid Moments:**
- "I still forget colons after `if` statements"
- "Understanding `__init__.py` took me a day"
- "Python's simplicity for scripting is unmatched"
- "AI (Claude) wrote ~60% of the code — I learned by reading/debugging"

#### How AI Assisted This Project
- Generated initial boilerplate (typed code correctly!)
- Explained Python idioms (comprehensions, context managers)
- Debugged async issues (I gave up, Claude fixed it)
- **Key Point:** "AI makes language-switching less scary"

---
Real-World Extensions** (3 minutes)

#### What You Could Build With This
**Examples of tools you could add:**

1. **ML Workflow Tools**
   - `train_model(config)` — kick off training jobs
   - `get_experiment_results(run_id)` — fetch from MLflow/W&B
   - `deploy_model(model_id, env)` — push to production

2. **Data Engineering Tools**
   - `run_sql_query(query)` — query your data warehouse
   - `check_pipeline_status(pipeline_id)` — Airflow/Prefect status
   - `get_table_schema(table_name)` — inspect data structures

3. **Integration Tools**
   - `create_jira_ticket(title, description)` — project management
   - `post_to_slack(channel, message)` — notifications
   - `fetch_arxiv_paper(arxiv_id)` — research papers

4. **Custom Domain Tools**
   - Whatever your workflow needs — it's just a Python function + JSON schema
   - The LLM figures out when to call each tool
   - Chat: "Review MR #123 and check for data leakage"

---

## 🎤 Delivery Notes

### Preparation Checklist
- [ ] Test all demos in REPL mode beforehand
- [ ] Prepare terminal with large font (audience visibility)
- [ ] Have backup screenshots if live demo fails
- [ ] Verify `.env` file doesn't leak on screenshare
- [ ] Test timing: Run through once, aim for 42 minutes (buffer)

### Speaking Tips
1. **Start with vulnerability:** "I'm a JS dev, Python is new — here's what I learned"
2. **Engage early:** Ask audience questions in first 5 mins
3. **Slow down during code:** Line-by-line for key snippets
4. **Use analogies:** "JSONL is like a git log — append-only, rewindable"
5. **Pause for questions:** After architecture, after demo, at end

### Handling Q&A (15 minutes)

**Anticipated Questions & Answers:**

**Q: Why not use LangChain/CrewAI/AutoGPT?**  
A: "Those are great! This is a learning project — wanted to understand the primitives. Also, 500 lines of code vs 5000 lines of dependencies."

**Q: How do you handle rate limits?**  
A: "Not implemented yet — Portkey has built-in rate limiting. For prod, I'd add exponential backoff in the agent loop."

**Q: Security concerns with shell execution?**  
A: "Absolutely valid. Permission manager is basic. For prod, I'd use sandboxing (Docker, gVisor) or restrict to read-only commands."

**Q:Great question! This is about understanding the primitives. Those frameworks are powerful but abstract away the details. I wanted to see what's actually happening — and it's surprisingly simple. 500 lines of core logic vs thousands of
A: "Simple grep! For scale, I'd use embeddings + vector DB (Chroma, Pinecone). This is a prototype."

**Q: Can this run offline?**  
A: "LLM calls need internet. But with Ollama + OpenAI-compatible API, could run local models (llama3, mistral)."

**Q: Performance bottlenecks?**  
A: "LLM latency dominates. For speed: smaller models, prompt caching (Anthropic supports it), parallel tool calls."

**Q:Right now? Literal grep over markdown files. Works surprisingly well for a few thousand facts. For real scale you'd want embeddings + vector DB (Chroma, Qdrant, etc.). But for prototyping and learning, simple beats fancy
A: "Portkey = unified gateway. Switch providers without code changes. Also has built-in logging, fallbacks, load balancing."

**Q: How to add a new tool?**  
A: [Open `tools/registry.py`] "Literally 10 lines: define function, write JSON schema, call `registry.register()`. Demo this live if time!"

---

## 📊 Slide Deck Outline (Suggested Tools)

### Recommended Setup
- **Slides:** Keynote/PowerPoint (visual diagrams)
- **Code:** VS Code with large font, dark theme
- **Terminal:** iTerm2 / Terminal.app, font size 18+
- **Timer:** Visible countdown (45 min)

### Slide Count Estimate
- Title + Intro: 3 slides
- Architecture: 4 slides
- Demo Prep: 2 slides (instructions for audience)
- Code Deep Dive: 3 slides (headings only, code on screen)
- Python Lessons: 2 slides
- Use Cases: 1 slide
- Conclusion + Contacts: 1 slide

**Total:** ~16 slides (heavy on live coding/terminal)

---

## 🎯 Key Takeaways for Audience

**End with these 3 points:**

1. **Tool-use is the game changer**  
   "LLMs + structured function calls = AI that *does* things, not just talks"

2. **Simplicity scales better than complexity**  
   "JSONL, markdown memory, permission prompts — boring tech, but it works"

3. **Cross-language learning is easier than ever**  
   "AI assistants lower the barrier — try that framework in a new language!"
simpler than you think**  
   "LLMs + JSON schemas + function calls = agents that actually do things. No magic."

2. **Boring tech works**  
   "JSONL files, markdown, regex patterns — unsexy but reliable. Don't overcomplicate v1."

3. **AI makes exploration cheap**  
   "Built this in Python without knowing Python well. AI pair programming removes language barriers. Try that new framework.
- Create a Slack/Discord channel for questions?

### Gather Feedback
- Anonymous form: "What use case would you build?"
- Feature requests issue template on GitHub

---

## 🚀 Bonus: If Time Permits

### Advanced Topics (Pick 1-2 if ahead of schedule)

1. **Multi-Agent Routing Deep Dive**
   - Show `agent/router.py`
   - Explain prefix routing (`/research`, `/admin`)
   - Use case: Specialized agents per task

2. **Session Compaction Algorithm**
   - Walk through `session/compaction.py`
   - Token estimation with tiktoken
   - Summarization prompt engineering

3. **Slack MR Digest Feature**
   - Monitors channels for GitLab links
   - Fetches MR details via API
   - Sends digests to MR owner
   - Real-world productivity hack

---

## 🎓 Meta-Learning Moment

**Close with this reflection:**

> "Six months ago, I didn't know Python well enough to build this. But with Claude as a pair programmer, I learned by:
> 1. Asking it to generate boilerplate
> 2. Reading every line it wrote
> 3. Breaking things and debugging together
> 4. Gradually taking over more of the coding
> 
> I'm not a Python expert now — but I shipped something real. That's the power of AI-assisted learning.
> 
> What will you build next?"

---

## 📞 Contact & Resources

**Include in final slide:**
- GitHub: [repo-url]
- Email: [your-email]
- Twitter/LinkedIn: [handles]
- Resources:
  - Anthropic Tool Use Docs: anthropic.com/docs/agents
  - Portkey Gateway: portkey.ai
  - Python async guide: (share favorite resource)

---

**Good luck with your presentation! 🎉**
