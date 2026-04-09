"""
list_profiles.py — Lists all Firefox profiles available on this machine.

Run this to find the exact profile folder name to put in config.json:
    python3 list_profiles.py
"""

import configparser
import os
import sqlite3
from datetime import datetime

PROFILES_DIR = os.path.expanduser("~/Library/Application Support/Firefox/Profiles")
PROFILES_INI = os.path.expanduser("~/Library/Application Support/Firefox/profiles.ini")


def get_db_stats(profile_path: str):
    """Return (total_visits, first_visit, last_visit) from a profile's places.sqlite."""
    db = os.path.join(profile_path, "places.sqlite")
    if not os.path.exists(db):
        return None, None, None
    try:
        import shutil
        tmp = "/tmp/places_list_copy.sqlite"
        shutil.copy2(db, tmp)
        conn = sqlite3.connect(tmp)
        row = conn.execute("""
            SELECT COUNT(*), MIN(visit_date), MAX(visit_date)
            FROM moz_historyvisits
        """).fetchone()
        conn.close()
        os.remove(tmp)
        total = row[0] or 0
        first = datetime.utcfromtimestamp(row[1] / 1_000_000).strftime("%Y-%m-%d") if row[1] else "—"
        last  = datetime.utcfromtimestamp(row[2] / 1_000_000).strftime("%Y-%m-%d") if row[2] else "—"
        return total, first, last
    except Exception:
        return None, None, None


def list_profiles():
    if not os.path.exists(PROFILES_DIR):
        print("Firefox Profiles directory not found.")
        print(f"Expected: {PROFILES_DIR}")
        return

    # Parse profiles.ini for human-readable names
    names = {}
    if os.path.exists(PROFILES_INI):
        parser = configparser.ConfigParser()
        parser.read(PROFILES_INI)
        for section in parser.sections():
            if section.startswith("Profile"):
                path = parser.get(section, "Path", fallback=None)
                name = parser.get(section, "Name", fallback=None)
                if path and name:
                    folder = os.path.basename(path)
                    names[folder] = name

    folders = sorted(
        f for f in os.listdir(PROFILES_DIR)
        if os.path.isdir(os.path.join(PROFILES_DIR, f))
    )

    if not folders:
        print("No Firefox profiles found.")
        return

    print()
    print("Firefox Profiles found on this machine:")
    print("─" * 72)
    print(f"  {'Profile Name':<25} {'Folder':<35} {'Visits':>8}  History")
    print("─" * 72)

    for folder in folders:
        profile_path = os.path.join(PROFILES_DIR, folder)
        display_name = names.get(folder, "(unnamed)")
        total, first, last = get_db_stats(profile_path)

        if total is not None:
            history = f"{first} → {last}" if first != "—" else "no history"
            visits  = f"{total:,}"
        else:
            history = "no places.sqlite"
            visits  = "—"

        print(f"  {display_name:<25} {folder:<35} {visits:>8}  {history}")

    print("─" * 72)
    print()
    print('Set "firefox_profile" in ~/.browsing_tracker/config.json to the')
    print("Folder name of the profile you want to track.")
    print()
    print('Example:')
    if folders:
        print(f'  "firefox_profile": "{folders[0]}"')
    print()


if __name__ == "__main__":
    list_profiles()
