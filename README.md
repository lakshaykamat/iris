# iris

An autonomous Telegram companion that chats in a specific persona and texts you first
— because she remembers. See [plan.md](plan.md) for the full design.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # fill in the values below
```

**Required `.env` values:**

| Variable | Where to get it |
|---|---|
| `TELEGRAM_TOKEN` | [@BotFather](https://t.me/BotFather) → create a bot |
| `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) |
| `OWNER_CHAT_ID` | Message [@userinfobot](https://t.me/userinfobot) — it replies with your numeric id |

**Run locally:**

```bash
python bot.py
```

Text the bot — she'll reply in character and remember what you say.

---

## Stickers & GIFs

She drops a sticker or GIF sparingly at emotional moments (never every message).
Both are optional; without them she stays text-only.

**Stickers** — collect `file_id`s once:

```bash
python tools/collect_stickers.py
```

In the chat, send a mood word (`love`, `laugh`, `sulk`, `miss_you`, `sleepy`, …),
then forward stickers that fit it. Each is filed under that mood in
`media/stickers.json`. Switch mood by sending another word. Stop with Ctrl+C.

**GIFs** — set in `.env`:

```
GIF_PROVIDER=tenor   # or giphy
GIF_API_KEY=...      # leave empty to disable GIFs
```

---

## Simulate proactivity (test without waiting)

Fire one proactive turn on demand — she decides whether to send, then prints
what she would have said:

```bash
python scheduler.py "check how the interview went"
```

---

## Debug memory

```bash
# Inspect the live database
sqlite3 data/agent.db 'SELECT role, content, ts FROM messages ORDER BY id;'
sqlite3 data/agent.db 'SELECT text, importance FROM memories ORDER BY ts DESC LIMIT 20;'
sqlite3 data/agent.db 'SELECT action, reason, ts FROM decisions ORDER BY id DESC LIMIT 10;'

# Or use the memory CLI
python tools/memory_cli.py
```

---

## Deploy to a VPS (Docker)

You need a small always-on Linux box (1 vCPU / 1 GB RAM is plenty).
Long polling means no inbound ports, no public URL, no TLS to manage.

**1. Copy files to the VPS:**

```bash
rsync -av --exclude .venv --exclude __pycache__ --exclude 'data/' \
  ./ user@your-vps:/opt/iris/
```

**2. Copy your `.env`:**

```bash
scp .env user@your-vps:/opt/iris/.env
```

**3. On the VPS — build and start:**

```bash
cd /opt/auto-tele
docker compose up -d --build
```

The container runs as `restart: unless-stopped` — it comes back after reboots and
crashes automatically.

**4. Tail logs:**

```bash
docker compose logs -f
```

---

## Backup `data/agent.db`

The SQLite file holds all memory, facts, history and the self-scheduled check-ins.
Back it up regularly.

**One-off backup from the VPS:**

```bash
# On the VPS
cp /opt/iris/data/agent.db /opt/iris/data/agent.db.bak

# Pull it to your machine
scp user@your-vps:/opt/iris/data/agent.db ./agent.db.bak
```

**Nightly cron on the VPS** (`crontab -e`):

```
0 2 * * * cp /opt/iris/data/agent.db /opt/iris/data/agent.db.$(date +\%Y\%m\%d)
```

**Restore** — stop the bot, replace the file, start again:

```bash
docker compose stop
cp agent.db.bak /opt/iris/data/agent.db
docker compose start
```
