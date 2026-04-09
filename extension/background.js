"use strict";

// ─── State ────────────────────────────────────────────────────────────────────
let activeTabId = null;
let activeTabStartTime = null;
let windowFocused = true;

const SERVER_URL = "http://127.0.0.1:7331/track";
const MIN_SESSION_SECONDS = 5;

// ─── Helpers ──────────────────────────────────────────────────────────────────

function isTrackableUrl(url) {
  if (!url) return false;
  const blocked = ["about:", "moz-extension:", "chrome:", "resource:", "data:", "javascript:"];
  return !blocked.some(prefix => url.startsWith(prefix));
}

function extractDomain(url) {
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}

async function getTabInfo(tabId) {
  try {
    const tab = await browser.tabs.get(tabId);
    return { url: tab.url || "", title: tab.title || "" };
  } catch {
    return null;
  }
}

// ─── Core: flush a completed tab session ─────────────────────────────────────

async function flushSession(tabId, startTime, endTime) {
  if (!tabId || !startTime || !endTime) return;

  const durationSeconds = Math.round((endTime - startTime) / 1000);
  if (durationSeconds < MIN_SESSION_SECONDS) return;

  const info = await getTabInfo(tabId);
  if (!info || !isTrackableUrl(info.url)) return;

  const record = {
    url: info.url,
    title: info.title,
    domain: extractDomain(info.url),
    timestamp: new Date(startTime).toISOString(),
    duration_seconds: durationSeconds
  };

  await sendRecord(record);
}

// ─── Network: POST to local server, buffer on failure ────────────────────────

async function sendRecord(record) {
  try {
    const response = await fetch(SERVER_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(record)
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
  } catch {
    // Server unavailable — buffer locally
    const stored = await browser.storage.local.get("pending");
    const pending = stored.pending || [];
    pending.push(record);
    await browser.storage.local.set({ pending });
  }
}

// ─── Retry buffered records every 30 seconds ─────────────────────────────────

setInterval(async () => {
  const stored = await browser.storage.local.get("pending");
  const pending = stored.pending || [];
  if (pending.length === 0) return;

  const failed = [];
  for (const record of pending) {
    try {
      const response = await fetch(SERVER_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(record)
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
    } catch {
      failed.push(record);
    }
  }
  await browser.storage.local.set({ pending: failed });
}, 30000);

// ─── Tab event listeners ──────────────────────────────────────────────────────

// User switches to a different tab
browser.tabs.onActivated.addListener(async (activeInfo) => {
  const now = Date.now();

  // Flush the outgoing tab
  if (activeTabId !== null && activeTabStartTime !== null && windowFocused) {
    await flushSession(activeTabId, activeTabStartTime, now);
  }

  // Start tracking the newly active tab
  activeTabId = activeInfo.tabId;
  activeTabStartTime = windowFocused ? now : null;
});

// URL changes within the currently active tab (navigation)
browser.tabs.onUpdated.addListener(async (tabId, changeInfo) => {
  if (tabId !== activeTabId) return;
  if (!changeInfo.url) return; // Only care about URL changes, not loading states

  const now = Date.now();

  // Flush the old URL session
  if (activeTabStartTime !== null && windowFocused) {
    await flushSession(activeTabId, activeTabStartTime, now);
  }

  // Restart timer for the new URL
  activeTabStartTime = windowFocused ? now : null;
});

// Tab closed
browser.tabs.onRemoved.addListener(async (tabId) => {
  if (tabId !== activeTabId) return;

  if (activeTabStartTime !== null && windowFocused) {
    await flushSession(activeTabId, activeTabStartTime, Date.now());
  }

  activeTabId = null;
  activeTabStartTime = null;
});

// Window gains or loses focus (alt-tab, minimize, switching apps)
browser.windows.onFocusChanged.addListener(async (windowId) => {
  const now = Date.now();

  if (windowId === browser.windows.WINDOW_ID_NONE) {
    // Focus lost
    windowFocused = false;
    if (activeTabId !== null && activeTabStartTime !== null) {
      await flushSession(activeTabId, activeTabStartTime, now);
      activeTabStartTime = null; // Pause — don't count unfocused time
    }
  } else {
    // Focus regained
    windowFocused = true;
    if (activeTabId !== null) {
      activeTabStartTime = now; // Resume timer
    }
  }
});

// ─── Initialization ───────────────────────────────────────────────────────────

// On extension load, pick up the currently active tab
browser.tabs.query({ active: true, currentWindow: true }).then(tabs => {
  if (tabs.length > 0 && isTrackableUrl(tabs[0].url)) {
    activeTabId = tabs[0].id;
    activeTabStartTime = Date.now();
  }
});
