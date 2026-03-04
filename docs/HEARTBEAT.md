# Heartbeat Scheduler — Explained

> **File:** `src/openclaw/heartbeat/scheduler.py`

## The Big Picture

Heartbeats are **scheduled tasks that run without human input**. Think cron jobs, but instead of running a shell script, they run the AI agent with a pre-defined prompt.

Example use cases:
- "Every morning at 7:30, tell me what's on my agenda"
- "Every day at 18:00, compile a digest of unreviewed merge requests"
- "Every Monday at 9:00, summarize last week's activity"

```
┌─────────────────────────────────────────────────┐
│  Background Thread (daemon)                      │
│                                                   │
│  while True:                                      │
│    check: is it time for any heartbeat?           │
│    if yes → run the agent with the heartbeat's    │
│             prompt → send result to owner          │
│    sleep 30 seconds                               │
│    repeat                                         │
│                                                   │
└─────────────────────────────────────────────────┘
```

---

## Key Components

### 1. `Heartbeat` Dataclass

```python
@dataclass(frozen=True)
class Heartbeat:
    name: str            # unique ID, e.g. "morning-briefing"
    schedule_expr: str   # e.g. "every day at 07:30"
    prompt: str          # e.g. "Good morning! What's on my agenda?"
    agent: str = "main"  # which agent handles it (default: Jarvis)
```

`frozen=True` means once created, you can't change its fields. It's immutable — like a constant.

### 2. `HeartbeatScheduler` Class

The manager that holds all heartbeats, runs a background thread, and fires them on schedule.

### 3. `_parse_schedule()` Function

Translates human-readable strings into `schedule` library jobs:

| Expression | What it does |
|---|---|
| `"every 5 minutes"` | Fires every 5 minutes |
| `"every 1 hour"` | Fires every hour |
| `"every day at 07:30"` | Fires daily at 7:30 AM |
| `"every monday at 09:00"` | Fires every Monday at 9 AM |
| `"every 30 seconds"` | Fires every 30 seconds (for testing) |

---

## How It Works — Step by Step

### Step 1: Create the Scheduler

```python
scheduler = HeartbeatScheduler(
    run_fn=my_agent_runner,     # function that runs the agent
    on_result=my_result_handler, # function called with the agent's response
)
```

- **`run_fn`**: A function with signature `(agent_name, session_key, prompt) → response`. This is what actually calls the LLM.
- **`on_result`**: Called after each heartbeat completes. Used to send the result somewhere (Telegram DM, Slack DM, terminal print, etc.)

### Step 2: Register Heartbeats

```python
scheduler.add(Heartbeat(
    name="morning-briefing",
    schedule_expr="every day at 07:30",
    prompt="Good morning! What's on my agenda today?",
    agent="main",
))
```

Inside `add()`:

```python
def add(self, heartbeat: Heartbeat) -> bool:
    job = _parse_schedule(self._scheduler, heartbeat.schedule_expr)  # parse the expression
    if job is None:
        return False        # invalid expression

    job.do(self._fire, heartbeat)                    # tell schedule: when it's time, call _fire()
    self._heartbeats[heartbeat.name] = heartbeat     # store it
    return True
```

`job.do(self._fire, heartbeat)` registers `_fire` as the callback. When the schedule triggers, it calls `self._fire(heartbeat)`.

### Step 3: Start the Background Thread

```python
scheduler.start(check_interval=30)
```

This spawns a **daemon thread** that runs forever:

```python
def _loop():
    while not self._stop_event.is_set():
        self._scheduler.run_pending()         # check: any heartbeats due?
        self._stop_event.wait(timeout=30)      # sleep 30 seconds (or until stop)
```

- **`self._scheduler.run_pending()`** — asks the `schedule` library: "is any job overdue?" If yes, it calls the registered callback (`_fire`).
- **`self._stop_event.wait(timeout=30)`** — sleeps for 30 seconds, but can be woken up early if `stop()` is called.
- **Daemon thread** — automatically killed when the main program exits. No cleanup needed.

### Step 4: When a Heartbeat Fires

```python
def _fire(self, heartbeat: Heartbeat) -> None:
    session_key = f"cron:{heartbeat.name}"    # e.g. "cron:morning-briefing"
    try:
        response = self._run_fn(heartbeat.agent, session_key, heartbeat.prompt)
        if self._on_result:
            self._on_result(heartbeat.name, response)
    except Exception:
        logger.exception("Heartbeat '%s' failed", heartbeat.name)
```

Key detail: **each heartbeat gets its own session key** (`cron:<name>`). This means:
- Heartbeat conversations don't mix with interactive user conversations
- Each heartbeat has its own conversation history
- The agent can reference previous heartbeat results (e.g. "yesterday I told you about 3 MRs")

### Step 5: Stop

```python
scheduler.stop()
```

Sets the stop event → the background thread wakes up from `wait()` → sees the event is set → exits the loop → thread joins.

---

## How Heartbeats Are Defined

Heartbeats come from `config.json` (loaded via `AppConfig`):

```json
{
  "heartbeats": [
    {
      "name": "morning-briefing",
      "schedule": "every day at 07:30",
      "prompt": "Good morning! Summarize any pending tasks.",
      "agent": "main"
    },
    {
      "name": "daily-mr-digest",
      "schedule": "every day at 18:00",
      "prompt": "Compile a digest of merge requests.",
      "agent": "main"
    }
  ]
}
```

In `main.py`, each channel loads these and registers them:

```python
for hb_def in config.heartbeats:
    heartbeat_scheduler.add(Heartbeat(
        name=hb_def.name,
        schedule_expr=hb_def.schedule,
        prompt=hb_def.prompt,
        agent=hb_def.agent,
    ))
```

---

## Channel-Specific Behavior

### Telegram

Heartbeats can't start immediately because we don't know the owner's chat ID yet. They wait for the first user message:

```python
_owner_chat_id: list[int] = []  # empty until someone messages the bot

def set_owner_chat_id(chat_id: int) -> None:
    if not _owner_chat_id:
        _owner_chat_id.append(chat_id)
        heartbeat_scheduler.start()  # NOW we know where to send results
```

Results are sent via raw Telegram Bot API (`urllib.request`) since the heartbeat runs outside the `python-telegram-bot` event loop.

### Slack

Heartbeats start immediately (the owner ID is known from `SLACK_OWNER_ID` env var). Results are delivered as DMs via `channel.send_dm()`.

The Slack channel has a special optimization for the MR digest heartbeat — it skips the LLM entirely and calls `compile_mr_digest()` directly:

```python
def _heartbeat_run_fn(agent_name, session_key, prompt):
    if "daily-mr-digest" in session_key:
        return channel.compile_mr_digest(...)  # direct scan, no LLM
    return router.run(...)                      # normal agent call
```

### REPL

No heartbeat support in the REPL — it's interactive only.

---

## The `_parse_schedule()` Parser

Translates human strings into `schedule` library calls:

```python
"every day at 07:30"
  → rest = "day at 07:30"
  → rest.startswith("day at ") → True
  → scheduler.every().day.at("07:30")

"every monday at 09:00"
  → rest = "monday at 09:00"
  → matches weekday map → scheduler.every().monday.at("09:00")

"every 5 minutes"
  → rest = "5 minutes"
  → parts = ["5", "minutes"]
  → interval = 5, unit = "minute" → scheduler.every(5).minutes
```

Returns `None` for invalid expressions, which causes `add()` to return `False`.

---

## Properties

```python
scheduler.heartbeats   # → ["morning-briefing", "daily-mr-digest"]
scheduler.is_running   # → True/False
```

Used in startup banners:

```python
if hb_names:
    print(f"  Heartbeats: {', '.join(hb_names)}")
else:
    print("  Heartbeats: none (add to config.json to enable)")
```

---

## Threading Model

```
Main Thread                    Heartbeat Thread (daemon)
    │                                │
    │  start()──────────────────────►│
    │                                │  loop:
    │  (running Telegram/Slack       │    run_pending()
    │   polling / WebSocket)         │    sleep 30s
    │                                │    run_pending()
    │                                │    sleep 30s
    │                                │    ← heartbeat fires! →
    │                                │      _fire() → run_fn() → LLM call
    │                                │      on_result() → send DM
    │                                │    sleep 30s
    │                                │    ...
    │  stop()───────────────────────►│  ← stop_event set
    │                                │  exits loop
    │  thread.join()                 │
    ▼                                ▼
```

The heartbeat thread runs **completely independently** of the main channel loop. They don't block each other.
