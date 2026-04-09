# Browsing Behavior Tracker

A personal Firefox tool that tracks how you spend time online, uses Claude (LLM) to analyze your browsing patterns, and emails you behavioral reports on a daily, weekly, monthly, and annual basis.

No pre-defined categories. Claude looks at your actual data and decides what the meaningful patterns are.

---

## Demo

[![Watch the demo](https://img.youtube.com/vi/EW5BPC3ORbU/0.jpg)](https://youtu.be/EW5BPC3ORbU)

---

## What It Does

- **Tracks time** spent on every browser tab in real time (exact seconds, not estimated)
- **Classifies behavior** using Claude — categories emerge from your data, not from a fixed list
- **Emails you reports** automatically on a schedule
- **Handles YouTube correctly** — distinguishes a Python tutorial from a fails compilation using the page title
- **Reads your full Firefox history** on demand for a longitudinal behavioral analysis

### Sample daily report output

```
Daily Report — April 10, 2026

Total browsing time: 5h 12m

Deep Technical Learning          2h 14m  ████████████  43%
  youtube.com, docs.python.org, github.com

Passive Entertainment            1h 48m  ██████████    35%
  youtube.com (shorts/compilations), instagram.com

Communication & Admin              44m   ████          14%
  gmail.com, notion.so

News & Current Affairs             26m   ██             8%
  substack.com, medium.com

Behavioral Insight:
You dedicated 43% of your browsing time to structured technical learning today,
with a clear focus on Python async patterns and ML fundamentals. However, a
significant 35% was passive entertainment, concentrated in the 10–11 PM window,
suggesting late-night context switching away from productive work...
```

---

## Architecture

```
┌─────────────────────────────────────────┐
│  Firefox Extension (background.js)      │
│  Tracks active tab time via tab events  │
│  POSTs sessions to local server         │
└──────────────────┬──────────────────────┘
                   │ HTTP POST localhost:7331
┌──────────────────▼──────────────────────┐
│  Flask Server (server.py)               │
│  Receives + stores sessions to SQLite   │
│  Runs as launchd service (auto-start)   │
└──────────────────┬──────────────────────┘
                   │ reads SQLite / places.sqlite
┌──────────────────▼──────────────────────┐
│  Analyzer + Reporter                    │
│  Aggregates data → Claude API           │
│  Claude defines its own categories      │
│  Generates HTML email → Gmail SMTP      │
│  Triggered by cron on schedule          │
└─────────────────────────────────────────┘
```

---

## File Structure

```
browsing_tracker/
├── extension/
│   ├── manifest.json        Firefox extension manifest (MV2)
│   ├── background.js        Tab time tracking — all browser events
│   ├── popup.html           Toolbar button popup UI
│   └── popup.js             Triggers on-demand historical report
├── server.py                Flask server on 127.0.0.1:7331
├── analyzer.py              Data aggregation + Claude API calls
├── reporter.py              HTML report builder + Gmail SMTP sender
├── list_profiles.py         Helper: lists your Firefox profiles
├── setup.sh                 One-command setup script
├── config.template.json     Config template (copy to ~/.browsing_tracker/)
├── requirements.txt         Python dependencies
├── REQUIREMENTS.md          Full functional + non-functional requirements
├── DESIGN.md                Architecture and component design doc
└── TASKS.md                 Development task checklist
```

**Runtime data** (not in repo, lives at `~/.browsing_tracker/`):
```
~/.browsing_tracker/
├── config.json              Your credentials (email, API key, Firefox profile)
├── browsing.db              SQLite: all extension-tracked sessions
└── scripts/                 Python scripts copied here for launchd access
```

---

## Prerequisites

- **macOS** (launchd is macOS-specific; Linux requires minor adaptation)
- **Firefox** (standard or Developer Edition)
- **Python 3.9+**
- **Gmail account** with 2-Step Verification enabled
- **Anthropic API key** — get one at [console.anthropic.com](https://console.anthropic.com)

---

## Installation

### Step 1 — Clone and run setup

```bash
git clone https://github.com/bssatya/browsing-tracker
cd browsing-tracker
bash setup.sh
```

`setup.sh` does the following automatically:
- Checks Python 3.9+
- Installs `flask` and `anthropic` via pip
- Creates `~/.browsing_tracker/` and scaffolds `config.json`
- Copies Python scripts to `~/.browsing_tracker/scripts/` (required for launchd access)
- Installs and starts a **launchd service** so the Flask server auto-starts on every login
- Installs **4 cron jobs** for scheduled email reports

### Step 2 — Find your Firefox profile

```bash
python3 list_profiles.py
```

Output:
```
Firefox Profiles found on this machine:
────────────────────────────────────────────────────────────────────────
  Profile Name     Folder                    Visits    History
────────────────────────────────────────────────────────────────────────
  default-release  abc12def.default-release   2,833    2025-04-26 → 2026-04-09
  work             xyz99abc.work-profile        412    2025-09-01 → 2026-04-09
────────────────────────────────────────────────────────────────────────
```

Note the **Folder** name of the profile you want to track.

### Step 3 — Configure credentials

Edit `~/.browsing_tracker/config.json`:

```json
{
  "email_to":          "you@gmail.com",
  "smtp_from":         "you@gmail.com",
  "smtp_host":         "smtp.gmail.com",
  "smtp_port":         465,
  "smtp_user":         "you@gmail.com",
  "smtp_password":     "abcd efgh ijkl mnop",
  "anthropic_api_key": "sk-ant-api03-...",
  "firefox_profile":   "abc12def.default-release"
}
```

**`smtp_password`** — This is a Gmail App Password, not your account password.  
Generate one at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)  
(Requires 2-Step Verification to be enabled on your Gmail account)

**`anthropic_api_key`** — Get from [console.anthropic.com](https://console.anthropic.com) → API Keys

**`firefox_profile`** — The folder name from `list_profiles.py`. Set to `null` to auto-detect.

### Step 4 — Install the Firefox extension

1. Open Firefox → go to `about:debugging#/runtime/this-firefox`
2. Click **"Load Temporary Add-on..."**
3. Navigate to the `extension/` folder and select `manifest.json`
4. The extension appears in the toolbar — tracking is now active

> **Note:** Temporary add-ons are removed when Firefox restarts. Re-load via `about:debugging` after each restart, or sign and install permanently (see [Extension Workshop](https://extensionworkshop.com/documentation/publish/signing-and-distribution-overview/)).

---

## How Reports Work

### Scheduled reports (automatic)

| Report | When sent | Data sent to Claude |
|--------|-----------|---------------------|
| Daily | 11:59 PM every day | That day's sessions |
| Weekly | 11:59 PM every Sunday | Full week re-classified from scratch |
| Monthly | 11:58 PM last day of month | Full month re-classified from scratch |
| Annual | 11:59 PM December 31 | Full year re-classified from scratch |

For weekly, monthly, and annual reports, all data is sent to Claude in a single batch — categories are derived fresh each time, not carried over from daily reports.

### On-demand historical report

Click the extension toolbar icon → **"Generate Historical Behavior Report"**

This reads your complete Firefox history from `places.sqlite` and sends it to Claude for a longitudinal behavioral analysis — what patterns dominated, how behavior shifted year over year, what your browsing says about your interests over time.

> Historical data is based on **visit frequency only** (no duration). Duration tracking begins from when the extension is installed.

---

## How Claude Classifies Your Browsing

Claude receives a list of domains with time spent and sample page titles. It is given **no pre-defined categories** — it derives its own based on what it sees.

For example, given these two YouTube entries:
- `"CS50 Week 4: Memory — Harvard"` → **Deep Technical Learning**
- `"Top 10 Fails Compilation 2026"` → **Passive Entertainment**

Claude reads the page title and makes the judgment. The same domain can appear in different categories depending on what you were actually doing there.

For weekly and monthly reports, Claude sees the full period's data at once and re-derives categories across the entire dataset — so a pattern that appears across multiple days becomes more visible and better named.

---

## Running Reports Manually

```bash
cd ~/.browsing_tracker/scripts

# Generate and send a report for any period
python3 reporter.py --period daily
python3 reporter.py --period weekly
python3 reporter.py --period monthly
python3 reporter.py --period annual
```

---

## Verifying the Setup

```bash
# Check the server is running
curl http://127.0.0.1:7331/health

# Check sessions are being stored
python3 -c "
import sqlite3
conn = sqlite3.connect('/Users/$USER/.browsing_tracker/browsing.db')
count = conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
print(f'{count} sessions in database')
conn.close()
"

# Check cron jobs are installed
crontab -l | grep browsing-tracker

# Check launchd service is loaded
launchctl list | grep browsingtracker
```

---

## Data & Privacy

- All browsing data is stored **locally** on your machine in `~/.browsing_tracker/browsing.db`
- The only data sent externally is domain names + page titles, sent to the **Anthropic API** for classification
- The Flask server binds to `127.0.0.1` only — it is never exposed to the network
- `config.json` is created with `chmod 600` — only you can read it
- Private/Incognito tabs are never saved to Firefox history and are not tracked

---

## Changing Your Firefox Profile

You can switch the tracked profile at any time by editing `firefox_profile` in `~/.browsing_tracker/config.json`.

### Step 1 — Find the new profile's folder name

```bash
python3 list_profiles.py
```

### Step 2 — Update config.json

```json
"firefox_profile": "newprofilefolder.profile-name"
```

### Step 3 — Nothing else needed

No restarts required. Each component picks up the change automatically:

| Component | Impact | Detail |
|---|---|---|
| **Historical report** | Immediate | `config.json` is read fresh on every button click |
| **Flask server** | None | Doesn't cache the profile — reads at request time |
| **Daily / weekly / monthly / annual reports** | None | These use `browsing.db` (extension-tracked data), not `places.sqlite` |
| **Extension** | None | Tracks whatever tab is active — unaffected by profile setting |

The `firefox_profile` setting **only affects the historical report** (which reads `places.sqlite`). Ongoing time tracking via the extension is profile-agnostic — it records sessions regardless of which Firefox profile is active in the browser.

### After switching profiles

- Click the extension toolbar icon → **"Generate Historical Behavior Report"** to immediately get a historical analysis of the new profile
- Ongoing incremental reports (daily, weekly, etc.) will continue uninterrupted using the extension-tracked data in `browsing.db`

---

## Troubleshooting

**Server not starting after login**
```bash
cat ~/.browsing_tracker/server_error.log
launchctl list | grep browsingtracker
```

**Extension not sending data**  
Open `about:debugging` in Firefox → find the extension → click **Inspect** → check the Console tab for errors.

**No email received**  
- Verify `smtp_password` is a Gmail App Password (not your Gmail login password)
- Ensure 2-Step Verification is enabled on the Gmail account
- Run `python3 reporter.py --period daily` manually and check the error output

**Wrong Firefox profile being read**  
Run `python3 list_profiles.py` to see all profiles, then update `firefox_profile` in `~/.browsing_tracker/config.json`.

**Re-run setup after updating scripts**  
If you pull updates from git, re-run `bash setup.sh` to copy updated scripts to `~/.browsing_tracker/scripts/`.

---

## Stopping and Uninstalling

### Stop the server temporarily

```bash
launchctl unload ~/Library/LaunchAgents/com.browsingtracker.server.plist
```

To start it again:

```bash
launchctl load ~/Library/LaunchAgents/com.browsingtracker.server.plist
```

### Remove everything permanently

```bash
# Stop and remove the launchd service
launchctl unload ~/Library/LaunchAgents/com.browsingtracker.server.plist
rm ~/Library/LaunchAgents/com.browsingtracker.server.plist

# Remove all cron jobs
crontab -l | grep -v "browsing-tracker" | crontab -

# Remove all data and scripts (optional — this deletes your browsing history database)
rm -rf ~/.browsing_tracker
```

To also remove the Firefox extension: open `about:debugging#/runtime/this-firefox` → find the extension → click **Remove**.

---

## Cost

Uses **Claude Haiku** (Anthropic's cheapest model).

| Usage | Estimated cost |
|-------|---------------|
| Daily report | ~$0.01 – $0.03 |
| Weekly report | ~$0.03 – $0.08 |
| Monthly report | ~$0.05 – $0.15 |
| Annual report | ~$0.10 – $0.30 |
| Historical report (one-off) | ~$0.05 – $0.20 |
| **Per month total** | **~$0.50 – $2.00** |
