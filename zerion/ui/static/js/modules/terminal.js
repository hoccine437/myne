// modules/terminal.js — the dock terminal. Commands are sent verbatim
// to the Core's run_shell tool via the session (constitutional policy +
// approval flow intact); output renders as a classic scrollback.

import { h } from "../core/dom.js";
import { on, emit } from "../core/bus.js";
import { core } from "../core/net.js";

let stream, scrollEl, input, panel, dockBody;
let open = false;

function line(kind, text) {
  stream.appendChild(h("div", { class: `tl-${kind}` }, text));
  scrollEl.scrollTop = scrollEl.scrollHeight;
  while (stream.children.length > 400) stream.firstElementChild.remove();
}

export function initTerminal() {
  stream = document.getElementById("terminal-stream");
  scrollEl = document.getElementById("terminal-scroll");
  input = document.getElementById("terminal-input");
  panel = document.getElementById("terminal-panel");
  dockBody = document.querySelector(".dock-body");

  document.getElementById("terminal-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const cmd = input.value.trim();
    if (!cmd) return;
    line("cmd", `$ ${cmd}`);
    core.terminal(cmd);
    input.value = "";
  });

  document.getElementById("terminal-clear").addEventListener("click", () => { stream.innerHTML = ""; });
  document.getElementById("terminal-close").addEventListener("click", () => toggleTerminal(false));

  document.getElementById("btn-terminal-toggle").addEventListener("click", () => toggleTerminal());

  on("core:tool", (d) => {
    if (d.channel !== "terminal") return;
    if (d.phase === "confirm") {
      line("pending", `⚠ approval required — approve in the dialog to run: ${d.command ?? ""}`);
    } else if (d.phase === "end") {
      const cls = d.success ? "out" : "err";
      for (const l of String(d.output ?? "").split("\n")) line(cls, l);
      if (!d.success && d.error) line("err", `[${d.error}]`);
    } else if (d.phase === "rejected") {
      line("err", `(!) ${d.reason === "busy" ? "Zerion is busy — try again in a moment." : "rejected"}`);
    } else if (d.phase === "cancelled") {
      line("err", "aborted — nothing was executed.");
    }
  });
}

export function toggleTerminal(force) {
  open = force ?? !open;
  panel.classList.toggle("hidden", !open);
  dockBody.dataset.split = open ? "true" : "false";
  document.getElementById("btn-terminal-toggle").setAttribute("aria-pressed", String(open));
  if (open) {
    document.getElementById("dock").dataset.collapsed = "false";
    input.focus();
  }
  emit("layout:changed");
}
