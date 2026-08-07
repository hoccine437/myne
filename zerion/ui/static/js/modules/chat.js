// modules/chat.js — the conversation stream.
//
// Rendered DOM is windowed (only the last MAX_DOM messages live in the
// tree) so a long session never degrades scroll/frame performance; the
// full history stays in memory and the buffer is re-hydrated from the
// server's replay after reconnects.

import { h, mdLite, timeOf, clear } from "../core/dom.js";
import { on, emit } from "../core/bus.js";
import { store } from "../core/store.js";

const MAX_DOM = 60;

let streamEl, scrollEl, jumpBtn;
let messages = [];
let speakHook = null;

export function onSpeak(fn) { speakHook = fn; }

function msgNode(m) {
  const body = h("div", { class: "msg-body" });
  body.innerHTML = mdLite(m.text);
  const when = h("div", { class: "msg-meta" },
    `${m.role === "ai" ? "Zerion" : "You"} · ${timeOf(m.ts)}${m.kind ? " · " + m.kind : ""}`);
  const bubble = h("div", { class: "msg-bubble" }, body, when);
  return h("div", { class: "msg", dataset: { role: m.role, kind: m.kind || "" } },
    h("span", { class: "msg-avatar", "aria-hidden": "true" }, m.role === "ai" ? "Z" : "U"),
    bubble,
  );
}

function nearBottom() {
  return scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight < 80;
}

function renderOne(m, { stick } = {}) {
  const stickNow = stick ?? nearBottom();
  streamEl.appendChild(msgNode(m));
  while (streamEl.children.length > MAX_DOM) streamEl.removeChild(streamEl.firstChild);
  if (stickNow) scrollEl.scrollTop = scrollEl.scrollHeight;
  else jumpBtn.dataset.show = "true";
}

export function addMessage(m) {
  messages.push(m);
  if (messages.length > 2000) messages = messages.slice(-1500);
  renderOne(m);
  if (m.role === "ai" && speakHook && store.settings.voiceOutput) speakHook(m.text);
}

export function initChat() {
  streamEl = document.getElementById("chat-stream");
  scrollEl = document.getElementById("chat-scroll");
  jumpBtn = document.getElementById("chat-jump");

  on("core:chat", (d) => addMessage({ role: d.role, text: d.text, kind: d.kind || "", ts: Date.now() / 1000 }));

  scrollEl.addEventListener("scroll", () => {
    if (nearBottom()) jumpBtn.dataset.show = "false";
  }, { passive: true });

  jumpBtn.addEventListener("click", () => {
    scrollEl.scrollTop = scrollEl.scrollHeight;
    jumpBtn.dataset.show = "false";
  });

  emit("chat:ready");
}
