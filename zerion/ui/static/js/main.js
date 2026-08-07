// main.js — Zerion UI boot orchestrator.
//
// Wiring only: device classification, settings application, module
// initialization, Core connection, state pill, focus mode, FPS meter,
// and the built-in layout auditor. No Core logic lives here — everything
// the UI knows arrives as events from /ws over the Core bridge.

import { initDevice, fullscreen } from "./core/device.js";
import { on, emit } from "./core/bus.js";
import { connect } from "./core/net.js";
import { store } from "./core/store.js";

const isMonitor = new URLSearchParams(location.search).get("view") === "monitor";

async function boot() {
  if (isMonitor) {
    const { bootMonitorView } = await import("./modules/monitor.js");
    bootMonitorView();
    return;
  }

  const device = initDevice();

  const { initSettings, applySettingsNow } = await import("./modules/settings.js");
  applySettingsNow();
  initSettings();

  const { initOrb } = await import("./modules/orb.js");
  window.__zerionOrb = initOrb();

  const [
    { initChat }, { initStatusPanel }, { initInsightPanel },
    { initWorkspace, setWorkspace }, { initCommandBar },
    { initTerminal }, { registerPanel }, { initGestures },
    { initShortcuts }, { initVoice }, { initMonitorButton },
  ] = await Promise.all([
    import("./modules/chat.js"),
    import("./modules/statuspanel.js"),
    import("./modules/insightpanel.js"),
    import("./modules/workspace.js"),
    import("./modules/commandbar.js"),
    import("./modules/terminal.js"),
    import("./modules/floating.js"),
    import("./modules/gestures.js"),
    import("./modules/shortcuts.js"),
    import("./modules/voice.js"),
    import("./modules/monitor.js"),
  ]);

  await import("./modules/panels.js"); // registers explorer/logs/memory/devtools

  initChat();
  initStatusPanel();
  initInsightPanel();
  initWorkspace();
  initCommandBar();
  initTerminal();
  initGestures();
  initShortcuts();
  initVoice();
  initMonitorButton();

  // welcome experience: once, on hello payload, never blocking the UI
  const { maybeShowWelcome } = await import("./modules/welcome.js");
  window.__zerionBus = { on };
  on("hello", () => maybeShowWelcome());

  // header panel buttons
  document.getElementById("btn-explorer").addEventListener("click", () => toggle("explorer"));
  document.getElementById("btn-logs").addEventListener("click", () => toggle("logs"));
  document.getElementById("btn-memory").addEventListener("click", () => toggle("memory"));
  document.getElementById("btn-devtools").addEventListener("click", () => toggle("devtools"));
  async function toggle(id) { (await import("./modules/floating.js")).togglePanel(id); }

  /* ---- core state pill + root state reflect ---- */
  const pill = document.getElementById("core-state-pill");
  const pillLabel = document.getElementById("core-state-label");
  const STATE_LABELS = {
    idle: "Idle", thinking: "Thinking", listening: "Listening", speaking: "Speaking",
    searching: "Searching", coding: "Coding", learning: "Learning",
    updating: "Updating", error: "Error", success: "Success",
  };
  on("core:core_state", (d) => {
    store.core.state = d.state;
    const color = getComputedStyle(document.documentElement).getPropertyValue(`--st-${d.state}`).trim() || "var(--st-idle)";
    pill.style.color = color;
    pill.style.borderColor = "color-mix(in srgb, currentColor 45%, transparent)";
    pillLabel.textContent = d.detail ? `${STATE_LABELS[d.state] || d.state} — ${d.detail}` : (STATE_LABELS[d.state] || d.state);
  });

  /* ---- focus mode ---- */
  on("core:focus", (d) => {
    document.getElementById("app").dataset.focus = d.active ? "true" : "false";
    emit("focus", { active: !!d.active, reason: d.reason || "" });
  });

  /* ---- workspace switch requests from UI gestures ---- */
  on("workspace:request", (d) => setWorkspace(d.mode));

  /* ---- connection state ---- */
  const banner = document.getElementById("connection-banner");
  on("connection", ({ connected }) => {
    banner.classList.toggle("hidden", connected);
    if (!connected) {
      pill.style.color = "var(--st-error)";
      pillLabel.textContent = "Offline";
    }
  });

  /* ---- FPS meter (feeds Developer Mode + quality governor) ---- */
  let frames = 0, lastFpsAt = performance.now();
  (function fpsLoop() {
    frames++;
    const now = performance.now();
    if (now - lastFpsAt >= 3000) {
      emit("fps", Math.round(frames / ((now - lastFpsAt) / 1000)));
      frames = 0; lastFpsAt = now;
    }
    requestAnimationFrame(fpsLoop);
  })();

  connect();
  fullscreen.armAutoFullscreen();

  if (new URLSearchParams(location.search).has("layoutcheck")) layoutAuditor();

  emit("app:ready", { device });
}

/* ---------- built-in layout auditor (dev verification) ----------
   Surfaces overlap/clipping issues during development — run with
   ?layoutcheck=1 or via console: zerionAudit(). */
function layoutAuditor() {
  const issues = [];
  document.querySelectorAll("#app *, #floating-layer *").forEach((el) => {
    if (!(el instanceof Element)) return;
    if (el.closest(".hidden")) return;
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") return;
    // clipped text: content wider/taller than box with hidden overflow
    const clipX = el.scrollWidth - el.clientWidth > 2 && cs.overflowX === "hidden" && !el.matches("canvas, [data-allow-clip]");
    const clipY = el.scrollHeight - el.clientHeight > 2 && cs.overflowY === "hidden" && !el.matches("canvas, [data-allow-clip], .chat-scroll, .terminal-scroll, .float-body, .side-panel-inner");
    if ((clipX || clipY) && (el.textContent || "").trim().length > 24 && el.children.length === 0) {
      issues.push(`clip${clipX ? "X" : ""}${clipY ? "Y" : ""}: ${el.tagName}.${el.className} "${el.textContent.slice(0, 40)}…"`);
    }
  });
  console.group(`Zerion layout audit — ${issues.length} potential issue(s)`);
  issues.forEach(i => console.warn(i));
  if (!issues.length) console.log("clean: no clipped text or hidden overflow found");
  console.groupEnd();
  return issues;
}
window.zerionAudit = layoutAuditor;

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
