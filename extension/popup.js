"use strict";

const HISTORICAL_URL = "http://127.0.0.1:7331/generate-historical";

const btn = document.getElementById("generateBtn");
const status = document.getElementById("status");

function setStatus(state, message) {
  status.className = state;
  if (state === "generating") {
    status.innerHTML = `<span class="spinner"></span>${message}`;
  } else {
    status.textContent = message;
  }
}

btn.addEventListener("click", async () => {
  btn.disabled = true;
  setStatus("generating", "Generating report\u2026 this may take a moment.");

  try {
    const response = await fetch(HISTORICAL_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    });

    const data = await response.json();

    if (data.status === "sent") {
      setStatus("success", "Report sent to your email.");
    } else {
      setStatus("error", `Error: ${data.message || "Unknown error."}`);
    }
  } catch {
    setStatus("error", "Server not running \u2014 run setup.sh first.");
  } finally {
    btn.disabled = false;
  }
});
