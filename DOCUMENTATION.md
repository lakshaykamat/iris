# Iris (Ruchi) — Bot Documentation

Iris is a personal Telegram companion bot. It runs as "Ruchi" — a persona of a Delhi girlfriend who texts in Hinglish, remembers things you tell her, and reaches out on her own when she has something to say. The bot is powered by OpenAI and stores everything in a local SQLite database.

---

## Table of Contents

1. [High-Level Design (HLD)](#1-high-level-design)
2. [Components Overview](#2-components-overview)
3. [Workflow — Reactive (You Message Her)](#3-workflow--reactive)
4. [Workflow — Proactive (She Messages First)](#4-workflow--proactive)
5. [Nightly Reflection Loop](#5-nightly-reflection-loop)
6. [Database — What Gets Stored](#6-database)
7. [Memory System — How She Remembers](#7-memory-system)
8. [Tools — What She Can Do Mid-Reply](#8-tools)
9. [Dashboard](#9-dashboard)
10. [Configuration](#10-configuration)

---

## 1. High-Level Design

```
┌─────────────────────────────────────────────────────────┐
│                        iris bot                         │
│                                                         │
│   Telegram  ──►  Channel  ──►  Agent  ──►  OpenAI      │
│                              (core)                     │
│                                │                        │
│                         ┌──────┴──────┐                 │
│                         │   SQLite DB  │                 │
│                         │  (data/     │                 │
│                         │  agent.db)  │                 │
│                         └─────────────┘                 │
│                                                         │
│   Heartbeat ──► Scheduler ──► Agent (proactive turns)  │
│   Reflection Loop ──► OpenAI ──► DB (insights saved)   │
│   Dashboard (Flask, port 5050) ──► DB (read-only)      │
└─────────────────────────────────────────────────────────┘
```

**Three independent loops run at all times:**

| Loop | What it does |
|------|-------------|
| **Telegram polling** | Receives your messages, sends replies |
| **Heartbeat** | Wakes up at scheduled times, decides if she should text first |
| **Reflection** | Runs nightly at 3 AM, distills recent events into insights |

All three share one SQLite database and one async lock so they never step on each other.

---

## 2. Components Overview

| File / Folder | Role |
|---------------|------|
| `bot.py` | Entry point — starts everything |
| `channels/telegram.py` | Handles Telegram I/O (inbound messages, sending replies) |
| `agent/core.py` | The AI brain — calls OpenAI, runs tools, saves the reply |
| `agent/prompt.py` | Builds the system prompt (persona + current time + memory) |
| `agent/tools/` | Tools the AI can call mid-reply (remember, schedule, sticker, GIF) |
| `memory/store.py` | SQLite access layer — single source of truth |
| `memory/retrieval.py` | Picks which memories are relevant for the current turn |
| `memory/reflection.py` | Nightly summarization of events into insights |
| `scheduler.py` | Heartbeat loop + nightly reflection trigger |
| `dashboard.py` | Flask web dashboard (read-only view of the DB) |
| `config.py` | All env vars in one place |
| `persona.md` | Ruchi's character sheet (sent as the system prompt) |

---

## 3. Workflow — Reactive

This is what happens when **you send a message**.

```
You send a message on Telegram
         │
         ▼
  Telegram polling receives it
         │
         ▼
  Debouncer waits 3 seconds
  (collects any follow-up messages you send quickly)
         │
         ▼
  Agent.reply() is called
         │
         ├── 1. Saves your message to DB  (messages table)
         │
         ├── 2. Builds the system prompt:
         │       • persona.md  (who Ruchi is)
         │       • current time in your timezone
         │       • how long the conversation gap was
         │       • recalled memories relevant to your message
         │
         ├── 3. Loads last 30 messages from DB as conversation history
         │
         ├── 4. Calls OpenAI (gpt-5-mini by default)
         │
         ├── 5. If OpenAI wants to use a tool → runs the tool, feeds result back
         │       (loops up to 8 times)
         │
         └── 6. Gets the reply text
                  │
                  ├── Saves reply to DB  (messages table)
                  └── Sends it to Telegram as 1–3 message bubbles
                        (with a fake typing delay so it feels human)
```

**Key detail — the debouncer:** If you send "hey" then "wait actually" in quick succession, the bot waits 3 seconds and joins them into one turn: `"hey\nwait actually"`. This prevents double-replies for rapid typing.

**Key detail — bubbles:** The reply is split by newlines, capped at 3 bubbles. Each bubble gets a small typing indicator delay before sending, so it reads like a real person texting.

---

## 4. Workflow — Proactive

This is what happens when **she decides to text first**.

```
Heartbeat loop polls every 60 seconds
         │
         ▼
  Is there a pending check-in whose fire_at time has passed?
         │
         No → sleep again
         │
         Yes ▼
  Is this a user-requested reminder? (pinned = 1)
         │
         Yes → skip all checks, go straight to Agent
         │
         No ▼
  Was there a message from you in the last 5 minutes?
         │
         Yes → defer the check-in by 30 minutes (you're active, no need to interrupt)
         │
         No ▼
  Ask the gate model (gpt-5-nano, cheaper/faster):
  "Is now a good moment to reach out for this reason?"
         │
         No → mark check-in done, log "gate declined"
         │
         Yes ▼
  Agent.reach_out(reason)
         │
         ├── Builds system prompt with a proactive instruction:
         │     "You planned to text him for this reason: {reason}.
         │      Decide whether to send now or stay silent."
         │
         └── If she sends → message goes to Telegram + saved to DB
             If she stays silent → logged as "silent", no message sent

  After every check-in → ensure_upcoming_checkin()
  (always leaves at least one future check-in so she never goes permanently quiet)
```

**Who schedules check-ins?** Two sources:
1. The **agent herself** — during any turn she can call `schedule_next_checkin` to plan a follow-up ("ask how your interview went in 8 hours")
2. The **safety floor** — if nothing is scheduled within `MAX_SILENCE_HOURS` (default 24h), the heartbeat seeds one automatically

---

## 5. Nightly Reflection Loop

Runs every night at **3 AM** (in your timezone).

```
Collect all 'event' memories since the last reflection
         │
         Less than 5 events? → skip
         │
         5+ events ▼
  Send to OpenAI:
  "You are reviewing recent memories. Distil up to 3 higher-level insights.
   Return as a JSON array."
         │
         ▼
  Save insights as 'reflection' memories (importance = 7)
```

Example: if the events this week were "he seemed tired", "he mentioned a stressful project", "he said he hasn't been sleeping well" — the reflection might produce: *"He's been under work pressure this week and not sleeping enough."*

This reflection then gets recalled in future turns, giving the bot pattern-awareness rather than just per-message awareness.

---

## 6. Database

Single SQLite file at `data/agent.db`. Six tables:

### `messages`
Every message in the conversation, in order.

| Column | What it holds |
|--------|--------------|
| `id` | Auto-increment primary key |
| `role` | `"user"` or `"assistant"` |
| `content` | The text |
| `kind` | `"text"`, `"sticker"`, or `"gif"` |
| `ts` | UTC timestamp |

Used for: conversation history fed to OpenAI (last 30 messages), gap detection, dashboard chat view.

### `facts`
Durable truths that should persist indefinitely — names, preferences, ongoing situations.

| Column | What it holds |
|--------|--------------|
| `id` | Auto-increment |
| `text` | The fact ("His name is Lakshay") |
| `source` | `"agent"` (she wrote it) |
| `created_at` | When it was first saved |
| `superseded_by` | Points to a newer fact if this one was corrected |

Facts are never deleted. When a fact changes, the old row gets `superseded_by` set to the new row's ID. Only facts with `superseded_by = NULL` are shown as "active facts".

### `memories`
Episodic moments + nightly reflections, with importance scores.

| Column | What it holds |
|--------|--------------|
| `id` | Auto-increment |
| `text` | What happened / the insight |
| `kind` | `"event"` or `"reflection"` |
| `importance` | 1–10 (agent decides) |
| `ts` | When it was created |
| `last_recalled` | When it was last surfaced in a prompt |

### `schedule`
The planned check-ins that drive proactive messaging.

| Column | What it holds |
|--------|--------------|
| `fire_at` | UTC datetime when to wake up |
| `reason` | Why she planned to reach out |
| `status` | `"pending"` or `"done"` |
| `pinned` | `1` = user-requested reminder (always fires), `0` = regular check-in (can be skipped) |

### `decisions`
Audit trail of every proactive decision.

| Column | What it holds |
|--------|--------------|
| `action` | `"sent"`, `"silent"`, or `"deferred"` |
| `reason` | Why |

### `token_usage`
Every OpenAI API call logged for cost visibility.

| Column | What it holds |
|--------|--------------|
| `model` | Which model was used |
| `prompt_tokens` | Total input tokens |
| `cached_tokens` | How many were served from cache (cheaper) |
| `completion_tokens` | Output tokens |
| `trigger` | `"reply"` (reactive) or `"proactive"` |

---

## 7. Memory System

Memory is how she remembers what you told her across conversations. It works in three layers:

### Layer 1 — Facts (permanent)
Written via the `remember_fact` tool when something durable is worth keeping: your name, your friend's names, your preferences, ongoing situations. Every active fact is included in **every** system prompt, no matter what you're talking about.

### Layer 2 — Events (episodic)
Written via the `remember_event` tool for moments worth carrying — news you shared, how a day went, how you felt. Each event gets an importance score (1–10) chosen by the agent.

### Layer 3 — Reflections (synthesized insights)
Written nightly by the reflection loop. Not raw events but patterns: "He's been stressed about work this week." Stored at importance 7.

### How Retrieval Works (per turn)

When building the system prompt for a turn, the bot runs this:

```
1. Load ALL active facts  →  always included
2. Score ALL memories:
     score = recency_weight × (1 / (1 + age_in_days))
           + importance_weight × (importance / 10)
           + relevance_weight × (keyword_overlap with your message)
3. Take top 8 memories by score
4. Mark them as "recalled now" (bumps last_recalled)
5. Render into the prompt:

   Facts you know:
   - [#1] His name is Lakshay
   - [#2] He works in software

   Things you remember:
   - He had a big interview on Thursday
   - He seemed tired last week
```

**Relevance** is keyword-based (no embeddings): words in your current message are matched against memory text, stopwords removed. A memory about "interview" scores higher when you mention "interview".

---

## 8. Tools

The agent can call these mid-turn (before producing her reply). Each tool call loops back into OpenAI with the result.

| Tool | What it does |
|------|-------------|
| `remember_fact` | Saves a durable fact. Pass `supersedes: id` to correct an old one. |
| `remember_event` | Saves an episodic moment with an importance score. |
| `schedule_next_checkin` | Plans a future proactive check-in (0.25h to 336h from now). |
| `set_reminder` | Like schedule, but pinned — bypasses all gate checks. Used for explicit "remind me" requests. |
| `send_sticker` | Queues a Telegram sticker by mood (e.g. `"happy"`, `"love"`). |
| `send_gif` | Queues a GIF search (via Tenor or Giphy). |

Tools are registered in `agent/tools/`. Media tools are only registered if the sticker library or GIF API key exists.

---

## 9. Dashboard

A read-only Flask web UI at `http://localhost:5050` (or your server's IP + port 5050).

Runs as a background daemon thread inside the same process as the bot.

**What you can see:**
- Total message / memory / fact counts
- Recent reflections
- Full conversation history
- All memories (events + reflections)
- Active facts
- Proactive decision log (sent / silent / deferred)
- Scheduled check-ins
- Token usage totals, per-model breakdown, recent calls

The dashboard opens its own read-only SQLite connection (separate from the bot's write connection) with a threading lock to handle Flask's worker threads.

---

## 10. Configuration

All config lives in `.env` (copy from `.env.example`).

| Variable | Default | What it controls |
|----------|---------|-----------------|
| `TELEGRAM_TOKEN` | required | Your bot token from BotFather |
| `OWNER_CHAT_ID` | required | Your Telegram user ID (only chat she responds to) |
| `OPENAI_API_KEY` | required | OpenAI key |
| `MODEL` | `gpt-5-mini` | Main model for replies and reflection |
| `GATE_MODEL` | `gpt-5-nano` | Cheap model for the "should I text now?" gate check |
| `OWNER_TZ` | `Asia/Kolkata` | Your timezone (for time context in prompt + reflection hour) |
| `MAX_SILENCE_HOURS` | `24` | Safety floor — she'll never go quiet longer than this |
| `HISTORY_WINDOW` | `30` | How many past messages to include in each turn |
| `DEBOUNCE_SECONDS` | `3` | How long to wait before flushing rapid messages into one turn |
| `PRESENCE_WINDOW_MIN` | `5` | Minutes of recent activity that counts as "you're active" |
| `REFLECTION_HOUR` | `3` | Hour (local time) when nightly reflection runs |
| `GIF_PROVIDER` | `tenor` | `tenor` or `giphy` |
| `GIF_API_KEY` | empty | API key for GIF search (optional) |

---

## How It All Fits Together — One-Page Summary

```
bot.py starts
  │
  ├── Store(agent.db) opened
  ├── Dashboard thread started  (Flask, port 5050)
  ├── Telegram app built        (channels/telegram.py)
  ├── Agent created             (agent/core.py)
  │     └── Tools registered: remember_fact, remember_event,
  │                           schedule_next_checkin, set_reminder,
  │                           send_sticker, send_gif
  │
  ├── Heartbeat coroutine launched  (scheduler.py)
  │     └── every 60s: check schedule → decide → maybe send
  │
  └── Reflection coroutine launched
        └── nightly at 3 AM: summarize events → save insights

  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─

  Per turn (reactive):
    message in
      → debounce
      → build prompt (persona + time + recalled memory)
      → load history (last 30 messages)
      → call OpenAI
      → maybe call tools (up to 8 rounds)
      → send reply as bubbles
      → save to DB

  Per check-in (proactive):
    heartbeat fires
      → presence check
      → gate model check (skipped for reminders)
      → agent decides to send or stay silent
      → send or log silence
      → schedule next check-in
```
