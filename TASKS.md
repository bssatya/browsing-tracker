# Browsing Behavior Tracker — Development Task List

## Status Legend
- [ ] Not started
- [~] In progress
- [x] Done

---

## Phase 1 — Firefox Extension (Data Collection)

- [ ] **EXT-01** Create `extension/manifest.json`
  - MV2, persistent background script
  - Permissions: tabs, storage, windows, localhost
  - Declare `browser_action` for toolbar popup

- [ ] **EXT-02** Create `extension/background.js` — core tab tracking
  - Track `activeTabId` and `activeTabStartTime`
  - Handle `tabs.onActivated` — flush old tab, start new timer
  - Handle `tabs.onUpdated` (URL change) — flush current tab, restart timer
  - Handle `tabs.onRemoved` — flush closed tab
  - Handle `windows.onFocusChanged` — pause on blur, resume on focus
  - Initialize with current active tab on extension load

- [ ] **EXT-03** Create `extension/background.js` — POST to server
  - Build session record: `{url, title, domain, timestamp, duration_seconds}`
  - Filter: skip sessions < 5 seconds
  - Filter: skip `about:*`, `moz-extension:*`, `chrome:*` URLs
  - POST to `http://127.0.0.1:7331/track`

- [ ] **EXT-04** Create `extension/background.js` — offline buffer
  - On POST failure: save record to `browser.storage.local` under `pending`
  - `setInterval` every 30 seconds: retry all pending records
  - On retry success: remove from pending list

- [ ] **EXT-05** Create `extension/popup.html` — toolbar button popup UI
  - Single button: "Generate Historical Behavior Report"
  - Status area to show: idle / generating / sent / error states

- [ ] **EXT-06** Create `extension/popup.js` — popup logic
  - On button click: disable button, show "Generating..." spinner
  - POST to `http://127.0.0.1:7331/generate-historical`
  - On success (`{"status": "sent"}`): show "Report sent to your email"
  - On failure / server down: show "Server not running — start it first"

---

## Phase 2 — Local Flask Server (Data Persistence)

- [ ] **SRV-01** Create `server.py` — Flask app scaffold
  - Bind to `127.0.0.1:7331`
  - Initialize SQLite DB at `~/.browsing_tracker/browsing.db` on startup

- [ ] **SRV-02** Create `server.py` — SQLite schema
  - Table: `sessions (id, url, title, domain, timestamp, duration_secs, date)`
  - Index on `date` column for fast range queries

- [ ] **SRV-03** Create `server.py` — POST `/track` endpoint
  - Validate required fields: `url`, `duration_seconds`, `timestamp`
  - Extract `date` from timestamp
  - Insert into `sessions` table

- [ ] **SRV-04** Create `server.py` — GET `/health` endpoint
  - Return `{"status": "running", "db": "ok"}`

- [ ] **SRV-05** Create `server.py` — POST `/generate-historical` endpoint
  - Call `classify_historical_with_claude()` from analyzer.py
  - Call `run_historical_report()` from reporter.py
  - Return `{"status": "sent"}` on success or `{"status": "error", "message": "..."}` on failure

---

## Phase 3 — Analyzer (Claude API Integration)

- [ ] **ANL-01** Create `analyzer.py` — session query functions
  - `get_sessions_for_period(start_date, end_date)` → list of session dicts
  - `aggregate_by_domain(sessions)` → sorted list of `{domain, total_seconds, visit_count, titles[]}`
  - `format_duration(seconds)` → human-readable string (e.g. "2h 14m")

- [ ] **ANL-02** Create `analyzer.py` — incremental Claude classification
  - Function: `classify_with_claude(sessions, period_label)`
  - Aggregate sessions by domain
  - Build open-ended prompt (no pre-defined categories)
  - Call Claude Haiku API
  - Parse and return JSON response: `{categories[], behavioral_insight, total_seconds}`

- [x] **ANL-03** Create `analyzer.py` — historical data reader
  - Function: `read_firefox_history()`
  - Reads `firefox_profile` from config.json; falls back to auto-detect if null
  - Copy to `/tmp/places_copy.sqlite` to avoid DB lock
  - Query: all domains with visit counts, first/last visit, sample titles
  - Aggregate by domain + year
  - Group minor domains (< 0.5% of total visits) into "Other"

- [x] **ANL-03b** Create `list_profiles.py` — helper to list Firefox profiles
  - Shows profile name, folder, visit count, and history date range
  - Tells user exactly which folder name to put in config.json

- [ ] **ANL-04** Create `analyzer.py` — historical Claude analysis
  - Function: `classify_historical_with_claude(history_data)`
  - Build longitudinal analysis prompt
  - Call Claude Haiku API
  - Parse and return JSON response: `{periods[], dominant_patterns[], behavioral_evolution, insight}`

---

## Phase 4 — Reporter (HTML Email)

- [ ] **RPT-01** Create `reporter.py` — config loader
  - Load `~/.browsing_tracker/config.json`
  - Raise clear error if config is missing or keys are absent

- [ ] **RPT-02** Create `reporter.py` — date range calculator
  - Function: `get_date_range(period)` for: `daily`, `weekly`, `monthly`, `annual`
  - Returns: `(start_date, end_date, human_label)`
  - Weekly: Monday → Sunday of current week
  - Monthly: 1st of current month → today
  - Annual: Jan 1 → today

- [ ] **RPT-03** Create `reporter.py` — HTML report generator (incremental)
  - Function: `generate_html_report(analysis, period_label, start_date, end_date)`
  - Sections: header, total time, per-category bars, behavioral insight block, footer
  - CSS inline styles (email client compatible)
  - Color-coded category bars (auto-assigned colors)
  - Show top 5 domains per category

- [ ] **RPT-04** Create `reporter.py` — HTML report generator (historical)
  - Function: `generate_historical_html_report(analysis)`
  - Sections: header, behavioral evolution paragraph, dominant patterns list, year-by-year summary, insight block
  - Note clearly: "Based on visit frequency — duration tracking begins from [date]"

- [ ] **RPT-05** Create `reporter.py` — email sender
  - Function: `send_email(subject, html_body, config)`
  - Use `smtplib` with `SMTP_SSL` on port 465
  - Gmail App Password authentication

- [ ] **RPT-06** Create `reporter.py` — historical report function (callable on demand)
  - Function: `run_historical_report(config)`
  - Called by `server.py` when `/generate-historical` endpoint is hit
  - No flag file, no restriction — can be run any number of times

- [ ] **RPT-07** Create `reporter.py` — main entry point
  - CLI: `python reporter.py --period [daily|weekly|monthly|annual]`
  - Run first-run check on every invocation
  - Then run the requested period report

---

## Phase 5 — Config & Dependencies

- [ ] **CFG-01** Create `config.template.json`
  - Fields: `email_to`, `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`, `smtp_from`, `anthropic_api_key`
  - Placeholder values with inline comments explaining each field

- [ ] **CFG-02** Create `requirements.txt`
  - `flask`
  - `anthropic`
  - (all others are stdlib: sqlite3, smtplib, json, argparse, shutil, glob, os, datetime)

---

## Phase 6 — Setup & Automation

- [ ] **SET-01** Create `setup.sh` — dependency installation
  - Check Python 3.9+
  - `pip install -r requirements.txt`
  - Create `~/.browsing_tracker/` directory
  - Copy `config.template.json` → `~/.browsing_tracker/config.json` (if not already present)
  - Set `chmod 600 ~/.browsing_tracker/config.json`

- [ ] **SET-02** Create `setup.sh` — launchd service for Flask server
  - Write plist to `~/Library/LaunchAgents/com.browsingtracker.server.plist`
  - `launchctl load` the plist
  - Verify server is running via `/health` endpoint

- [ ] **SET-03** Create `setup.sh` — cron job installation
  - Daily:   `59 23 * * *`   → `python reporter.py --period daily`
  - Weekly:  `59 23 * * 0`   → `python reporter.py --period weekly`
  - Monthly: `59 23 28-31 * *` with last-day guard → `python reporter.py --period monthly`
  - Annual:  `59 23 31 12 *` → `python reporter.py --period annual`
  - Use absolute paths for both python and reporter.py

- [ ] **SET-04** Create `setup.sh` — Firefox extension install instructions
  - Print step-by-step: open about:debugging → Load Temporary Add-on → select manifest.json
  - Note: for permanent install, guide to about:config or signed extension

---

## Phase 7 — Testing & Validation

- [ ] **TST-01** Test extension: verify sessions are POSTed correctly
  - Open Firefox, browse a few sites, check server logs and browsing.db

- [ ] **TST-02** Test server: verify `/track` and `/health` endpoints
  - `curl -X POST http://127.0.0.1:7331/track -H "Content-Type: application/json" -d '{...}'`

- [ ] **TST-03** Test analyzer: verify Claude API call works and returns valid JSON
  - Run with a small manually-seeded dataset

- [ ] **TST-04** Test reporter: verify email is received and renders correctly
  - Run `python reporter.py --period daily` manually

- [ ] **TST-05** Test historical report: verify places.sqlite is read correctly
  - Click "Generate Historical Behavior Report" in the extension popup
  - Verify email is received with longitudinal analysis

- [ ] **TST-06** Test offline buffer: stop Flask server, browse in Firefox, restart server
  - Verify buffered records are flushed to DB after reconnection

---

## Execution Order

```
Phase 1 (Extension) → Phase 2 (Server) → Phase 3 (Analyzer)
    → Phase 4 (Reporter) → Phase 5 (Config) → Phase 6 (Setup) → Phase 7 (Test)
```

Phase 1 and Phase 2 can be developed in parallel.
Phase 3 depends on Phase 2 (needs the DB schema).
Phase 4 depends on Phase 3 (needs classify_with_claude).
Phase 6 depends on all previous phases.
