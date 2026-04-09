"""
Local Flask server — receives tab session data from the Firefox extension
and persists it to SQLite. Also exposes an endpoint to trigger the
on-demand historical report.

Binds to 127.0.0.1:7331 only (never exposed to the network).
Run via launchd (see setup.sh) so it starts automatically on login.
"""

import os
import sqlite3
import threading
from datetime import datetime

from flask import Flask, jsonify, request

# ─── Paths ────────────────────────────────────────────────────────────────────

DATA_DIR = os.path.expanduser("~/.browsing_tracker")
DB_PATH  = os.path.join(DATA_DIR, "browsing.db")

# ─── DB setup ─────────────────────────────────────────────────────────────────

def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            url            TEXT    NOT NULL,
            title          TEXT,
            domain         TEXT,
            timestamp      TEXT    NOT NULL,
            duration_secs  INTEGER NOT NULL,
            date           TEXT    NOT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_date ON sessions (date)")
    conn.commit()
    conn.close()

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ─── Flask app ────────────────────────────────────────────────────────────────

app = Flask(__name__)

# ─── POST /track — receive a session record from the extension ────────────────

@app.route("/track", methods=["POST"])
def track():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body"}), 400

    url              = data.get("url", "").strip()
    duration_seconds = data.get("duration_seconds")
    timestamp        = data.get("timestamp", datetime.utcnow().isoformat())

    if not url or duration_seconds is None:
        return jsonify({"status": "error", "message": "Missing url or duration_seconds"}), 400

    try:
        duration_seconds = int(duration_seconds)
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "duration_seconds must be an integer"}), 400

    # Extract date portion for indexing
    date = timestamp[:10]  # YYYY-MM-DD

    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO sessions (url, title, domain, timestamp, duration_secs, date)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                url,
                data.get("title", ""),
                data.get("domain", ""),
                timestamp,
                duration_seconds,
                date,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"status": "ok"})

# ─── GET /health — used by setup.sh to verify the server is up ───────────────

@app.route("/health", methods=["GET"])
def health():
    try:
        conn = get_conn()
        conn.execute("SELECT 1")
        conn.close()
        db_status = "ok"
    except Exception as e:
        db_status = str(e)

    return jsonify({"status": "running", "db": db_status})

# ─── POST /generate-historical — on-demand historical report ─────────────────
#
# Importing reporter here (lazy import) avoids circular-import issues and keeps
# startup fast. The report runs in a background thread so the popup gets an
# immediate acknowledgement; the email arrives once processing is complete.

@app.route("/generate-historical", methods=["POST"])
def generate_historical():
    def _run():
        try:
            # Lazy import — reporter and analyzer are only needed here
            import reporter
            import json

            config = reporter.load_config()
            from analyzer import read_firefox_history, classify_historical_with_claude
            from reporter import generate_historical_html_report, send_email

            history_data = read_firefox_history()
            if not history_data:
                return  # Nothing to analyse

            analysis = classify_historical_with_claude(history_data)
            html     = generate_historical_html_report(analysis)
            send_email("Historical Browsing Behavior Report", html, config)
        except Exception as e:
            # Errors are logged to stderr (captured by launchd)
            import traceback
            traceback.print_exc()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return jsonify({"status": "sent",
                    "message": "Generating report in the background — check your email shortly."})

# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    # host=127.0.0.1 — localhost only, never exposed to the network
    app.run(host="127.0.0.1", port=7331, debug=False)
