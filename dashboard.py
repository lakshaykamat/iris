"""
Ruchi Dashboard — read-only window into the agent's inner life.

Launched automatically by bot.py as a daemon thread.
Can also be run standalone:  python dashboard.py [port]
"""

from flask import Flask, jsonify, render_template, request
from functools import wraps
from pathlib import Path
import threading
import sys
import os

app = Flask(__name__)

try:
    sys.path.insert(0, os.path.dirname(__file__))
    from config import DB_PATH
except Exception:
    DB_PATH = Path("data/agent.db")

from memory.store import Store

# One read-only connection, separate from the bot's, created at startup and shared
# across Flask's request threads. A lock serializes access because a single SQLite
# connection cannot be used from several threads at once.
store = Store(Path(DB_PATH), check_same_thread=False)
_lock = threading.Lock()


def reads_db(view):
    """Serialize a route's access to the shared read-only connection."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        with _lock:
            return view(*args, **kwargs)
    return wrapper


# ── API ─────────────────────────────────────────────────────────────────────

@app.route("/api/status")
@reads_db
def api_status():
    last = store.last_message()
    return jsonify({
        "message_count": store.message_count(),
        "memory_count":  store.memory_count(),
        "fact_count":    store.active_fact_count(),
        "last_message":  {"role": last[1], "ts": last[0]} if last else None,
        "recent_reflections": [r["text"] for r in store.recent_reflections(3)],
    })


@app.route("/api/messages")
@reads_db
def api_messages():
    limit = request.args.get("limit", 40, type=int)
    return jsonify([dict(r) for r in store.messages_for_display(limit)])


@app.route("/api/memories")
@reads_db
def api_memories():
    return jsonify([dict(r) for r in store.recent_memories(80)])


@app.route("/api/facts")
@reads_db
def api_facts():
    return jsonify([dict(r) for r in store.active_facts()])


@app.route("/api/decisions")
@reads_db
def api_decisions():
    return jsonify([dict(r) for r in store.recent_decisions(50)])


@app.route("/api/schedule")
@reads_db
def api_schedule():
    return jsonify([dict(r) for r in store.recent_schedule(30)])


@app.route("/api/tokens")
@reads_db
def api_tokens():
    totals = store.token_usage_totals()
    return jsonify({
        "totals":   dict(totals) if totals else None,
        "by_model": [dict(r) for r in store.token_usage_by_model()],
        "recent":   [dict(r) for r in store.token_usage_recent(40)],
    })


@app.route("/")
def index():
    return render_template("dashboard.html")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5050
    print(f"\n  ✦ Ruchi dashboard  →  http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
