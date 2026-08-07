// modules/gestures.js — touch & pointer gestures:
//   · edge swipes (phone/tablet) open the status/insight drawers
//   · swipe-down on an open drawer closes it
//   · long-press on the orb toggles voice listening
//   · dock resize handle (pointer drag, mouse or touch)
//   · global file drag & drop (text → command chip, image → vision)
// Pointer Events unify mouse/touch/pen so none of this is device-gated.

import { store } from "../core/store.js";
import { on, emit } from "../core/bus.js";
import { attachFile } from "./commandbar.js";

const EDGE = 28;         // px from screen edge that counts as edge swipe
const SWIPE_MIN = 64;    // px travel needed for a swipe

function drawersEnabled() {
  const d = store.device?.device;
  return d === "phone" || d === "tablet";
}

function openDrawer(side, open) {
  const panel = document.querySelector(side === "left" ? ".side-left" : ".side-right");
  if (panel) panel.dataset.open = open ? "true" : "false";
}

function anyDrawerOpen() {
  return [...document.querySelectorAll(".side-panel")].some(p => p.dataset.open === "true");
}

export function closeDrawers() {
  document.querySelectorAll(".side-panel").forEach(p => p.dataset.open = "false");
}

function initEdgeSwipes() {
  let start = null;

  window.addEventListener("pointerdown", (e) => {
    if (!drawersEnabled()) return;
    if (e.pointerType === "mouse" && e.button !== 0) return;
    const fromLeft = e.clientX <= EDGE;
    const fromRight = e.clientX >= window.innerWidth - EDGE;
    // when a drawer is open, allow a closing swipe from anywhere inside it
    const inPanel = e.target.closest?.(".side-panel");
    if (!fromLeft && !fromRight && !inPanel) return;
    start = { x: e.clientX, y: e.clientY, fromLeft, fromRight, inPanel, t: Date.now() };
  }, { passive: true });

  window.addEventListener("pointerup", (e) => {
    if (!start) return;
    const dx = e.clientX - start.x;
    const dy = e.clientY - start.y;
    const adx = Math.abs(dx), ady = Math.abs(dy);
    const dt = Date.now() - start.t;

    if (dt < 700) {
      if (start.fromLeft && dx > SWIPE_MIN && ady < adx) openDrawer("left", true);
      else if (start.fromRight && dx < -SWIPE_MIN && ady < adx) openDrawer("right", true);
      else if (start.inPanel) {
        const panel = start.inPanel;
        const isPhone = store.device?.device === "phone";
        if (isPhone && dy > SWIPE_MIN) panel.dataset.open = "false";
        else if (!isPhone && panel.classList.contains("side-left") && dx < -SWIPE_MIN) panel.dataset.open = "false";
        else if (!isPhone && panel.classList.contains("side-right") && dx > SWIPE_MIN) panel.dataset.open = "false";
      }
    }
    start = null;
  }, { passive: true });

  // tapping outside an open drawer dismisses it
  window.addEventListener("pointerdown", (e) => {
    if (!drawersEnabled() || !anyDrawerOpen()) return;
    if (!e.target.closest?.(".side-panel") && !e.target.closest?.(".edge-handle")) closeDrawers();
  }, { passive: true, capture: true });
}

function initLongPress() {
  const stage = document.getElementById("orb-stage");
  let timer = null;
  let moved = 0;
  stage.addEventListener("pointerdown", (e) => {
    moved = 0;
    timer = setTimeout(() => {
      timer = null;
      stage.dispatchEvent(new CustomEvent("orb:voice-toggle"));
    }, 620);
  });
  stage.addEventListener("pointermove", (e) => {
    if (!timer) return;
    moved += Math.abs(e.movementX || 0) + Math.abs(e.movementY || 0);
    if (moved > 18) { clearTimeout(timer); timer = null; }
  });
  const cancel = () => { if (timer) { clearTimeout(timer); timer = null; } };
  stage.addEventListener("pointerup", cancel);
  stage.addEventListener("pointercancel", cancel);
}

function initDockResize() {
  const handle = document.getElementById("dock-resize");
  const dock = document.getElementById("dock");
  let start = null;
  handle.addEventListener("pointerdown", (e) => {
    start = { y: e.clientY, h: dock.offsetHeight };
    handle.dataset.dragging = "true";
    handle.setPointerCapture(e.pointerId);
  });
  handle.addEventListener("pointermove", (e) => {
    if (!start) return;
    const next = Math.min(
      Math.max(start.h + (start.y - e.clientY), 90),
      window.innerHeight - 140,
    );
    dock.dataset.collapsed = "false";
    dock.style.height = next + "px";
  });
  handle.addEventListener("pointerup", () => {
    handle.dataset.dragging = "false";
    if (start) emit("layout:changed");
    start = null;
  });
  handle.addEventListener("dblclick", () => { dock.style.height = ""; emit("layout:changed"); });
}

function initFileDrop() {
  window.addEventListener("dragover", (e) => {
    if (!e.dataTransfer?.types?.includes("Files")) return;
    e.preventDefault();
  }, { passive: false });
  window.addEventListener("drop", async (e) => {
    if (!e.dataTransfer?.files?.length) return;
    // mode views handle their own drops (vision frame) — skip those
    if (e.target.closest?.(".vision-frame")) return;
    e.preventDefault();
    for (const file of e.dataTransfer.files) {
      if (file.type.startsWith("image/")) {
        // stash first: the vision workspace may not exist yet when the
        // switch event lands — createMode() consumes the stash.
        window.__zerionPendingImage = file;
        emit("workspace:request", { mode: "vision" });
        emit("ui:stage-image", { file });
        continue;
      }
      const text = await file.text().catch(() => "");
      attachFile(file.name, text.slice(0, 200_000));
    }
  }, { passive: false });
}

export function initGestures() {
  initEdgeSwipes();
  initLongPress();
  initDockResize();
  initFileDrop();
}
