// modules/monitor.js — second-display support.
//
// Opens a dedicated monitor view (same origin, ?view=monitor) that the
// user can place on a secondary display. Where the Window Management API
// is granted, we position it on the second screen automatically;
// otherwise it opens as a normal window the user drags over. The view
// opens its own WebSocket — no fragile cross-window state.
// On phones the option is hidden by CSS.

import { on, emit } from "../core/bus.js";
import { store } from "../core/store.js";
import { h } from "../core/dom.js";
import { connect, core } from "../core/net.js";
import { initDevice } from "../core/device.js";
import { applySettingsNow } from "./settings.js";

let monitorWindow = null;

async function openMonitor() {
  if (monitorWindow && !monitorWindow.closed) {
    monitorWindow.focus();
    return;
  }
  let left = window.screenX + 80, top = window.screenY + 60, width = 900, height = 640;

  // Best-effort: with window-management permission, target the 2nd screen
  try {
    if ("getScreenDetails" in window) {
      const details = await window.getScreenDetails();
      const other = details.screens.find(s => s !== details.currentScreen) || details.screens[0];
      if (other) {
        left = other.left + 40; top = other.top + 40;
        width = Math.min(1100, other.width - 80);
        height = Math.min(760, other.height - 80);
      }
    }
  } catch { /* permission not granted — plain window is fine */ }

  monitorWindow = window.open(
    "/?view=monitor", "zerion-monitor",
    `popup=yes,left=${left},top=${top},width=${width},height=${height}`,
  );
  if (!monitorWindow) {
    emit("toast", { text: "Popup blocked — allow popups for the monitor view.", level: "warning" });
  }
}

export function initMonitorButton() {
  document.getElementById("btn-monitor").addEventListener("click", openMonitor);
}

/* ---------- the monitor view itself (?view=monitor) ---------- */

export function bootMonitorView() {
  document.documentElement.dataset.view = "monitor";
  initDevice();
  applySettingsNow();

  const app = document.getElementById("app");
  app.className = "monitor-app";
  app.innerHTML = "";

  const stateEl = h("span", { class: "core-state-pill" },
    h("span", { class: "state-dot" }), h("span", { id: "mon-state" }, "…"));
  const metricsEl = h("span", { class: "mono", style: "font-size:11px;color:var(--text-2)" }, "—");

  const logsEl = h("div", { class: "log-list" });
  const termStream = h("div", { class: "terminal-stream mono", style: "flex:1;overflow-y:auto;padding:8px 10px" });
  const termInput = h("input", {
    class: "terminal-input mono", placeholder: "command…",
    "aria-label": "Terminal command", autocomplete: "off", spellcheck: "false",
  });

  app.append(
    h("header", { class: "monitor-head" },
      h("strong", {}, "ZERION · MONITOR"), stateEl, metricsEl),
    h("div", { class: "monitor-mid" }, logsEl),
    h("section", { class: "monitor-term terminal-panel" },
      termStream,
      h("form", { class: "terminal-form", onsubmit: (e) => {
        e.preventDefault();
        const cmd = termInput.value.trim();
        if (cmd) { termStream.append(h("div", { class: "tl-cmd" }, `$ ${cmd}`)); core.terminal(cmd); termInput.value = ""; }
        termStream.parentElement.scrollTop = termStream.parentElement.scrollHeight;
      } },
        h("span", { class: "terminal-prompt mono" }, "$"), termInput),
    ),
  );

  on("core:core_state", (d) => {
    app.querySelector("#mon-state").textContent = d.state;
  });
  on("core:metrics", (m) => {
    metricsEl.textContent =
      `cpu ${m.cpu?.percent ?? "—"}% · ram ${m.ram?.percent ?? "—"}% · up ${m.uptime_s ?? 0}s`;
  });
  const addLine = (text) => {
    logsEl.append(h("div", { class: "log-line" }, h("span", { class: "log-msg" }, text)));
    while (logsEl.children.length > 300) logsEl.firstElementChild.remove();
    logsEl.parentElement.scrollTop = logsEl.parentElement.scrollHeight;
  };
  on("core:event", (msg) => {
    if (msg.type === "log") addLine(msg.data.text);
    if (msg.type === "chat" && msg.data.role === "ai") addLine("Zerion: " + msg.data.text.slice(0, 200));
    if (msg.type === "stage") addLine(`stage ${msg.data.stage}: ${msg.data.status}`);
    if (msg.type === "tool") {
      const d = msg.data;
      if (d.channel === "terminal" && d.phase === "end") {
        termStream.append(h("div", { class: d.success ? "tl-out" : "tl-err" }, d.output || d.error || ""));
        termStream.parentElement.scrollTop = termStream.parentElement.scrollHeight;
      }
    }
  });
  on("connection", ({ connected }) => {
    document.title = connected ? "Zerion Monitor" : "Zerion Monitor — offline";
  });

  connect();
}
