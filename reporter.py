"""
reporter.py — HTML report builder + email sender.

Usage (called by cron):
    python reporter.py --period daily
    python reporter.py --period weekly
    python reporter.py --period monthly
    python reporter.py --period annual

The historical report is NOT triggered here; it is called on-demand via
server.py's /generate-historical endpoint (initiated from the extension popup).
"""

import argparse
import json
import os
import smtplib
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from analyzer import (
    classify_historical_with_claude,
    classify_with_claude,
    format_duration,
    get_sessions_for_period,
    read_firefox_history,
)

# ─── Config ───────────────────────────────────────────────────────────────────

DATA_DIR    = os.path.expanduser("~/.browsing_tracker")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(
            f"Config file not found at {CONFIG_PATH}. "
            "Copy config.template.json to ~/.browsing_tracker/config.json and fill it in."
        )
    with open(CONFIG_PATH) as f:
        config = json.load(f)
    required = ["email_to", "smtp_host", "smtp_port", "smtp_user", "smtp_password",
                "smtp_from", "anthropic_api_key"]
    missing = [k for k in required if not config.get(k)]
    if missing:
        raise ValueError(f"Missing required config keys: {', '.join(missing)}")
    return config

# ─── Date ranges ──────────────────────────────────────────────────────────────

def get_date_range(period: str) -> tuple[str, str, str]:
    """
    Returns (start_date, end_date, human_label) for the requested period.
    All dates as YYYY-MM-DD strings.
    """
    today = date.today()

    if period == "daily":
        return str(today), str(today), f"Daily Report — {today.strftime('%B %d, %Y')}"

    elif period == "weekly":
        # Monday of the current week → today
        start = today - timedelta(days=today.weekday())
        label = (f"Weekly Report — "
                 f"{start.strftime('%b %d')} to {today.strftime('%b %d, %Y')}")
        return str(start), str(today), label

    elif period == "monthly":
        start = today.replace(day=1)
        return str(start), str(today), f"Monthly Report — {today.strftime('%B %Y')}"

    elif period == "annual":
        start = today.replace(month=1, day=1)
        return str(start), str(today), f"Annual Report — {today.year}"

    raise ValueError(f"Unknown period: {period}")

# ─── HTML generation — incremental reports ────────────────────────────────────

# Colour palette for category bars (cycles if more categories than colours)
_COLOURS = ["#4F86C6", "#F4845F", "#63B995", "#E8A838", "#9B8EC4",
            "#E86C6C", "#4ECDC4", "#A8D8A8", "#F6AE2D", "#86BBD8"]


def _bar_html(pct: int, colour: str) -> str:
    return (
        f'<div style="background:#e8e8e8;border-radius:4px;height:10px;margin:4px 0 6px;">'
        f'<div style="background:{colour};width:{pct}%;height:10px;border-radius:4px;'
        f'min-width:4px;"></div></div>'
    )


def generate_html_report(analysis: dict, period_label: str,
                         start_date: str, end_date: str) -> str:
    total_time  = format_duration(analysis.get("total_seconds", 0))
    categories  = analysis.get("categories", [])
    insight     = analysis.get("behavioral_insight", "")
    total_secs  = max(analysis.get("total_seconds", 1), 1)

    categories_html = ""
    for i, cat in enumerate(categories):
        pct    = round(cat["total_seconds"] / total_secs * 100)
        colour = _COLOURS[i % len(_COLOURS)]
        time_s = format_duration(cat["total_seconds"])
        domains_preview = ", ".join(d["domain"] for d in cat.get("domains", [])[:5])

        categories_html += f"""
        <div style="margin-bottom:18px;">
          <div style="display:flex;justify-content:space-between;align-items:baseline;">
            <span style="font-weight:600;font-size:14px;">{cat['name']}</span>
            <span style="color:#666;font-size:13px;">{time_s} &nbsp;·&nbsp; {pct}%</span>
          </div>
          <div style="font-size:11px;color:#999;margin-bottom:2px;">{cat.get('description','')}</div>
          {_bar_html(pct, colour)}
          <div style="font-size:11px;color:#aaa;">{domains_preview}</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
             max-width:580px;margin:0 auto;padding:28px 24px;color:#1a1a1a;
             background:#ffffff;">

  <h2 style="margin:0 0 2px;font-size:20px;">{period_label}</h2>
  <p style="margin:0 0 20px;color:#999;font-size:13px;">{start_date} &rarr; {end_date}</p>

  <div style="background:#f5f5f5;border-radius:8px;padding:14px 18px;margin-bottom:24px;
              display:inline-block;">
    <span style="font-size:30px;font-weight:700;">{total_time}</span>
    <span style="color:#888;font-size:14px;margin-left:8px;">total browsing time</span>
  </div>

  <h3 style="margin:0 0 14px;font-size:15px;color:#444;">Behavioural Breakdown</h3>
  {categories_html}

  <div style="background:#f0f6ff;border-left:4px solid #4F86C6;padding:14px 16px;
              border-radius:0 8px 8px 0;margin-top:24px;">
    <h4 style="margin:0 0 6px;color:#2c5f8a;font-size:13px;">Behavioural Insight</h4>
    <p style="margin:0;line-height:1.65;color:#333;font-size:13px;">{insight}</p>
  </div>

  <p style="margin-top:28px;font-size:11px;color:#ccc;text-align:center;">
    Browsing Behavior Tracker &mdash; generated {datetime.now().strftime('%Y-%m-%d %H:%M')}
  </p>
</body>
</html>"""

# ─── HTML generation — historical report ──────────────────────────────────────

def generate_historical_html_report(analysis: dict) -> str:
    dr       = analysis.get("date_range", {})
    from_yr  = dr.get("from", "")
    to_yr    = dr.get("to", "")
    patterns = analysis.get("dominant_patterns", [])
    evo      = analysis.get("behavioral_evolution", "")
    insight  = analysis.get("insight", "")

    patterns_html = ""
    for i, p in enumerate(patterns):
        colour  = _COLOURS[i % len(_COLOURS)]
        domains = ", ".join(p.get("top_domains", [])[:6])
        patterns_html += f"""
        <div style="margin-bottom:16px;padding:12px 14px;
                    border-left:4px solid {colour};background:#fafafa;border-radius:0 6px 6px 0;">
          <div style="font-weight:600;font-size:14px;margin-bottom:3px;">{p['name']}</div>
          <div style="font-size:12px;color:#666;margin-bottom:4px;">{p.get('description','')}</div>
          <div style="font-size:11px;color:#aaa;">Top sites: {domains}</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
             max-width:580px;margin:0 auto;padding:28px 24px;color:#1a1a1a;
             background:#ffffff;">

  <h2 style="margin:0 0 2px;font-size:20px;">Historical Browsing Behaviour Report</h2>
  <p style="margin:0 0 6px;color:#999;font-size:13px;">{from_yr} &rarr; {to_yr}</p>
  <p style="margin:0 0 22px;font-size:11px;color:#bbb;">
    Based on visit frequency — duration tracking begins from today.
  </p>

  <h3 style="margin:0 0 12px;font-size:15px;color:#444;">Dominant Patterns</h3>
  {patterns_html}

  <div style="background:#fff8f0;border-left:4px solid #E8A838;padding:14px 16px;
              border-radius:0 8px 8px 0;margin-top:20px;">
    <h4 style="margin:0 0 6px;color:#a06010;font-size:13px;">How Your Behaviour Has Evolved</h4>
    <p style="margin:0;line-height:1.65;color:#333;font-size:13px;">{evo}</p>
  </div>

  <div style="background:#f0f6ff;border-left:4px solid #4F86C6;padding:14px 16px;
              border-radius:0 8px 8px 0;margin-top:16px;">
    <h4 style="margin:0 0 6px;color:#2c5f8a;font-size:13px;">Overall Insight</h4>
    <p style="margin:0;line-height:1.65;color:#333;font-size:13px;">{insight}</p>
  </div>

  <p style="margin-top:28px;font-size:11px;color:#ccc;text-align:center;">
    Browsing Behavior Tracker &mdash; generated {datetime.now().strftime('%Y-%m-%d %H:%M')}
  </p>
</body>
</html>"""

# ─── Email sender ─────────────────────────────────────────────────────────────

def send_email(subject: str, html_body: str, config: dict) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = config["smtp_from"]
    msg["To"]      = config["email_to"]
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL(config["smtp_host"], int(config["smtp_port"])) as server:
        server.login(config["smtp_user"], config["smtp_password"])
        server.sendmail(config["smtp_from"], config["email_to"], msg.as_string())

# ─── Report runners ───────────────────────────────────────────────────────────

def run_report(period: str) -> None:
    """Run a scheduled incremental report (daily / weekly / monthly / annual)."""
    config = load_config()
    start_date, end_date, period_label = get_date_range(period)

    print(f"[{datetime.now()}] Fetching sessions for {period_label}…")
    sessions = get_sessions_for_period(start_date, end_date)

    if not sessions:
        print(f"No browsing data found for {period_label}. Skipping.")
        return

    print(f"  {len(sessions)} sessions found. Calling Claude…")
    analysis = classify_with_claude(sessions, period_label)

    html    = generate_html_report(analysis, period_label, start_date, end_date)
    subject = f"Browsing Report: {period_label}"

    send_email(subject, html, config)
    print(f"  Report sent to {config['email_to']}.")


def run_historical_report(config=None) -> None:
    """
    Run the on-demand historical report.
    Called by server.py when the extension popup button is clicked.
    Can also be called directly for testing.
    """
    if config is None:
        config = load_config()

    print(f"[{datetime.now()}] Reading Firefox history…")
    history_data = read_firefox_history()

    if not history_data:
        raise RuntimeError(
            "Could not locate Firefox places.sqlite. "
            "Make sure Firefox is installed and has been used at least once."
        )

    print(f"  {len(history_data)} domains found. Calling Claude…")
    analysis = classify_historical_with_claude(history_data)

    html = generate_historical_html_report(analysis)
    send_email("Historical Browsing Behavior Report", html, config)
    print(f"  Historical report sent to {config['email_to']}.")

# ─── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send a browsing behaviour report.")
    parser.add_argument(
        "--period",
        choices=["daily", "weekly", "monthly", "annual"],
        required=True,
        help="Report period to generate and send.",
    )
    args = parser.parse_args()
    run_report(args.period)
