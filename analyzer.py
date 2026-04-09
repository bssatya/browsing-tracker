"""
analyzer.py — Data aggregation and Claude API calls.

Two analysis paths:
  1. Incremental  — extension-tracked sessions from browsing.db
                    (has duration, used for daily/weekly/monthly/annual reports)
  2. Historical   — visit frequency data from Firefox's places.sqlite
                    (no duration, used for the on-demand historical report)

Claude is given no pre-defined categories in either path.
It derives its own categories from the data it receives.
"""

import glob
import json
import os
import shutil
import sqlite3
from datetime import datetime

import anthropic
from typing import List, Optional

# ─── Paths ────────────────────────────────────────────────────────────────────

DATA_DIR = os.path.expanduser("~/.browsing_tracker")
DB_PATH  = os.path.join(DATA_DIR, "browsing.db")

# ─── Utilities ────────────────────────────────────────────────────────────────

def format_duration(seconds: int) -> str:
    """Convert seconds to a human-readable string: 2h 14m, 45m 30s, 12s."""
    if seconds >= 3600:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h {m}m" if m else f"{h}h"
    elif seconds >= 60:
        m = seconds // 60
        s = seconds % 60
        return f"{m}m {s}s" if s else f"{m}m"
    return f"{seconds}s"


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of a Claude response string."""
    start = text.find("{")
    end   = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in Claude response")
    return json.loads(text[start:end])


def _claude_client() -> anthropic.Anthropic:
    """Build an Anthropic client, reading the API key from config."""
    config_path = os.path.join(DATA_DIR, "config.json")
    with open(config_path) as f:
        config = json.load(f)
    return anthropic.Anthropic(api_key=config["anthropic_api_key"])

# ═══════════════════════════════════════════════════════════════════════════════
# PATH A — Incremental (extension-tracked sessions from browsing.db)
# ═══════════════════════════════════════════════════════════════════════════════

def get_sessions_for_period(start_date: str, end_date: str) -> List[dict]:
    """
    Return all sessions between start_date and end_date (YYYY-MM-DD, inclusive).
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        """
        SELECT url, title, domain, timestamp, duration_secs, date
        FROM   sessions
        WHERE  date >= ? AND date <= ?
        ORDER  BY timestamp
        """,
        (start_date, end_date),
    )
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _aggregate_by_domain(sessions: List[dict]) -> List[dict]:
    """
    Collapse sessions into per-domain summaries, sorted by total time (desc).
    Domains with less than 30 seconds total are dropped as noise.
    """
    domains: dict[str, dict] = {}
    for s in sessions:
        d = s["domain"] or "unknown"
        if d not in domains:
            domains[d] = {"domain": d, "total_seconds": 0, "visit_count": 0, "titles": []}
        domains[d]["total_seconds"] += s["duration_secs"]
        domains[d]["visit_count"]   += 1
        title = (s.get("title") or "").strip()
        if title and title not in domains[d]["titles"] and len(domains[d]["titles"]) < 8:
            domains[d]["titles"].append(title)

    filtered = [v for v in domains.values() if v["total_seconds"] >= 30]
    return sorted(filtered, key=lambda x: x["total_seconds"], reverse=True)


def classify_with_claude(sessions: List[dict], period_label: str) -> dict:
    """
    Send aggregated session data to Claude Haiku.
    Claude decides its own behavioral categories — no pre-defined buckets.

    Returns:
        {
          "categories": [
            {
              "name": str,
              "description": str,
              "total_seconds": int,
              "domains": [{"domain": str, "time_spent": str, "time_seconds": int}]
            }
          ],
          "behavioral_insight": str,
          "total_seconds": int
        }
    """
    aggregated   = _aggregate_by_domain(sessions)
    total_seconds = sum(s["duration_secs"] for s in sessions)

    # Build the domain payload for Claude (cap at 60 domains to stay within token limits)
    domain_payload = [
        {
            "domain":        d["domain"],
            "time_spent":    format_duration(d["total_seconds"]),
            "time_seconds":  d["total_seconds"],
            "visits":        d["visit_count"],
            "sample_titles": d["titles"],
        }
        for d in aggregated[:60]
    ]

    prompt = f"""I have browsing data for {period_label}.
Total browsing time tracked: {format_duration(total_seconds)}.

Below is a list of domains visited, with time spent, visit count, and sample page titles:

{json.dumps(domain_payload, indent=2)}

Please analyse this browsing behaviour and do the following:

1. Group these domains into meaningful behavioural categories that YOU think best \
describe this person's internet usage patterns. Do NOT use pre-defined or generic \
bucket names — derive categories that genuinely reflect what you see in the data. \
For example, if the person watches a lot of coding tutorials, call it something \
specific, not just "Learning".

2. For each category, list the domains it contains and their total time.

3. Write a short behavioural insight paragraph (3–5 sentences) describing what \
you observe about this person's internet habits for this period.

Return ONLY a JSON object with exactly this structure (no extra text):
{{
  "categories": [
    {{
      "name": "category name",
      "description": "one-sentence description of what this category represents",
      "total_seconds": 1234,
      "domains": [
        {{"domain": "example.com", "time_spent": "30m", "time_seconds": 1800}}
      ]
    }}
  ],
  "behavioral_insight": "paragraph here",
  "total_seconds": {total_seconds}
}}"""

    client = _claude_client()
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    return _extract_json(message.content[0].text)

# ═══════════════════════════════════════════════════════════════════════════════
# PATH B — Historical (Firefox places.sqlite, visit frequency only)
# ═══════════════════════════════════════════════════════════════════════════════

def _find_firefox_places_sqlite(profile_folder: Optional[str] = None) -> Optional[str]:
    """
    Locate places.sqlite for a Firefox profile on macOS.

    If profile_folder is given (e.g. 'abc12def.default-release'), use that exact
    folder under ~/Library/Application Support/Firefox/Profiles/.
    Otherwise auto-select the first *.default-release or *.default profile found.
    """
    base = os.path.expanduser("~/Library/Application Support/Firefox/Profiles")

    if profile_folder:
        path = os.path.join(base, profile_folder, "places.sqlite")
        if os.path.exists(path):
            return path
        raise FileNotFoundError(
            f"Firefox profile '{profile_folder}' not found at {base}.\n"
            "Run 'python3 list_profiles.py' to see available profiles."
        )

    # Auto-detect: prefer *.default-release, fall back to *.default
    candidates = (
        glob.glob(os.path.join(base, "*.default-release", "places.sqlite")) +
        glob.glob(os.path.join(base, "*.default",         "places.sqlite"))
    )
    return candidates[0] if candidates else None


def read_firefox_history() -> Optional[List[dict]]:
    """
    Read ALL historical browsing data from Firefox's places.sqlite.

    The profile to read from is taken from ~/.browsing_tracker/config.json
    (key: "firefox_profile"). If that key is null or absent, the first
    default-release profile is used.

    Returns a list of domain-level aggregates:
        [
          {
            "domain": str,
            "visit_count": int,
            "sample_titles": [str],
            "first_visit_year": int,
            "last_visit_year": int,
          }
        ]
    Returns None if places.sqlite cannot be found.
    """
    # Read the configured profile (may be None → auto-detect)
    config_path = os.path.join(DATA_DIR, "config.json")
    profile_folder = None
    if os.path.exists(config_path):
        with open(config_path) as f:
            cfg = json.load(f)
        profile_folder = cfg.get("firefox_profile") or None

    original = _find_firefox_places_sqlite(profile_folder)
    if not original:
        return None

    # Copy to /tmp to avoid locking a live Firefox database
    tmp_copy = "/tmp/places_tracker_copy.sqlite"
    shutil.copy2(original, tmp_copy)

    conn = sqlite3.connect(tmp_copy)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # moz_historyvisits.visit_date is stored in microseconds since Unix epoch
    c.execute("""
        SELECT
            p.url,
            p.title,
            p.visit_count,
            MIN(v.visit_date) AS first_visit_us,
            MAX(v.visit_date) AS last_visit_us
        FROM  moz_places p
        JOIN  moz_historyvisits v ON v.place_id = p.id
        WHERE p.url NOT LIKE 'about:%'
          AND p.url NOT LIKE 'moz-extension:%'
          AND p.url NOT LIKE 'chrome:%'
          AND p.visit_count > 0
        GROUP BY p.id
        ORDER BY p.visit_count DESC
    """)
    rows = c.fetchall()

    # Per-domain aggregate
    domains: dict[str, dict] = {}
    for row in rows:
        try:
            from urllib.parse import urlparse
            domain = urlparse(row["url"]).hostname or "unknown"
        except Exception:
            continue

        first_year = datetime.utcfromtimestamp(row["first_visit_us"] / 1_000_000).year
        last_year  = datetime.utcfromtimestamp(row["last_visit_us"]  / 1_000_000).year

        if domain not in domains:
            domains[domain] = {
                "domain":         domain,
                "visit_count":    0,
                "sample_titles":  [],
                "first_visit_year": first_year,
                "last_visit_year":  last_year,
                "visits_by_year": {},
            }

        domains[domain]["visit_count"]    += row["visit_count"]
        domains[domain]["first_visit_year"] = min(domains[domain]["first_visit_year"], first_year)
        domains[domain]["last_visit_year"]  = max(domains[domain]["last_visit_year"],  last_year)

        title = (row["title"] or "").strip()
        if title and title not in domains[domain]["sample_titles"] and \
                len(domains[domain]["sample_titles"]) < 5:
            domains[domain]["sample_titles"].append(title)

    conn.close()
    os.remove(tmp_copy)

    total_visits = sum(d["visit_count"] for d in domains.values())

    # Drop domains with < 0.5% of total visits (noise)
    threshold = max(1, int(total_visits * 0.005))
    result = [d for d in domains.values() if d["visit_count"] >= threshold]
    return sorted(result, key=lambda x: x["visit_count"], reverse=True)


def classify_historical_with_claude(history_data: List[dict]) -> dict:
    """
    Send full historical domain data to Claude for longitudinal behavioural analysis.
    Claude derives its own patterns — no pre-defined categories.

    Returns:
        {
          "dominant_patterns": [{"name": str, "description": str, "top_domains": [str]}],
          "behavioral_evolution": str,
          "insight": str,
          "date_range": {"from": str, "to": str}
        }
    """
    total_visits = sum(d["visit_count"] for d in history_data)
    first_year   = min(d["first_visit_year"] for d in history_data)
    last_year    = max(d["last_visit_year"]  for d in history_data)

    # Cap at 80 domains to stay within token limits; group rest as "Other"
    top_domains   = history_data[:80]
    other_visits  = sum(d["visit_count"] for d in history_data[80:])

    domain_payload = [
        {
            "domain":           d["domain"],
            "total_visits":     d["visit_count"],
            "pct_of_total":     round(d["visit_count"] / total_visits * 100, 1),
            "years_active":     f"{d['first_visit_year']}–{d['last_visit_year']}",
            "sample_titles":    d["sample_titles"],
        }
        for d in top_domains
    ]
    if other_visits:
        domain_payload.append({
            "domain":        "other (combined)",
            "total_visits":  other_visits,
            "pct_of_total":  round(other_visits / total_visits * 100, 1),
            "years_active":  f"{first_year}–{last_year}",
            "sample_titles": [],
        })

    prompt = f"""I have the full Firefox browsing history for a person, spanning {first_year} to {last_year}.
Total recorded visits: {total_visits:,}.

Here is the data — top domains by visit count, with percentage of total visits, \
years when the domain was active, and sample page titles:

{json.dumps(domain_payload, indent=2)}

Note: this data is based on visit frequency only — time spent per page is not available \
for historical data. Duration tracking begins going forward.

Please perform a longitudinal behavioural analysis:

1. Identify the dominant behavioural patterns visible across the full history. \
   Group domains into patterns YOU define — don't use generic labels. \
   Let the actual content guide the names.

2. Describe how this person's browsing behaviour has evolved over the years \
   (e.g. shifts in focus, new interests emerging, old ones fading).

3. Write an insight paragraph (4–6 sentences) summarising what this history \
   reveals about the person's internet habits, interests, and tendencies.

Return ONLY a JSON object with exactly this structure (no extra text):
{{
  "dominant_patterns": [
    {{
      "name": "pattern name",
      "description": "what this pattern represents",
      "top_domains": ["domain1.com", "domain2.com"]
    }}
  ],
  "behavioral_evolution": "paragraph describing how behaviour changed over the years",
  "insight": "overall insight paragraph",
  "date_range": {{"from": "{first_year}", "to": "{last_year}"}}
}}"""

    client = _claude_client()
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    return _extract_json(message.content[0].text)
