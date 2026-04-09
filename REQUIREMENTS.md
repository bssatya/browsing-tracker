# Browsing Behavior Tracker — Requirements Document

## 1. Purpose

Build a personal tool that tracks browsing activity in Firefox, analyzes behavioral patterns using an LLM, and delivers automated email reports on a daily, weekly, monthly, and annual basis. The goal is self-awareness: understanding how time online is being spent — learning, passive consumption, entertainment, work, etc. — without any pre-imposed category definitions.

---

## 2. Functional Requirements

### 2.1 Browsing Data Collection

| ID | Requirement |
|----|-------------|
| F-01 | The system MUST track the time spent on each browser tab in real time |
| F-02 | For each tab session, the system MUST record: URL, page title, domain, session start timestamp, session end timestamp, and duration in seconds |
| F-03 | The system MUST detect and handle tab switches, tab closures, window focus loss (alt-tab, minimize), and URL changes within the same tab |
| F-04 | The system MUST NOT record sessions shorter than 5 seconds (noise filtering) |
| F-05 | The system MUST NOT track private/incognito browsing sessions |
| F-06 | The system MUST NOT track browser-internal pages (about:*, moz-extension:*, chrome:*) |
| F-07 | If the local server is unavailable, the extension MUST buffer data in browser.storage.local and retry every 30 seconds |

### 2.2 Historical Data (On-Demand)

| ID | Requirement |
|----|-------------|
| F-08 | The Firefox extension toolbar popup MUST include a "Generate Historical Behavior Report" button |
| F-09 | When the user clicks that button, the system MUST read ALL historical browsing data from Firefox's places.sqlite database and trigger a report |
| F-10 | The historical report MUST be based on visit frequency, visit count, and temporal trends — NOT duration (duration data is not available in places.sqlite) |
| F-11 | The historical report MUST cover the full available history, grouped and analyzed for long-term behavioral trends |
| F-12 | The historical report can be triggered any number of times — there is no one-time flag or restriction |
| F-13 | The system MUST handle large historical datasets by aggregating data (domain + visit count + sample titles + date range) before sending to the LLM |

### 2.3 Behavioral Analysis

| ID | Requirement |
|----|-------------|
| F-14 | The system MUST send browsing data to Claude (LLM) for behavioral classification |
| F-15 | Claude MUST NOT be given pre-defined categories. It MUST derive its own categories based on what it observes in the data |
| F-16 | For the daily report, Claude receives that day's data and classifies it independently |
| F-17 | For the weekly report, Claude receives the full 7 days of data in a single batch and re-classifies from scratch — daily category names are NOT carried over |
| F-18 | For monthly and annual reports, the same re-classification-from-scratch approach applies (full period data sent in one batch) |
| F-19 | Claude MUST return: category names, category descriptions, domains per category, time per category, and a behavioral insight paragraph |
| F-20 | For the historical report, Claude MUST return longitudinal trends: how behavior has shifted over time, dominant patterns, notable changes by year/period |

### 2.4 Email Reports

| ID | Requirement |
|----|-------------|
| F-21 | The system MUST send a daily email report at 11:59 PM every day |
| F-22 | The system MUST send a weekly email report at 11:59 PM every Sunday covering Mon–Sun |
| F-23 | The system MUST send a monthly email report at 11:59 PM on the last day of each month |
| F-24 | The system MUST send an annual email report at 11:59 PM on December 31 |
| F-25 | The historical report is triggered on-demand via the extension popup button and sent immediately to email |
| F-26 | All reports MUST be delivered as formatted HTML emails |
| F-27 | Each report MUST include: total time/visits, behavioral breakdown by Claude-defined categories, a visual progress bar per category, and Claude's behavioral insight paragraph |
| F-28 | The system MUST support Gmail SMTP for sending emails |

### 2.5 Scheduling & Automation

| ID | Requirement |
|----|-------------|
| F-29 | The local Flask server MUST start automatically on system login (via launchd on macOS) |
| F-30 | All report schedules MUST be automated via cron jobs — no manual trigger required |
| F-31 | A single setup script MUST handle all installation: dependencies, launchd service, cron jobs, and config scaffolding |

---

## 3. Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NF-01 | All browsing data MUST remain local on the user's machine. Nothing is sent to external servers except anonymized domain+title data sent to the Claude API for classification |
| NF-02 | The Flask server MUST only bind to 127.0.0.1 (localhost) — never exposed to the network |
| NF-03 | The system MUST use Claude Haiku (cheapest model) to minimize API costs. Estimated cost: $0.01–$0.05/day |
| NF-04 | The extension MUST NOT noticeably slow down browser performance |
| NF-05 | The local SQLite database MUST store all data indefinitely — no retention limit or archival policy |
| NF-06 | Setup MUST be completable by a non-developer following the README |

---

## 4. Data Requirements

### 4.1 Extension-tracked session record (stored in local SQLite)
```
id              INTEGER  — auto increment primary key
url             TEXT     — full URL of the page
title           TEXT     — page title at time of visit
domain          TEXT     — hostname only (e.g. youtube.com)
timestamp       TEXT     — ISO 8601 session start time
duration_secs   INTEGER  — time spent on this tab in seconds
date            TEXT     — YYYY-MM-DD (for easy date range queries)
```

### 4.2 Historical record (read-only from Firefox places.sqlite)
```
url             TEXT     — full URL
title           TEXT     — page title
visit_count     INTEGER  — total times visited
last_visit      TEXT     — timestamp of last visit
first_visit     TEXT     — timestamp of first ever visit
```

---

## 5. Constraints & Assumptions

- The system runs on **macOS** (launchd for services, standard Firefox profile path)
- Firefox must be the primary browser (Chrome/Safari not in scope)
- The user has a **Claude API key** (Anthropic)
- The user has a **Gmail account** for sending reports (or configures another SMTP)
- Python 3.9+ is available on the system
- The extension is installed in **Firefox Developer Edition or standard Firefox** via about:debugging (no store submission)
- places.sqlite is copied before reading to avoid SQLite locking issues when Firefox is open

---

## 6. Out of Scope

- Mobile browser tracking
- Cross-device sync
- Real-time dashboard or web UI
- Chrome / Safari / Edge support
- Cloud storage of browsing data
- Categorization of HTTPS-intercepted content (only URL + title used)
