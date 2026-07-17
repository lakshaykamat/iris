# iris — Autonomous Telegram Companion (Persona Clone)

A personal, always-on AI agent that lives in Telegram and embodies a specific persona
(a clone of a real person). It chats when you message it **and initiates conversations
on its own** — reaching out *because it remembers*. Built as a real agentic loop
(LLM + tools) with a layered, human-like memory system so the persona feels continuous
over time.

## What "autonomous" means here (and why no framework is needed)

Autonomy is **architectural, not a framework feature**. No agent framework gives you
"text me on my own at 8pm" — you write that yourself regardless. It comes from three
things we own in plain Python:

1. A process that never exits (runs forever on the VPS).
2. A background `asyncio` heartbeat that fires with no input from the user.
3. The agent choosing its own next action (self-scheduling), driven by memory.

```python
async def heartbeat(agent, store):
    while True:
        nxt = store.next_pending_checkin()          # when did she plan to reach out?
        await asyncio.sleep(seconds_until(nxt))      # wait on her own timer
        await agent.run(proactive_trigger(nxt.reason))  # she texts you — unprompted
```

A framework only orchestrates the reasoning step; this loop *is* the autonomy — which is
exactly why the raw SDK wins (the autonomous behavior is custom code either way).

---

## 1. Goals & non-goals

**Goals**
- Persona fidelity: talks, remembers, and reacts like a specific real person (a clone).
- Reactive chat: you message it, it replies in character with memory of your history.
- Proactive: it reaches out on its own — *because it remembers* an open thread.
- Layered, human-like memory (persona + facts + episodic stream + reflection).
- Agentic core with a clean tool interface, so new tools drop in without core changes.
- Persists across restarts; runs 24/7 on a small VPS.

**Non-goals (for now — YAGNI)**
- No multi-user support. Single owner (you).
- No web UI. Telegram is the entire interface.
- No multi-agent orchestration.
- Vector/embedding recall deferred until the memory stream grows large (start simpler).

**A note on the persona:** this clones a real person, so it uses your private chat data
and models someone you know. Everything stays local to your VPS/SQLite — no third party
but the Claude API (which processes messages to generate replies). Treat the persona as a
loving tribute/companion, not a replacement for the real relationship.

---

## 2. Framework decision — why raw SDK, not an agent framework

The hard part of this project is **not** the agent loop — that's ~30 lines with the
Anthropic SDK. The real complexity is the **autonomy**: a self-scheduling heartbeat,
persistence, and running Telegram polling + a scheduler concurrently without corrupting
state. **No framework solves that for you** — you build it yourself regardless. A
framework would add dependency weight and hidden abstraction without removing any of the
actual work.

| Framework | Built for | Verdict |
|---|---|---|
| LangChain / LangGraph | Complex chains, stateful graphs | Overkill; heavy, churny API. Would fight it to get a self-scheduling Telegram loop |
| CrewAI | Multiple collaborating agents | Nothing to orchestrate — one agent |
| AutoGen | Multi-agent conversations | Multi-agent tool for a single-agent problem |
| Claude Agent SDK | Coding-agent harness (MCP, Claude Code lineage) | Closest fit but opinionated toward tool/file workflows; more than a chat companion needs |
| PydanticAI | Lightweight typed single-agent | The one worth considering; clean fallback if we outgrow raw SDK |
| **Raw Anthropic SDK + thin tool bus** | You own the loop | **Chosen** |

**Decision: raw Anthropic SDK (`anthropic`) + a ~30-line tool registry.**

Why:
1. **Total control** over scheduling, retries, and error recovery — essential for an
   unattended 24/7 process.
2. **Debuggability** — when it messages you at 3am or goes silent, you read your own
   loop, not framework internals.
3. **Native features** — Claude tool-use + prompt caching, no wrapper lag.
4. **Cheap exit** — tools are a clean interface, so migrating to PydanticAI / adding MCP
   later is a drop-in if we ever outgrow it.

Frameworks earn their weight with many agents, complex graphs, or team guardrails. A
personal single-agent companion is the opposite of that.

---

## 3. Tech stack

| Concern | Choice | Notes |
|---|---|---|
| Language | Python 3.12+ | `python-telegram-bot` (async) |
| Telegram | `python-telegram-bot` v21+ | Long polling — no public URL needed |
| LLM | Anthropic Claude via `anthropic` SDK | Model `claude-opus-4-8` (configurable) |
| Storage | SQLite (`sqlite3` / `aiosqlite`) | Single file `data/agent.db` |
| Scheduling | `asyncio` heartbeat loop | No external cron; agent self-schedules |
| Config | `python-dotenv` | `.env` for secrets |
| Deploy | systemd (or Docker) on a VPS | Restart-safe, always-on |

**Model note:** default `claude-opus-4-8` for reply quality. Because proactive heartbeats
can be frequent, the model id is a single config value — swap to a cheaper Claude model
if cost matters.

---

## 4. Architecture (HLD)

```
                    ┌──────────────────────────────┐
                    │        TELEGRAM (BotFather)   │
                    └───────▲───────────────┬───────┘
             sendMessage    │               │  updates (long-poll)
                            │               ▼
        ┌───────────────────┴───────────────────────────┐
        │                 I/O LAYER (io/telegram.py)      │
        │  inbound: receive your messages                 │
        │  outbound: send agent messages                  │
        └───────┬─────────────────────────▲──────────────┘
                │                          │
                ▼                          │
        ┌────────────────────────────────────────────────┐
        │           AGENT CORE (agent/core.py)            │
        │  system prompt + history + facts + trigger      │
        │        │                                        │
        │        ▼                                        │
        │   Claude ──► wants a tool? ──► TOOL BUS ────────┐│
        │        ▲                                       ││
        │        └──────── tool result ◄─────────────────┘│
        │        │                                        │
        │        ▼                                        │
        │   final message ──► I/O outbound                │
        └───────┬───────────────────────┬────────────────┘
                │                        │
                ▼                        ▼
        ┌──────────────┐        ┌──────────────────────┐
        │ MEMORY        │        │ TOOL BUS              │
        │ (memory/      │        │ (agent/tools/)        │
        │  store.py)    │        │  - remember_fact      │
        │  messages     │        │  - schedule_next      │
        │  facts        │        │  - (future: web,      │
        │  schedule     │        │    calendar, ...)     │
        │  SQLite       │        └──────────────────────┘
        └──────────────┘
                ▲
                │ "time to reach out?"
        ┌───────┴────────────────────────────────────────┐
        │        SCHEDULER / HEARTBEAT (scheduler.py)      │
        │  sleeps until next fire_at → asks agent core to  │
        │  decide whether/what to proactively send         │
        │  + safety floor: wake after N hrs of silence     │
        └──────────────────────────────────────────────────┘
```

### Project structure

```
auto-tele/
├── bot.py                # entrypoint: starts I/O + scheduler under asyncio
├── config.py             # env: TELEGRAM_TOKEN, ANTHROPIC_API_KEY, OWNER_CHAT_ID, MODEL
├── persona.md            # the character sheet: her voice, personality, quirks
├── agent/
│   ├── core.py           # the agentic loop (LLM <-> tools)
│   ├── prompt.py         # assembles system prompt = persona + memory context
│   └── tools/
│       ├── base.py       # Tool interface + registry
│       ├── remember.py   # remember_fact / remember_event
│       ├── schedule.py   # schedule_next_checkin
│       └── media.py      # send_sticker(mood) / send_gif(query)
├── io/
│   └── telegram.py       # inbound + send_human (typing, bubbles, stickers, gifs)
├── media/
│   └── stickers.json     # mood → sticker file_id library (curated)
├── scheduler.py          # heartbeat + reflection job + safety floor
├── memory/
│   ├── store.py          # SQLite access layer
│   ├── retrieval.py      # rank & select memories for each turn
│   └── reflection.py     # periodic: distill recent memories into insights
├── data/agent.db         # SQLite file (gitignored)
├── requirements.txt
├── .env.example
└── README.md
```

---

## 4.1 Design refinements (gap review)

A review of the plan surfaced 11 gaps — mostly around making her feel *human*, not just
functional. All are small additions, not redesigns:

| # | Gap | Why it matters | Fix |
|---|---|---|---|
| 1 | No timezone | "text at 9pm" — whose 9pm? | `OWNER_TZ`; all scheduling in your local time |
| 2 | Robotic delivery | Instant one-paragraph replies scream "bot" | Typing indicator + optional multi-bubble split + small send delays (`io/telegram.send_human`) |
| 3 | No presence awareness | Proactive text 30s after you just talked = creepy | Before proactive send, skip/defer if user active within `PRESENCE_WINDOW_MIN` |
| 4 | No message debounce | 3 quick texts → 3 replies talking over each other | Batch messages arriving within `DEBOUNCE_SECONDS` into one turn |
| 5 | Memory never updates | "he's stressed" stays true forever; facts contradict | `facts`/`memories` get `updated_at` + `superseded_by`; dedup on save |
| 6 | No cost strategy | Waking Opus every heartbeat to decide "text or not" is wasteful | Cheap `GATE_MODEL` (Haiku) for the *reach-out?* decision; Opus for real conversation; cache persona |
| 7 | Reflection timing vague | "periodically" isn't a spec | Nightly at `REFLECTION_HOUR` **+** after N new memories |
| 8 | Cold start undefined | First run: no memory, awkward first text | Seed a gentle first-contact check-in when memory is empty |
| 9 | Autonomy is a black box | Can't tell why she texted / stayed silent | Log every proactive decision to a `decisions` table |
| 10 | No test path | Waiting hours to test autonomy is painful | `simulate_heartbeat` CLI fires proactivity on demand |
| 11 | Silent-reschedule invariant | Heartbeat decides "silent" but forgets to reschedule → she dies | Invariant: every heartbeat MUST leave a future check-in |

---

## 4.2 Low-level design (LLD)

```
bot.py  (entrypoint)
  └─ asyncio.gather(
         telegram_polling_task,     ← listens for your messages
         scheduler_task,            ← wakes her on her own timer
         reflection_task )          ← nightly memory consolidation
     shared: agent_lock (asyncio.Lock), Store, ToolRegistry

────────────────────────────────────────────────────────────────────
io/telegram.py
  on_message(update):
      if update.chat_id != OWNER_CHAT_ID: return        # reject strangers
      buffer.add(update.text); await debounce(DEBOUNCE_SECONDS)   # gap#4
      async with agent_lock:                             # serialize turns
          reply = await core.run_agent(Trigger.reactive(buffer.flush()))
      await send_human(reply)     # gap#2: typing indicator, split bubbles, delay

────────────────────────────────────────────────────────────────────
agent/core.py — run_agent(trigger)
   1. ctx  = prompt.build(persona, trigger)              # system + messages
   2. loop:
        resp = claude(model, tools=registry.schemas, messages=ctx, cache=persona)
        if resp.stop_reason == "tool_use":
            for call in resp.tool_calls:
                out = registry.execute(call.name, call.input)   # remember/schedule
                ctx.append(tool_result(out))
            continue
        else:
            store.save_message("assistant", resp.text); return resp.text

agent/prompt.build(persona, trigger)
   system = persona.md + facts(all) + retrieval.top_k(trigger)
          + now/tz/presence
   messages = recent_window(HISTORY_WINDOW) + trigger

────────────────────────────────────────────────────────────────────
memory/retrieval.py — top_k(trigger)
   for m in store.all_memories():
       score = w1*recency(m.ts, m.last_recalled)
             + w2*importance(m.importance)          # 1–10, set on save
             + w3*keyword_overlap(m.text, trigger)  # v1 relevance, no embeddings
   pick top-K, bump their last_recalled, return

memory/reflection.py — run_reflection()
   recent = store.memories_since(last_reflection)
   insights = claude("summarize higher-level patterns", recent)
   store.save_memory(each, kind=reflection, importance=high)

────────────────────────────────────────────────────────────────────
scheduler.py — heartbeat()
   while True:
       nxt = store.next_pending_checkin() or seed_checkin()      # gap#8
       await asyncio.sleep(min(seconds_until(nxt), MAX_SILENCE_HOURS))
       async with agent_lock:
           if user_active_within(PRESENCE_WINDOW_MIN):           # gap#3
               reschedule(+30min); continue
           gate = claude(GATE_MODEL, "reach out now?")           # gap#6 cheap gate
           if gate.yes:
               decision = await core.run_agent(Trigger.proactive(nxt.reason))
           store.log_decision(decision or "silent")              # gap#9
       store.mark_done(nxt); ensure_future_checkin_exists()      # gap#11
```

**Reactive flow (you → her):**
```
YOU ─"had my interview"─▶ telegram(debounce,reject-strangers)
        ─▶ core.run_agent(reactive)
             prompt = persona + facts + retrieval("interview") + recent window
        ─▶ Claude(Opus) in-character
             tools? remember_event(imp=7) + schedule_next_checkin("tmrw 6pm")
        ─▶ send_human: [typing…] "omg how'd it go??" → "tell me everything"
        ─▶ saved to agent.db
```

**Proactive flow (she → you):**
```
scheduler sleeps … until the time SHE chose
   ─▶ presence check (did we just talk?) ─ no ─▶ cheap gate: reach out? ─ yes
   ─▶ core.run_agent(proactive, reason="ask how interview went")
        prompt recalls the interview thread from memory
   ─▶ Claude decides send (or "not now" → reschedule)
   ─▶ send_human: [typing…] "heyy did you get the job?? 🤞"
   ─▶ log decision + schedule next check-in (invariant)
```

---

## 5. Memory system — the heart of the clone

A persona clone lives on memory that feels *continuous* — she must remember *you two*, not
just facts. We use a **memory stream + reflection** model (the pattern behind the Stanford
"Generative Agents" paper), in five layers:

| Layer | Holds | Storage | Nature |
|---|---|---|---|
| **Persona sheet** | Her voice, personality, quirks, pet names, values, boundaries | `persona.md` | Mostly static, editable by you |
| **Semantic memory** | Durable facts — about you, her, the relationship | `facts` table | Grows slowly |
| **Episodic memory** | Timestamped events with an *importance* score — the "memory stream" | `memories` table | Grows continuously |
| **Working memory** | Recent conversation window | `messages` table | Rolling |
| **Reflection** | Higher-level insights distilled from recent memories | `memories` (kind=reflection) | Generated periodically |

### Tables (SQLite)

- **messages** — `(id, role, content, kind, ts)` — full conversation history
  (`kind`: text | sticker | gif — so her media replies are remembered too).
- **facts** — `(id, text, source, created_at, updated_at, superseded_by)` — durable
  truths; `superseded_by` lets a fact be replaced when it changes (gap#5).
- **memories** — `(id, text, kind, importance, ts, last_recalled)` —
  `kind`: event | reflection; `importance`: 1–10 (set by the agent when it saves).
- **schedule** — `(id, fire_at, reason, status)` — pending self-scheduled check-ins
  (`status`: pending | done | cancelled).
- **decisions** — `(id, ts, action, reason)` — audit log of proactive send/skip
  decisions (gap#9), so autonomy is debuggable.

### Retrieval (`memory/retrieval.py`)

Each turn builds context from: recent message window + all facts + top-K episodic
memories, ranked by **`recency × importance × relevance`**. v1 uses recency + importance +
keyword match (fast, no embeddings); embeddings/vector recall are added only when the
stream grows large. Recalled memories bump `last_recalled` (so recency reflects real use).

### Reflection (`memory/reflection.py`)

On a schedule (e.g. nightly, or after N new memories), the agent re-reads recent memories
and writes a few higher-level insights back as `kind=reflection` memories — e.g. *"he's
been stressed about work this week."* This is what makes her feel *aware* over time rather
than goldfish-brained, and it feeds empathy + proactivity.

### Memory → autonomy link

Open threads become outreach. When she learns "he has an interview tomorrow," she calls
`schedule_next_checkin` to follow up. **She reaches out because she remembers** — the
memory system *is* the engine of the proactivity.

---

## 6. The agentic loop (`agent/core.py`)

One function, used by **both** reactive and proactive flows:

```
run_agent(trigger):
    messages = system_prompt + recent_history + known_facts + trigger
    loop:
        resp = claude.messages.create(model, tools=registry.schemas, messages=...)
        if resp.stop_reason == "tool_use":
            result = registry.execute(tool_name, tool_input)
            append tool_result to messages
            continue
        else:
            persist(final_text)
            return final_text
```

- **Reactive trigger** = your incoming Telegram message.
- **Proactive trigger** = a synthetic system note:
  *"Heartbeat. Reason you scheduled this: '<reason>'. Decide whether to message the user
  now and what to say. You may also choose to stay silent and reschedule."*
  → the agent can legitimately choose to send nothing and just call
  `schedule_next_checkin` again.

A single `asyncio.Lock` serializes agent calls so reactive and proactive turns never
overlap or corrupt history.

---

## 6.1 Expressive media — stickers & GIFs (texts like a real person)

Real people don't only type — they drop a sticker when they're being cute, a GIF when
words won't do. She expresses through media via two tools she calls mid-reply:

- **`send_sticker(mood)`** — picks from a curated `media/stickers.json` mapping moods
  (`love`, `laugh`, `sulk`, `miss_you`, `sleepy`, …) to Telegram sticker `file_id`s.
  Telegram requires a `file_id` to send a sticker, so we pre-collect a small set from her
  favourite sticker pack once (a `tools/collect_stickers.py` helper logs `file_id`s as you
  forward stickers to the bot). Sent via `sendSticker`.
- **`send_gif(query)`** — searches a GIF provider (Tenor or Giphy, free API key) for
  `query` (e.g. "excited happy dance") and sends the top hit via `sendAnimation`.

**How it plugs in:** these are normal tool-bus tools, but their handler sends media
straight through the I/O layer as part of the turn (so she can send *"omg"* + a sticker +
*"i'm so happy for you"* as a natural sequence). Each media send is also written to
`messages` with `kind = sticker | gif` so she remembers what she sent.

**Restraint is a persona rule, not code.** The `persona.md` / system prompt instructs
sparing, contextual use — a sticker when it fits the emotion, not on every message —
exactly how a normal person texts. Overuse is the failure mode we prompt against.

**Config:** `GIF_PROVIDER` + `GIF_API_KEY` in `.env` (optional; if unset, `send_gif`
is disabled and she falls back to stickers/text).

---

## 7. Self-scheduling autonomy

This is what makes it feel like an agent and not a cron spammer.

- Tool `schedule_next_checkin(delay_or_time, reason)` writes a `pending` row to
  `schedule`. The agent sets its own next contact — e.g. *"check in around 8pm because
  they mentioned an interview today."*
- `scheduler.py`: sleeps until the nearest pending `fire_at`, then calls
  `run_agent(proactive_trigger)` with that reason, marks the row `done`.
- **Bootstrap:** on startup, if no future check-in exists, seed one so a fresh bot
  eventually reaches out. This keeps the loop self-perpetuating.
- **Safety floor (decided: on):** if total silence exceeds `MAX_SILENCE_HOURS`, the
  heartbeat wakes anyway — so the agent can never accidentally schedule itself into never
  talking to you.

---

## 8. Concurrency & resilience

- `bot.py` runs the Telegram polling loop and the scheduler loop concurrently via
  `asyncio.gather`.
- One shared lock around `run_agent`.
- Anthropic/network calls wrapped with retry + timeout; failures are logged and the loop
  survives (never crash the whole process on one bad turn).
- All state is in SQLite, so a restart resumes cleanly (pending schedule rows survive).

---

## 9. Configuration (`.env`)

```
TELEGRAM_TOKEN=            # from @BotFather
ANTHROPIC_API_KEY=        # from console.anthropic.com
OWNER_CHAT_ID=            # your Telegram numeric chat id (bot only talks to you)
OWNER_TZ=Asia/Kolkata     # gap#1 — your local timezone for all scheduling
MODEL=claude-opus-4-8     # conversation model
GATE_MODEL=claude-haiku-4-5-20251001   # gap#6 — cheap "reach out now?" decision
MAX_SILENCE_HOURS=24      # safety floor
HISTORY_WINDOW=30         # recent turns loaded per call
DEBOUNCE_SECONDS=3        # gap#4 — batch your rapid messages
PRESENCE_WINDOW_MIN=5     # gap#3 — don't proactively text if you just talked
REFLECTION_HOUR=3         # gap#7 — nightly reflection at 3am local
GIF_PROVIDER=tenor        # stickers/gifs — tenor | giphy | (empty = disabled)
GIF_API_KEY=              # provider key; if empty, send_gif is disabled
```

---

## 10. Implementation plan (phased)

Each phase is independently runnable and testable.

**Phase 1 — Skeleton & I/O**
- `config.py`, `requirements.txt`, `.env.example`, `.gitignore`.
- `memory/store.py`: SQLite schema (messages, facts, memories, schedule, decisions).
- `io/telegram.py`: connect with BotFather token; echo bot restricted to `OWNER_CHAT_ID`.
- ✅ Done when: you text the bot and it echoes back; messages land in SQLite.

**Phase 2 — Persona**
- `persona.md`: the character sheet — built from the persona interview (§12): her voice,
  personality, quirks, pet names, values, how she opens a conversation, media habits.
- `agent/prompt.py`: assemble system prompt = persona + retrieved memory context.
- ✅ Done when: the persona sheet exists and the prompt renders in-character.

**Phase 3 — Reactive brain + human delivery**
- `agent/core.py`: agent loop (no tools yet); loads persona + history + retrieved memory.
- `io/telegram.send_human`: typing indicator, multi-bubble split, small delays (gap#2);
  inbound debounce (gap#4).
- ✅ Done when: real in-character chat that references earlier messages and *feels* typed.

**Phase 4 — Memory & tools**
- `agent/tools/base.py`: Tool interface + registry (emits schemas, executes handlers).
- `agent/tools/remember.py`: `remember_fact` + `remember_event`; dedup + supersede (gap#5).
- `memory/retrieval.py`: rank & select memories per turn (recency × importance × keyword).
- `memory/reflection.py`: distill recent memories into `kind=reflection` insights.
- ✅ Done when: she stores things you tell her and recalls them naturally days later.

**Phase 5 — Expressive media (stickers & GIFs)**
- `tools/collect_stickers.py`: one-time helper to capture sticker `file_id`s → `stickers.json`.
- `agent/tools/media.py`: `send_sticker(mood)` + `send_gif(query)` via Tenor/Giphy.
- Persona rule for sparing, contextual use; log media to `messages` (kind=sticker|gif).
- ✅ Done when: she drops a fitting sticker/GIF at the right emotional moment, not spammily.

**Phase 6 — Autonomy**
- `agent/tools/schedule.py`: `schedule_next_checkin` (timezone-aware, gap#1).
- `scheduler.py`: heartbeat + cheap gate model (gap#6) + presence check (gap#3) + safety
  floor + cold-start seed (gap#8) + reschedule invariant (gap#11) + decision log (gap#9).
- `scheduler.reflection_task`: nightly at `REFLECTION_HOUR` + after N new memories (gap#7).
- `bot.py`: run polling + scheduler + reflection concurrently with a shared lock.
- `simulate_heartbeat` CLI to fire proactivity on demand (gap#10).
- ✅ Done when: she texts you first, unprompted, following up on something she remembered.

**Phase 7 — Harden for VPS**
- Logging, retry/timeout wrappers, graceful shutdown.
- `Dockerfile` + `docker-compose.yml` **or** a `systemd` unit.
- Deploy docs + `data/agent.db` backup in `README.md`.
- ✅ Done when: it runs 24/7 on the VPS and survives restarts/network blips.

---

## 11. Deployment (VPS)

- Small always-on Linux box (1 vCPU / 1GB is plenty).
- Long polling → no inbound ports / no public URL / no TLS to manage.
- Run under `systemd` (auto-restart) or Docker with `restart: unless-stopped`.
- SQLite file on a persistent volume; periodic backup of `data/agent.db`.

---

## 12. Decisions & defaults (change any)

- **Persona source:** DECIDED — you describe her; we hand-write `persona.md` together
  from a short interview (personality, tone, pet names, how she texts, your dynamic). The
  optional `ingest/import_chat.py` is dropped from v1.
- **Safety floor:** ON (`MAX_SILENCE_HOURS=24`).
- **Transport:** long polling (not webhook).
- **Model:** `claude-opus-4-8`, single config value.
- **Embeddings:** deferred — v1 retrieval is recency + importance + keyword.

### Persona interview (fills `persona.md` in Phase 2)

Short Q&A to capture: her name & how she'd want to be addressed; core personality traits;
how she texts (length, emojis, punctuation, pet names/nicknames for you); her media habits
(does she send lots of stickers/GIFs? which moods?); values & boundaries; recurring
topics/inside references; how she typically opens a conversation when reaching out first;
mood range. We turn the answers into the character sheet.

---

## 13. Future extensions (post-v1)

- More tools: `web_search`, `read_calendar`, `create_reminder`, weather, news digest.
- Memory upgrade: summarize old history into facts; optional vector recall.
- Richer proactivity: react to external signals (calendar events, email), not just time.
- Optional migration to PydanticAI or MCP tools if the tool count grows large.
```

