# Browsing Behavior Tracker — Design & Architecture Document

## 1. System Overview

The system is composed of three loosely coupled layers:

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1: Data Collection                                    │
│  Firefox Extension (background.js)                          │
│  - Tracks active tab time via browser event listeners       │
│  - POSTs session records to local Flask server              │
│  - Buffers to browser.storage.local if server is down       │
└───────────────────────┬─────────────────────────────────────┘
                        │ HTTP POST (localhost:7331)
┌───────────────────────▼─────────────────────────────────────┐
│  LAYER 2: Local Data Store + Server                         │
│  Flask Server (server.py) + SQLite (browsing.db)            │
│  - Receives and persists session records                    │
│  - Runs as a background launchd service on macOS            │
│  - Also reads Firefox places.sqlite for historical data     │
└───────────────────────┬─────────────────────────────────────┘
                        │ reads SQLite / places.sqlite
┌───────────────────────▼─────────────────────────────────────┐
│  LAYER 3: Analysis + Reporting                              │
│  analyzer.py → Claude API → reporter.py → Gmail SMTP        │
│  - Aggregates data for the report period                    │
│  - Sends to Claude with no pre-defined categories           │
│  - Renders HTML email and delivers via SMTP                 │
│  - Triggered by cron on schedule                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Component Design

### 2.1 Firefox Extension (`extension/`)

**Files:**
- `manifest.json` — Extension metadata, permissions, background script declaration
- `background.js` — All tracking logic

**How time tracking works:**

The extension maintains two variables at all times:
- `activeTabId` — the ID of the currently focused tab
- `activeTabStartTime` — epoch ms when that tab became active

When any of the following events fires, the current session is flushed:

| Event | Action |
|-------|--------|
| `tabs.onActivated` | End session for old tab, start session for new tab |
| `tabs.onUpdated` (URL change) | End session for old URL, start session for new URL |
| `tabs.onRemoved` | End session for closed tab |
| `windows.onFocusChanged` (lost focus) | End session, pause timer |
| `windows.onFocusChanged` (gained focus) | Resume timer for current tab |

**Data sent per session (JSON POST to localhost:7331/track):**
```json
{
  "url": "https://www.youtube.com/watch?v=abc123",
  "title": "CS50 Week 4: Memory - Harvard University",
  "domain": "www.youtube.com",
  "timestamp": "2026-04-09T14:32:10.000Z",
  "duration_seconds": 2847
}
```

**Offline buffer:** If the POST fails, the record is saved to `browser.storage.local` under key `pending`. A `setInterval` every 30 seconds retries all pending records.

---

### 2.2 Local Flask Server (`server.py`)

**Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/track` | Receive a session record from the extension |
| GET | `/health` | Health check (used by setup script) |

**Storage:** SQLite database at `~/.browsing_tracker/browsing.db`

**Schema:**
```sql
CREATE TABLE sessions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    url            TEXT NOT NULL,
    title          TEXT,
    domain         TEXT,
    timestamp      TEXT NOT NULL,
    duration_secs  INTEGER NOT NULL,
    date           TEXT NOT NULL        -- YYYY-MM-DD, for fast date range queries
);
```

**Runtime:** Managed by a macOS launchd plist at `~/Library/LaunchAgents/com.browsingtracker.server.plist`. Starts automatically on login, restarts on crash.

---

### 2.3 Analyzer (`analyzer.py`)

Responsible for two distinct analysis paths:

#### Path A — Historical (first run only)
1. Locate Firefox profile: `~/Library/Application Support/Firefox/Profiles/*.default-release/places.sqlite`
2. Copy to `/tmp/places_copy.sqlite` (avoid lock conflict with running Firefox)
3. Query all history:
   ```sql
   SELECT p.url, p.title, p.visit_count,
          MIN(v.visit_date) as first_visit,
          MAX(v.visit_date) as last_visit
   FROM moz_places p
   JOIN moz_historyvisits v ON v.place_id = p.id
   GROUP BY p.id
   ORDER BY p.visit_count DESC
   ```
4. Aggregate by domain: sum visit counts, collect sample titles, determine active year range
5. If >200 domains, group minor domains (< 0.5% of total visits) into "Other"
6. Send to Claude with open-ended historical analysis prompt
7. Claude returns: longitudinal trends, dominant eras, behavioral shifts over time

#### Path B — Incremental (daily / weekly / monthly / annual)
1. Query `browsing.db` for the date range
2. Aggregate by domain: `{domain, total_seconds, visit_count, sample_titles[]}`
3. Filter out noise: sessions < 5 seconds, domains with < 30 seconds total
4. Send to Claude with open-ended classification prompt
5. Claude returns: category list (self-defined), domains per category, behavioral insight

**Claude prompt design (incremental):**
```
Here is browsing data for [period]. Total time: [X hours].
[domain list with time + sample titles as JSON]

Analyze this and:
1. Group domains into behavioral categories YOU define based on what you see.
   Do not use pre-set buckets. Let the data speak.
2. For each category: name, description, domains, total time.
3. Write a behavioral insight paragraph.

Return as JSON: { categories: [...], behavioral_insight: "...", total_seconds: N }
```

**Claude prompt design (historical):**
```
Here is a person's full Firefox browsing history aggregated by domain.
Data spans [first_year] to [last_year].
[domain list with visit counts + year breakdown + sample titles]

Analyze long-term browsing behavior:
1. What are the dominant behavioral patterns across the full history?
2. How has behavior shifted over the years?
3. What categories of content does this person gravitate toward?
4. Any notable trends, spikes, or changes?

Return as JSON: { periods: [...], dominant_patterns: [...], behavioral_evolution: "...", insight: "..." }
```

**Model:** `claude-haiku-4-5-20251001` (fast, cheap, sufficient for classification)

---

### 2.4 Reporter (`reporter.py`)

**Report flow:**
```
get_date_range(period)
    → get_sessions(start, end)   [from browsing.db]
    → classify_with_claude(sessions, period)
    → generate_html_report(analysis)
    → send_email(html, config)
```

**Report periods:**

| Period | Date range | Cron schedule |
|--------|-----------|---------------|
| daily | today only | `59 23 * * *` |
| weekly | last 7 days (Mon–Sun) | `59 23 * * 0` |
| monthly | 1st of month → today | `59 23 28-31 * *` (with last-day check) |
| annual | Jan 1 → today | `59 23 31 12 *` |

**HTML email structure:**
```
Subject: [Daily/Weekly/Monthly/Annual] Browsing Report — [date]

Body:
  - Header: period label + date range
  - Total browsing time (large number)
  - Per-category breakdown:
      Category name + description
      Time spent + percentage
      Horizontal bar (CSS)
      Top domains in this category
  - Behavioral Insight block (Claude's paragraph)
  - Footer
```

**Email sending:** Python `smtplib` with SSL, Gmail SMTP (`smtp.gmail.com:465`). Uses an App Password (not the account password) for security.

---

### 2.5 Historical Report — On-Demand via Extension Popup

The historical report is **not** triggered automatically. The user initiates it explicitly.

**Extension popup UI (`extension/popup.html` + `extension/popup.js`):**
- A small toolbar button popup with one clearly labeled button: **"Generate Historical Behavior Report"**
- When clicked: shows a spinner + status message ("Generating... this may take a moment")
- Sends a POST to `http://127.0.0.1:7331/generate-historical`
- On success: shows "Report sent to your email"
- On failure: shows "Server not running — start it first"

**Flask endpoint (`/generate-historical`):**
- Reads places.sqlite, runs historical Claude analysis, sends email
- Returns `{"status": "sent"}` or `{"status": "error", "message": "..."}`
- Can be triggered any number of times — no one-time flag or restriction

---

### 2.6 Configuration (`config.json`)

Stored at `~/.browsing_tracker/config.json` (outside the repo, never committed):

```json
{
  "email_to": "you@gmail.com",
  "smtp_host": "smtp.gmail.com",
  "smtp_port": 465,
  "smtp_user": "you@gmail.com",
  "smtp_password": "your-app-password-here",
  "smtp_from": "you@gmail.com",
  "anthropic_api_key": "sk-ant-..."
}
```

---

## 3. Data Flow Diagrams

### 3.1 Real-time tracking (ongoing)
```
User visits page
      │
      ▼
Extension detects tab event
      │
      ▼
Calculate duration for previous tab
      │
      ├─ Server reachable? ──YES──► POST to localhost:7331/track
      │                                      │
      └─ Server down? ─────────► buffer      ▼
                                 locally   Flask appends to browsing.db
```

### 3.2 Scheduled report (daily example)
```
Cron fires at 23:59
      │
      ▼
reporter.py --period daily
      │
      ├─ First run check ──► (historical report if needed)
      │
      ▼
Query browsing.db for today's sessions
      │
      ▼
Aggregate by domain (domain, total_secs, titles[])
      │
      ▼
Send to Claude API (no pre-defined categories)
      │
      ▼
Claude returns { categories[], behavioral_insight }
      │
      ▼
Generate HTML email
      │
      ▼
Send via Gmail SMTP
```

### 3.3 On-demand historical report
```
User clicks "Generate Historical Behavior Report" in extension popup
      │
      ▼
Extension POSTs to localhost:7331/generate-historical
      │
      ▼
Flask reads places.sqlite (copy to /tmp to avoid lock)
      │
      ▼
Query all history, aggregate by domain + year
      │
      ▼
Send to Claude (longitudinal analysis prompt)
      │
      ▼
Claude returns { periods[], behavioral_evolution, insight }
      │
      ▼
Generate + send historical HTML email
      │
      ▼
Flask returns {"status": "sent"} → popup shows confirmation
```

---

## 4. File Structure

```
browsing_tracker/                  ← repo root
├── extension/
│   ├── manifest.json              ← Firefox extension manifest (MV2)
│   ├── background.js              ← Tab time tracking logic
│   ├── popup.html                 ← Toolbar button popup UI
│   └── popup.js                   ← Popup logic (triggers historical report)
├── server.py                      ← Flask server (receives extension data)
├── analyzer.py                    ← Data aggregation + Claude API calls
├── reporter.py                    ← HTML report builder + email sender
├── setup.sh                       ← One-command setup script
├── config.template.json           ← Config template (copy to ~/.browsing_tracker/)
├── requirements.txt               ← Python dependencies
├── REQUIREMENTS.md
├── DESIGN.md
└── TASKS.md

~/.browsing_tracker/               ← runtime data (NOT in repo)
├── config.json                    ← User's actual config (email, API key)
├── browsing.db                    ← SQLite: extension-tracked sessions
└── .first_run_complete            ← Flag: historical report already sent
```

---

## 5. Technology Choices & Rationale

| Technology | Choice | Reason |
|------------|--------|--------|
| Browser extension | Firefox MV2 | MV2 allows persistent background scripts; MV3 service workers have lifecycle issues for continuous time tracking |
| Extension → backend | HTTP POST to localhost | Simple, reliable; avoids complex native messaging setup |
| Local server | Flask (Python) | Lightweight; same language as rest of backend; easy to daemonize |
| Database | SQLite | Zero-infrastructure, local, fast for date range queries |
| LLM | Claude Haiku | Cheapest Claude model; sufficient for classification; ~$0.01-0.05/day |
| Email | Gmail SMTP + App Password | Universal; no OAuth complexity; secure with App Passwords |
| Scheduling | cron | Native macOS/Linux; no extra dependencies |
| Server daemon | launchd | macOS native; auto-start on login; auto-restart on crash |

---

## 6. Security Considerations

- Config file (with API key + email password) lives at `~/.browsing_tracker/config.json` with `chmod 600`
- Flask server binds to `127.0.0.1` only — not accessible from network
- Gmail App Password used instead of account password
- No browsing data leaves the machine except domain+title to Claude API for classification
- places.sqlite is copied to /tmp before reading — original is never modified
