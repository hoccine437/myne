// modules/modes/chatws.js — resting workspace face.
// Conversation happens in the dock; the center stays contemplative and
// offers capability hints until work starts.

import { h } from "../../core/dom.js";

export function createMode() {
  const hint = h("div", { class: "ws-hint" },
    h("span", { class: "hint-glyph" }, "◈"),
    h("p", {}, "Zerion is listening."),
    h("p", { style: "font-size:11px; margin-top:6px" },
      "Ask below — or drop a file into the window. The workspace adapts itself to whatever you start: code, research, planning, vision."),
  );

  const root = h("section", { class: "", "aria-label": "Conversation workspace" }, hint);
  return {
    root,
    activate() { },
    event() { },
  };
}
