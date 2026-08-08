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
import { h } from "./core/dom.js";

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
  document.getElementById("btn-comms").addEventListener("click", () => toggle("comms"));
  async function toggle(id) { (await import("./modules/floating.js")).togglePanel(id); }

  /* ---- core state pill + root state reflect ---- */
  const pill = document.getElementById("core-state-pill");
  const pillLabel = document.getElementById("core-state-label");
  const STATE_LABELS = {
    idle: "Idle", ready: "Ready", thinking: "Thinking", analyzing: "Analyzing",
    executing: "Executing", listening: "Listening", speaking: "Speaking",
    searching: "Searching", coding: "Coding", learning: "Learning",
    updating: "Self-Upgrading", warning: "Warning", offline: "Offline",
    focus: "Focus Mode", error: "Error", success: "Success",
  };
  on("core:core_state", (d) => {
    store.core.state = d.state;
    const color = getComputedStyle(document.documentElement).getPropertyValue(`--st-${d.state}`).trim() || "var(--st-idle)";
    pill.style.color = color;
    pill.style.borderColor = "color-mix(in srgb, currentColor 45%, transparent)";
    pillLabel.textContent = d.detail ? `${STATE_LABELS[d.state] || d.state} — ${d.detail}` : (STATE_LABELS[d.state] || d.state);
  });

  /* ---- focus mode (with task detail + real stop control) ---- */
  let focusDetail = null;
  const focusBar = h("div", { class: "focus-bar hidden", role: "status", "aria-live": "polite" });
  document.getElementById("orb-stage").appendChild(focusBar);

  function renderFocusBar() {
    if (!focusBar) return;
    if (!focusDetail) { focusBar.classList.add("hidden"); focusBar.innerHTML = ""; return; }
    focusBar.classList.remove("hidden");
    const d = focusDetail;
    focusBar.innerHTML = "";
    const kb = document.createElement("span");
    kb.className = "focus-badge";
    kb.textContent = "FOCUS";
    const task = document.createElement("span");
    task.className = "focus-task";
    task.textContent = d.task || d.reason || "complex task";
    const progress = document.createElement("span");
    progress.className = "focus-progress mono";
    progress.textContent = d.progress || "";
    const stop = document.createElement("button");
    stop.className = "mini-btn focus-stop";
    stop.textContent = "STOP";
    stop.title = "Cancel Zerion's current pending action (real backend cancel)";
    stop.addEventListener("click", async () => {
      (await import("./core/net.js")).core.cancel();
      focusDetail = null;
      renderFocusBar();
    });
    focusBar.append(kb, task, progress, stop);
  }

  on("core:focus", (d) => {
    document.getElementById("app").dataset.focus = d.active ? "true" : "false";
    if (d.active) {
      focusDetail = { task: d.task || d.task_goal || d.reason, reason: d.reason,
                      progress: d.progress || "" };
      window.__zerionOrb?.setState("focus", d.task || d.reason || "complex task");
    } else {
      focusDetail = null;
      window.__zerionOrb?.setState("idle");
    }
    renderFocusBar();
    emit("focus", { active: !!d.active, reason: d.reason || "", task: d.task || "" });
  });
  on("tasks", (d) => {
    if (!focusDetail) return;
    const t = d.tasks || [];
    const done = t.filter(x => x.state === "completed").length;
    focusDetail.progress = t.length ? `${done}/${t.length} steps` : "";
    if (d.goal && !focusDetail.task) focusDetail.task = d.goal;
    renderFocusBar();
  });

  /* ---- orb context: agents + tools + connection state ---- */
  on("core:agents", (d) => {
    const n = Object.values(d.agents || {}).filter(a => {
      const ts = a.ts || 0;
      return a.state === "active" && (Date.now() / 1000 - ts) < 30;
    }).length;
    window.__zerionOrb?.setAgents(n);
  });
  const runningTools = new Set();
  on("core:tool", (d) => {
    const key = { run_python: "executecode", run_shell: "executecode", read_file: "file", write_file: "file",
                  search_files: "file", list_directory: "file", http_get: "net", http_post: "net",
                  phone_state: "phone", agent_delegate: "agent" }[d.tool] || "tool";
    if (d.phase === "start") runningTools.add(key);
    if (d.phase === "end" || d.phase === "cancelled") runningTools.delete(key);
    window.__zerionOrb?.setTools([...runningTools]);
  });
  on("connection", ({ connected }) => {
    window.__zerionOrb?.setState(connected ? "ready" : "offline");
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
