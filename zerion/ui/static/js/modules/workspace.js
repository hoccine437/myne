// modules/workspace.js — the adaptive workspace controller.
//
// The user never switches workspaces. The Core's classification and
// pipeline events decide; this module performs the transition: lazy-
// creating the mode view, crossfading it in, updating the header chip,
// and (via store.runtime.workspace) letting other modules react.

import { on, emit } from "../core/bus.js";
import { store } from "../core/store.js";

const MODES = {
  chat:       { label: "Conversation", sub: "Zerion is ready", loader: () => import("./modes/chatws.js") },
  coding:     { label: "Coding",       sub: "editor · terminal · git context", loader: () => import("./modes/coding.js") },
  research:   { label: "Research",     sub: "sources · notes · memory", loader: () => import("./modes/research.js") },
  trading:    { label: "Trading",      sub: "market posture · signals", loader: () => import("./modes/trading.js") },
  vision:     { label: "Vision",       sub: "image analysis workspace", loader: () => import("./modes/vision.js") },
  automation: { label: "Automation",   sub: "workflow graph · execution", loader: () => import("./modes/automation.js") },
};

const instances = new Map();   // name → { root, activate(ctx), event(type, data) }
let rootEl, currentName = null, token = 0;

export function currentMode() { return currentName; }

async function ensureMode(name) {
  if (instances.has(name)) return instances.get(name);
  const def = MODES[name];
  if (!def) return null;
  const mod = await def.loader();
  const inst = mod.createMode();
  inst.root.classList.add("ws-mode");
  inst.root.id = `ws-${name}`;
  inst.root.dataset.active = "false";
  rootEl.appendChild(inst.root);
  instances.set(name, inst);
  return inst;
}

export async function setWorkspace(name, ctx = {}) {
  if (!MODES[name] || name === currentName) {
    if (instances.get(name)?.activate) instances.get(name).activate(ctx);
    return;
  }
  const myToken = ++token;
  currentName = name;
  store.runtime.workspace = name;

  const inst = await ensureMode(name);
  if (!inst || myToken !== token) return; // a newer switch superseded this load

  for (const [n, i] of instances) {
    i.root.dataset.active = n === name ? "true" : "false";
    if (n !== name) i.root.setAttribute("aria-hidden", "true");
  }
  inst.root.removeAttribute("aria-hidden");
  inst.activate?.(ctx);

  const chip = document.getElementById("workspace-chip-label");
  if (chip) chip.textContent = MODES[name].label;
  document.getElementById("workspace-chip").title =
    `${MODES[name].label} — ${MODES[name].sub}`;
  emit("workspace:changed", { mode: name });
}

export function initWorkspace() {
  rootEl = document.getElementById("workspace-root");

  // chat exists immediately — it's the resting face
  ensureMode("chat").then((inst) => {
    inst.root.dataset.active = "true";
    currentName = "chat";
  });

  // Source of truth for switching: Core classification events.
  on("core:workspace", (d) => setWorkspace(d.mode, { source: d.source }));

  // Router for mode-scoped Core events → the active (or owning) view.
  on("core:tool", (d) => {
    for (const inst of instances.values()) inst.event?.("tool", d);
  });
  on("tasks", (d) => instances.get("automation")?.event?.("tasks", d));
  on("core:stage", (d) => {
    instances.get(currentName)?.event?.("stage", d);
    instances.get("automation")?.event?.("stage", d);
  });
  on("core:memory_update", (d) => instances.get("research")?.event?.("memory_update", d));
}
