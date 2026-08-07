// modules/floating.js — floating panel manager: draggable, resizable,
// lazily-created glass windows (File Explorer, Logs, Memory Inspector,
// Developer Tools, Settings). On phones they become bottom sheets.
// One instance per panel id; toggling an open panel closes it.

import { h } from "../core/dom.js";
import { on, emit } from "../core/bus.js";
import { store } from "../core/store.js";

const PANELS = {};   // id → { title, mount(bodyEl), unmount?() }
const openPanels = new Map(); // id → { root, cleanup }
let topZ = 1;

export function registerPanel(id, def) { PANELS[id] = def; }

export function isOpen(id) { return openPanels.has(id); }

export function togglePanel(id) {
  if (openPanels.has(id)) closePanel(id);
  else openPanel(id);
}

export function openPanel(id) {
  if (openPanels.has(id)) return;
  const def = PANELS[id];
  if (!def) return;

  const titleEl = h("span", { class: "float-title", id: `fp-title-${id}` }, def.title);
  const closeBtn = h("button", {
    class: "icon-btn", style: "width:26px;height:26px",
    "aria-label": `Close ${def.title}`,
    onclick: () => closePanel(id),
  }, "✕");

  const head = h("div", { class: "float-head" }, titleEl, closeBtn);
  const body = h("div", { class: "float-body" });
  const resizer = h("div", { class: "float-resize", "aria-hidden": "true" });
  const root = h("section", {
    class: "float-panel", role: "dialog",
    "aria-labelledby": `fp-title-${id}`, dataset: { panel: id },
  }, head, body, resizer);

  // restore saved position (desktop only)
  const saved = loadPos(id);
  const isPhone = store.device?.device === "phone";
  if (!isPhone) {
    root.style.left = `${saved?.x ?? 80 + openPanels.size * 36}px`;
    root.style.top = `${saved?.y ?? 90 + openPanels.size * 30}px`;
    if (saved?.w) root.style.width = saved.w + "px";
    if (saved?.h) root.style.height = saved.h + "px";
  }

  document.getElementById("floating-layer").appendChild(root);
  bringToFront(root);
  root.addEventListener("pointerdown", () => bringToFront(root), { capture: true });

  // drag by header (desktop; on phone the sheet is fixed)
  makeDraggable(root, head, id);
  makeResizable(root, resizer, id);

  const cleanup = def.mount?.(body) || null;
  openPanels.set(id, { root, cleanup });
  emit("panel:open", { id });
  closeBtn.focus();
}

export function closePanel(id) {
  const p = openPanels.get(id);
  if (!p) return;
  try { p.cleanup?.(); } catch { /* panel cleanup is best-effort */ }
  p.root.remove();
  openPanels.delete(id);
  emit("panel:close", { id });
}

function bringToFront(root) {
  root.style.zIndex = String(++topZ);
}

/* drag/resize with Pointer Events — mouse, pen and touch share a path */
function makeDraggable(root, handle, id) {
  let start = null;
  handle.addEventListener("pointerdown", (e) => {
    if (e.target.closest("button") || store.device?.device === "phone") return;
    start = { x: e.clientX, y: e.clientY, l: root.offsetLeft, t: root.offsetTop };
    handle.setPointerCapture(e.pointerId);
  });
  handle.addEventListener("pointermove", (e) => {
    if (!start) return;
    const nx = Math.max(0, Math.min(start.l + e.clientX - start.x, window.innerWidth - 80));
    const ny = Math.max(0, Math.min(start.t + e.clientY - start.y, window.innerHeight - 60));
    root.style.left = nx + "px"; root.style.top = ny + "px";
  });
  handle.addEventListener("pointerup", () => {
    if (start) savePos(id, { x: root.offsetLeft, y: root.offsetTop, w: root.offsetWidth, h: root.offsetHeight });
    start = null;
  });
}

function makeResizable(root, resizer, id) {
  let start = null;
  resizer.addEventListener("pointerdown", (e) => {
    if (store.device?.device === "phone") return;
    e.preventDefault();
    start = { x: e.clientX, y: e.clientY, w: root.offsetWidth, h: root.offsetHeight };
    resizer.setPointerCapture(e.pointerId);
  });
  resizer.addEventListener("pointermove", (e) => {
    if (!start) return;
    root.style.width = Math.max(240, start.w + e.clientX - start.x) + "px";
    root.style.height = Math.max(140, start.h + e.clientY - start.y) + "px";
  });
  resizer.addEventListener("pointerup", () => {
    if (start) savePos(id, { x: root.offsetLeft, y: root.offsetTop, w: root.offsetWidth, h: root.offsetHeight });
    start = null;
  });
}

const POS_KEY = "zerion.panels.v1";
function loadPos(id) {
  try { return JSON.parse(localStorage.getItem(POS_KEY) || "{}")[id]; } catch { return null; }
}
function savePos(id, pos) {
  try {
    const all = JSON.parse(localStorage.getItem(POS_KEY) || "{}");
    all[id] = pos;
    localStorage.setItem(POS_KEY, JSON.stringify(all));
  } catch { /* ignore */ }
}

/* Escape closes the topmost panel (wired by shortcuts.js through this). */
export function closeTopPanel() {
  if (!openPanels.size) return false;
  let best = null, bestZ = -1;
  for (const [id, p] of openPanels) {
    const z = parseInt(p.root.style.zIndex || "0", 10);
    if (z > bestZ) { bestZ = z; best = id; }
  }
  if (best) { closePanel(best); return true; }
  return false;
}

on("device", ({ changed }) => {
  // entering/leaving phone form factor re-homes panels (sheet ↔ window).
  // Snapshot first: close/open mutate openPanels — never iterate a map
  // you are rebuilding.
  if (!changed) return;
  for (const id of [...openPanels.keys()]) { closePanel(id); openPanel(id); }
});
