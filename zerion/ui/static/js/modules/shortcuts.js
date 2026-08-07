// modules/shortcuts.js — keyboard navigation. All shortcuts are global
// except when typing in a text field (only bare-Escape and the toggle
// keys act there).

import { togglePanel, closeTopPanel } from "./floating.js";
import { toggleTerminal } from "./terminal.js";
import { focusInput } from "./commandbar.js";
import { closeDrawers } from "./gestures.js";
import { fullscreen } from "../core/device.js";

const inField = (e) =>
  e.target.closest?.("input, textarea, select, [contenteditable]");

export function initShortcuts() {
  document.addEventListener("keydown", (e) => {
    const mod = e.ctrlKey || e.metaKey;

    // Escape: close overlay → top panel → drawers
    if (e.key === "Escape") {
      const confirm = document.getElementById("confirm-overlay");
      if (!confirm.classList.contains("hidden")) { document.getElementById("confirm-no").click(); return; }
      if (closeTopPanel()) return;
      closeDrawers();
      return;
    }

    if (inField(e) && !(mod || e.key === "F11")) return;

    if (e.key === "F11") { e.preventDefault(); fullscreen.toggle(); return; }

    if (e.key === "/" && !inField(e)) { e.preventDefault(); focusInput(); return; }

    if (!mod) return;

    switch (e.key.toLowerCase()) {
      case "k": e.preventDefault(); focusInput(); break;
      case "e": e.preventDefault(); togglePanel("explorer"); break;
      case "l": e.preventDefault(); togglePanel("logs"); break;
      case "m": e.preventDefault(); togglePanel("memory"); break;
      case "j": e.preventDefault(); togglePanel("devtools"); break;
      case ",": e.preventDefault(); togglePanel("settings"); break;
      case "`": e.preventDefault(); toggleTerminal(); break;
      case "d": e.preventDefault(); document.getElementById("btn-devtools").click(); break;
    }
  });

  // Tab-order sanity: the skip links target real landmarks (verified by
  // the layout auditor).
}
