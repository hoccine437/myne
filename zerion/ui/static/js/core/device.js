// core/device.js — the smart layout engine's classifier.
//
// Watches viewport geometry, aspect ratio, orientation, DPR and pointer
// type, and reflects them as data-* attributes on <html>. CSS reads those
// to switch layouts; modules listen to the 'device' bus event for
// geometry-dependent work (orb resize, chart canvases). Everything is
// live: rotate a tablet, resize a window, unfold a foldable — the UI
// re-flows instantly with no refresh and no state loss.

import { emit } from "./bus.js";
import { store } from "./store.js";

const html = document.documentElement;
let current = null;

export function classify() {
  const w = window.innerWidth;
  const hgt = window.innerHeight;
  const short = Math.min(w, hgt);
  const long = Math.max(w, hgt);
  const aspect = long / Math.max(short, 1);

  const coarse = window.matchMedia("(pointer: coarse)").matches;
  const fine = window.matchMedia("(pointer: fine)").matches;

  let device;
  if (coarse && !fine) {
    // Touch-first devices classify by short side: a 1180×820 tablet in
    // landscape is still a tablet, an unfolded foldable is a small tablet,
    // a phone in landscape is still a phone.
    device = short < 620 ? "phone" : "tablet";
  } else if (w >= 1900 && aspect >= 2.0) device = "ultrawide";
  else if (w >= 1600) device = "desktop";
  else if (w >= 1100) device = "laptop";
  else if (w < 640) device = "phone";       // narrow desktop window → compact UI
  else device = "tablet";                   // small desktop window → rail layout

  // Foldables: a hinge splits the viewport — with the W3C segments API we
  // can be precise; otherwise a near-square-but-huge viewport is the hint.
  let foldable = false;
  try {
    const segments = window.visualViewport?.segments;
    if (segments && segments.length > 1) foldable = true;
  } catch { /* API absent */ }
  try {
    if (navigator.devicePosture && navigator.devicePosture.type === "folded") foldable = true;
  } catch { /* API absent */ }
  if (!foldable && coarse && short >= 620 && short <= 780 && aspect <= 1.55) {
    foldable = "likely"; // unfoldable phablet/foldable-open territory
  }

  const pointer = coarse && !fine ? "coarse" : "fine";
  const orientation = w >= hgt ? "landscape" : "portrait";

  return {
    device, pointer, orientation, foldable,
    w, h: hgt, dpr: window.devicePixelRatio || 1, aspect, short, long,
  };
}

export function applyProfile(p = classify(), { announce = true } = {}) {
  const changed = !current ||
    p.device !== current.device || p.orientation !== current.orientation ||
    p.pointer !== current.pointer || !!p.foldable !== !!current.foldable;
  current = p;
  html.dataset.device = p.device;
  html.dataset.orientation = p.orientation;
  html.dataset.pointer = p.pointer;
  html.dataset.foldable = p.foldable ? "true" : "false";
  store.device = p;
  if (announce) emit("device", { profile: p, changed });
  return p;
}

export function initDevice() {
  applyProfile(classify(), { announce: false });

  let raf = 0;
  const reflow = () => {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => applyProfile(classify()));
  };
  window.addEventListener("resize", reflow, { passive: true });
  window.addEventListener("orientationchange", reflow, { passive: true });
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", reflow, { passive: true });
  }
  try { document.fonts?.ready?.then(reflow); } catch { /* optional */ }

  emit("device", { profile: current, changed: true });
  return current;
}

// ---------------- fullscreen ----------------

export const fullscreen = {
  supported: () =>
    typeof document.documentElement.requestFullscreen === "function",

  active: () => !!document.fullscreenElement,

  async toggle() {
    if (!this.supported()) {
      // Graceful degradation: when fullscreen is unavailable the app
      // already maximizes usable space via the fixed, 100dvh shell.
      emit("toast", { text: "Fullscreen is not available here — the workspace is already maximized.", level: "warning" });
      return false;
    }
    try {
      if (this.active()) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen({ navigationUI: "hide" });
      return this.active();
    } catch {
      emit("toast", { text: "Fullscreen request was blocked by the browser.", level: "warning" });
      return false;
    }
  },

  // "Auto fullscreen on start" — browsers require a user gesture, so we
  // hook the first interaction once. If that never comes, nothing breaks.
  armAutoFullscreen() {
    if (!store.settings.autoFullscreen || !this.supported()) return;
    const arm = () => {
      this.toggle().finally(() => {
        document.removeEventListener("pointerdown", arm);
        document.removeEventListener("keydown", arm);
      });
    };
    document.addEventListener("pointerdown", arm, { once: false });
    document.addEventListener("keydown", arm, { once: false });
    // Disarm if the user cancels fullscreen manually.
    document.addEventListener("fullscreenchange", () => {
      if (!this.active()) {
        document.removeEventListener("pointerdown", arm);
        document.removeEventListener("keydown", arm);
      }
    });
  },
};
