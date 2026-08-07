// modules/commandbar.js — the bottom command input: text, voice capture,
// slash-command autocomplete, file attachment chips, dock collapse.
// Every submission is routed to the Core through core/net.js.

import { h, clear } from "../core/dom.js";
import { on, emit } from "../core/bus.js";
import { store } from "../core/store.js";
import { core } from "../core/net.js";

const SLASH_COMMANDS = [
  ["/help", "list available local commands"],
  ["/status", "goal + action counts this session"],
  ["/tools", "list tools available to the Core"],
  ["/memory", "show prompt-relevant long-term memory"],
  ["/history", "recent tool executions"],
  ["/goals", "goal counters"],
  ["/plan", "show the active workflow"],
  ["/plugins", "about capability plugins"],
  ["/debug on", "planner debug logging on"],
  ["/debug off", "planner debug logging off"],
];

let input, form, acBox, acIndex = -1, acItems = [];
let attachments = []; // [{name, text}]

function autoGrow() {
  input.style.height = "0px";
  input.style.height = Math.min(input.scrollHeight, 132) + "px";
}

function setBusy(busy) {
  document.getElementById("btn-send").disabled = busy;
}

/* ---------------- attachments ---------------- */
function renderChips() {
  const wrap = document.getElementById("attach-chips");
  clear(wrap);
  attachments.forEach((a, i) => {
    wrap.appendChild(h("span", { class: "attach-chip" },
      h("span", {}, a.name),
      h("button", { type: "button", "aria-label": `Remove ${a.name}`,
        onclick: () => { attachments.splice(i, 1); renderChips(); } }, "✕"),
    ));
  });
}

export function attachFile(name, text) {
  attachments.push({ name, text: String(text ?? "").slice(0, 200_000) });
  renderChips();
  input.focus();
}

/* ---------------- submit ---------------- */
let busyFallbackTimer = null;

function submit() {
  const text = input.value.trim();
  if (!text && !attachments.length) return;

  let payload = text;
  if (attachments.length) {
    const parts = attachments.map(a =>
      `[Attached file: ${a.name}]\n${a.text}`);
    payload = `${parts.join("\n\n")}\n\n${text || "Please review the attached file(s)."}`;
    attachments = [];
    renderChips();
  }

  core.message(payload);
  input.value = "";
  autoGrow();
  hideAutocomplete();
  setBusy(true);
  // safety: if the turn-end event never arrives (dropped connection),
  // don't strand the composer in a disabled state
  clearTimeout(busyFallbackTimer);
  busyFallbackTimer = setTimeout(() => setBusy(false), 45000);
}

/* ---------------- slash autocomplete ---------------- */
function hideAutocomplete() {
  acBox.classList.add("hidden");
  acIndex = -1; acItems = [];
}

function updateAutocomplete() {
  const v = input.value;
  if (!v.startsWith("/") || v.includes(" ") && !v.startsWith("/debug ")) { hideAutocomplete(); return; }
  const q = v.toLowerCase();
  acItems = SLASH_COMMANDS.filter(([cmd]) => cmd.startsWith(q));
  if (!acItems.length || (acItems.length === 1 && acItems[0][0] === q)) {
    // keep /debug on|off suggestions visible while typing argument
    if (!q.startsWith("/debug")) { hideAutocomplete(); return; }
  }
  clear(acBox);
  acItems.forEach(([cmd, desc], i) => {
    acBox.appendChild(h("div", {
      class: "cmd-ac-item", role: "option", id: `ac-${i}`,
      "aria-selected": i === acIndex ? "true" : "false",
      onmousedown: (e) => { e.preventDefault(); pickAc(i); },
    }, h("code", {}, cmd), h("span", {}, desc)));
  });
  acBox.classList.remove("hidden");
}

function pickAc(i) {
  const cmd = acItems[i]?.[0];
  if (!cmd) return;
  if (cmd.endsWith(" ")) { input.value = cmd; }
  else if (cmd === "/debug on" || cmd === "/debug off") { input.value = cmd; submit(); return; }
  else input.value = cmd + (cmd === "/debug" ? " " : "");
  input.focus();
  hideAutocomplete();
}

/* ---------------- voice input ---------------- */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let recog = null, listening = false;

function setupVoice() {
  const btn = document.getElementById("btn-voice");
  if (!SR) {
    btn.addEventListener("click", () =>
      emit("toast", { text: "Speech recognition isn't available in this browser — type instead.", level: "warning" }));
    return;
  }
  recog = new SR();
  recog.continuous = false;
  recog.interimResults = true;
  recog.lang = ({ en: "en-US", fr: "fr-FR", es: "es-ES", de: "de-DE" })[store.settings.language] || "en-US";

  recog.onstart = () => {
    listening = true;
    btn.dataset.active = "true";
    btn.setAttribute("aria-pressed", "true");
    store.core.state = "listening";
  };
  recog.onresult = (e) => {
    let interim = "", final = "";
    for (const r of e.results) (r.isFinal ? final += r[0].transcript : interim += r[0].transcript);
    input.value = (final || interim).trim();
    autoGrow();
  };
  recog.onerror = (e) => {
    stopVoice();
    if (e.error !== "aborted" && e.error !== "no-speech")
      emit("toast", { text: `Voice input stopped (${e.error}).`, level: "warning" });
  };
  recog.onend = () => {
    const hadText = !!input.value.trim();
    stopVoice();
    if (hadText) submit();
  };
  btn.addEventListener("click", () => listening ? recog.stop() : startVoice());
}

function startVoice() {
  try { recog?.start(); } catch { /* already started */ }
}
function stopVoice() {
  listening = false;
  const btn = document.getElementById("btn-voice");
  btn.dataset.active = "false";
  btn.setAttribute("aria-pressed", "false");
  try { recog?.stop(); } catch { /* idle */ }
}

/* ---------------- init ---------------- */
export function initCommandBar() {
  input = document.getElementById("command-input");
  form = document.getElementById("command-bar");
  acBox = document.getElementById("cmd-autocomplete");

  form.addEventListener("submit", (e) => { e.preventDefault(); submit(); });

  input.addEventListener("input", () => { autoGrow(); updateAutocomplete(); });
  input.addEventListener("keydown", (e) => {
    if (!acBox.classList.contains("hidden")) {
      if (e.key === "ArrowDown") { e.preventDefault(); acIndex = (acIndex + 1) % acItems.length; }
      else if (e.key === "ArrowUp") { e.preventDefault(); acIndex = (acIndex - 1 + acItems.length) % acItems.length; }
      else if (e.key === "Tab" || (e.key === "Enter" && acIndex >= 0)) { e.preventDefault(); pickAc(acIndex >= 0 ? acIndex : 0); return; }
      else if (e.key === "Escape") { hideAutocomplete(); return; }
      else if (e.key === "Enter") { /* fall through to submit */ }
      else { updateAutocomplete(); return; }
      // refresh aria-selected
      [...acBox.children].forEach((el, i) =>
        el.setAttribute("aria-selected", i === acIndex ? "true" : "false"));
      if (e.key === "ArrowDown" || e.key === "ArrowUp") return;
    }
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
  });

  on("core:turn", (d) => {
    if (d.phase === "end") { clearTimeout(busyFallbackTimer); setBusy(false); }
  });
  on("core:core_state", (d) => {
    store.core.state = d.state;
    if (d.state === "error") setBusy(false);
  });

  // dock collapse toggle
  const dock = document.getElementById("dock");
  const dockBtn = document.getElementById("btn-dock-toggle");
  const applyDock = () => {
    dock.dataset.collapsed = store.settings.dockCollapsed ? "true" : "false";
    dockBtn.setAttribute("aria-pressed", (!store.settings.dockCollapsed).toString());
  };
  dockBtn.addEventListener("click", () => {
    store.settings.dockCollapsed = !store.settings.dockCollapsed;
    try { localStorage.setItem("zerion.settings.v1", JSON.stringify(store.settings)); } catch { }
    applyDock();
  });
  on("focus", (d) => {
    if (d.active) { dock.dataset.collapsed = "true"; }
    else applyDock();
  });
  applyDock();

  setupVoice();

  emit("commandbar:ready");
}

export function focusInput() { input?.focus(); }
