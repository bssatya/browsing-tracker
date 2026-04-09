#!/usr/bin/env bash
# setup.sh — one-command setup for Browsing Behavior Tracker
# Run once from the project directory: bash setup.sh
set -e

# ─── Colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
fail() { echo -e "${RED}✗${NC} $*"; exit 1; }
step() { echo -e "\n${YELLOW}▶${NC} $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$HOME/.browsing_tracker"
CONFIG="$DATA_DIR/config.json"
PLIST_PATH="$HOME/Library/LaunchAgents/com.browsingtracker.server.plist"
# Scripts are copied to DATA_DIR so launchd can access them
# (macOS restricts launchd agents from accessing Documents/)
SCRIPTS_DIR="$DATA_DIR/scripts"
REPORTER="$SCRIPTS_DIR/reporter.py"

# ─── Step 1: Python version check ─────────────────────────────────────────────
step "Checking Python version…"
PYTHON=$(command -v python3 || true)
[[ -z "$PYTHON" ]] && fail "python3 not found. Install Python 3.9+ and retry."
VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
MAJOR=$(echo "$VERSION" | cut -d. -f1)
MINOR=$(echo "$VERSION" | cut -d. -f2)
[[ "$MAJOR" -lt 3 || ("$MAJOR" -eq 3 && "$MINOR" -lt 9) ]] && \
  fail "Python 3.9+ required (found $VERSION)."
ok "Python $VERSION"

# ─── Step 2: Install Python dependencies ──────────────────────────────────────
step "Installing Python dependencies…"
"$PYTHON" -m pip install -q --upgrade pip
"$PYTHON" -m pip install -q -r "$SCRIPT_DIR/requirements.txt"
ok "Dependencies installed"

# ─── Step 3: Create data directory and config ─────────────────────────────────
step "Setting up data directory and copying scripts…"
mkdir -p "$DATA_DIR"
mkdir -p "$SCRIPTS_DIR"
ok "Created $DATA_DIR"

# Copy Python scripts to DATA_DIR/scripts so launchd can read them
# (macOS TCC blocks launchd agents from accessing ~/Documents)
cp "$SCRIPT_DIR/server.py"       "$SCRIPTS_DIR/"
cp "$SCRIPT_DIR/analyzer.py"     "$SCRIPTS_DIR/"
cp "$SCRIPT_DIR/reporter.py"     "$SCRIPTS_DIR/"
cp "$SCRIPT_DIR/list_profiles.py" "$SCRIPTS_DIR/"
ok "Scripts copied to $SCRIPTS_DIR"

if [[ ! -f "$CONFIG" ]]; then
  cp "$SCRIPT_DIR/config.template.json" "$CONFIG"
  chmod 600 "$CONFIG"
  warn "Config created at $CONFIG"
  warn "IMPORTANT: Edit that file and fill in your email + API keys before using the tool."
else
  ok "Config already exists at $CONFIG"
fi

# ─── Step 4: launchd service for the Flask server ─────────────────────────────
step "Installing launchd service for the local server…"

# Unload existing service if present
if launchctl list | grep -q "com.browsingtracker.server" 2>/dev/null; then
  launchctl unload "$PLIST_PATH" 2>/dev/null || true
  ok "Unloaded existing service"
fi

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.browsingtracker.server</string>

  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON}</string>
    <string>${SCRIPTS_DIR}/server.py</string>
  </array>

  <key>WorkingDirectory</key>
  <string>${SCRIPTS_DIR}</string>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <true/>

  <key>StandardOutPath</key>
  <string>${DATA_DIR}/server.log</string>

  <key>StandardErrorPath</key>
  <string>${DATA_DIR}/server_error.log</string>
</dict>
</plist>
PLIST

launchctl load "$PLIST_PATH"
ok "launchd service installed and started"

# Give the server a moment to start
sleep 2
if curl -sf http://127.0.0.1:7331/health > /dev/null 2>&1; then
  ok "Server is running at http://127.0.0.1:7331"
else
  warn "Server did not respond to health check yet."
  warn "Check logs at $DATA_DIR/server_error.log if issues persist."
fi

# ─── Step 5: Install cron jobs ────────────────────────────────────────────────
step "Installing cron jobs…"

# Build the cron entries
DAILY_JOB="59 23 * * *     $PYTHON $REPORTER --period daily   >> $DATA_DIR/cron.log 2>&1"
WEEKLY_JOB="59 23 * * 0    $PYTHON $REPORTER --period weekly  >> $DATA_DIR/cron.log 2>&1"
MONTHLY_JOB="58 23 28-31 * * [ \"\$(date +\\%d)\" = \"\$(cal | awk 'NF{f=\$NF} END{print f}')\" ] && $PYTHON $REPORTER --period monthly >> $DATA_DIR/cron.log 2>&1"
ANNUAL_JOB="59 23 31 12 *  $PYTHON $REPORTER --period annual  >> $DATA_DIR/cron.log 2>&1"

MARKER="# browsing-tracker"

# Remove any previous browsing-tracker cron entries, then append fresh ones
(crontab -l 2>/dev/null | grep -v "$MARKER" ; \
  echo "$DAILY_JOB   $MARKER-daily" ; \
  echo "$WEEKLY_JOB  $MARKER-weekly" ; \
  echo "$MONTHLY_JOB $MARKER-monthly" ; \
  echo "$ANNUAL_JOB  $MARKER-annual" \
) | crontab -

ok "Cron jobs installed:"
echo "    Daily   → 11:59 PM every day"
echo "    Weekly  → 11:59 PM every Sunday"
echo "    Monthly → 11:58 PM on the last day of each month"
echo "    Annual  → 11:59 PM on December 31"

# ─── Step 6: Firefox extension instructions ───────────────────────────────────
step "Firefox extension — manual install required"
echo ""
echo "  To install the extension in Firefox:"
echo "  1. Open Firefox and go to:  about:debugging#/runtime/this-firefox"
echo "  2. Click  'Load Temporary Add-on...'"
echo "  3. Navigate to:  $SCRIPT_DIR/extension/"
echo "  4. Select:       manifest.json"
echo ""
warn "Temporary add-ons are removed when Firefox restarts."
warn "For a permanent install, the extension must be signed."
warn "See: https://extensionworkshop.com/documentation/publish/signing-and-distribution-overview/"
echo ""

# ─── Done ─────────────────────────────────────────────────────────────────────
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Setup complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Next steps:"
echo "  1. Edit  ~/.browsing_tracker/config.json  (email + API keys)"
echo "  2. Install the Firefox extension (instructions above)"
echo "  3. Click the extension toolbar icon to generate a historical report"
echo "  4. Scheduled reports will arrive automatically each day/week/month/year"
echo ""
