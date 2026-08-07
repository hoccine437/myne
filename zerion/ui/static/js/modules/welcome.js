// modules/welcome.js — first-run welcome experience.
//
// Fast and functional by contract: no cinematic delay, one card, real
// readiness data. Shown once (localStorage flag), re-openable from
// Settings. Uses live bootstrap data: version, model, voice readiness,
// API key presence — honest about what's missing instead of a fake "all
// good" splash.

import { h } from "../core/dom.js";
import { store } from "../core/store.js";

const KEY = "zerion.welcomed.v1";

function readinessRows(boot) {
  const s = boot?.settings || {};
  const rows = [
    ["Core online", true, "Core engine reachable via the UI bridge"],
    ["Model configured", !!s.llm_configured, s.llm_configured ? s.model : "GEMINI_API_KEY not set — chat needs it"],
    ["Voice output", !!s.tts_supported && !!s.llm_configured,
      s.llm_configured ? "Gemini TTS wired (server); browser voice available in Settings" : "depends on the API key"],
    ["Tools", (boot?.tools?.length || 0) > 0, `${boot?.tools?.length || 0} tools discovered`],
  ];
  return rows;
}

export function maybeShowWelcome(container) {
  let seen = false;
  try { seen = !!localStorage.getItem(KEY); } catch { }
  if (seen) return;
  show(container);
}

export function show(container) {
  container = container || document.getElementById("floating-layer");
  const overlay = h("div", {
    class: "confirm-overlay", role: "dialog", "aria-modal": "true",
    "aria-labelledby": "welcome-title", style: "backdrop-filter: blur(12px)",
  });

  const list = h("div", { style: "display:flex; flex-direction:column; gap:7px; margin:12px 0 4px" });

  const card = h("div", { class: "glass-strong", style: "max-width:520px;width:100%;padding:26px 28px" },
    h("div", { style: "display:flex; align-items:center; gap:10px; margin-bottom:6px" },
      h("span", { class: "brand-mark" }, h("span", { class: "brand-dot" })),
      h("h2", { id: "welcome-title", style: "margin:0; letter-spacing:.18em" }, "ZERION"),
    ),
    h("p", { style: "color:var(--text-1); font-size:13.5px; line-height:1.6" },
      "Welcome. I'm Zerion — your adaptive AI operating layer for this device. " +
      "One screen, one workspace: I reshuffle it around whatever you're doing."),
    h("h3", { style: "font-size:11px; letter-spacing:.14em; color:var(--text-2); margin-top:14px" },
      "READINESS"),
    list,
    h("p", { style: "color:var(--text-2); font-size:12px; margin-top:10px; line-height:1.6" },
      "Everything is local-first: memory stays on this hardware, tools ask before " +
      "they change anything, and I announce system state instead of hiding it."),
    h("div", { style: "display:flex; gap:10px; margin-top:18px; justify-content:flex-end" },
      h("button", {
        class: "btn btn-ghost", onclick: () => { dismiss(overlay, false); },
      }, "Later"),
      h("button", {
        class: "btn btn-danger", style: "background:linear-gradient(135deg,var(--accent),var(--accent-2));color:#06121c",
        autofocus: true,
        onclick: () => dismiss(overlay, true),
      }, "Enter Zerion"),
    ),
  );

  overlay.appendChild(card);
  document.body.appendChild(overlay);

  // readiness fills in when bootstrap/hello data is available
  const renderReadiness = () => {
    list.innerHTML = "";
    for (const [label, ok, detail] of readinessRows(store.boot)) {
      list.appendChild(h("div", {
        style: "display:flex; gap:10px; align-items:baseline; font-size:12.5px",
      },
        h("span", { style: `color:${ok ? "var(--ok)" : "var(--warn)"}; width:14px` }, ok ? "✓" : "!"),
        h("span", { style: "min-width:130px; font-weight:600" }, label),
        h("span", { style: "color:var(--text-2); font-size:11.5px" }, detail),
      ));
    }
  };
  if (store.boot) renderReadiness();
  else {
    const { on } = window.__zerionBus || {};
    if (on) {
      const off = on("hello", (data) => { renderReadiness(); off(); });
    }
  }
  card.querySelector("[autofocus]")?.focus();
}

function dismiss(overlay, persist) {
  if (persist) {
    try { localStorage.setItem(KEY, "1"); } catch { }
  }
  overlay.remove();
  document.getElementById("command-input")?.focus();
}

export function resetWelcome() {
  try { localStorage.removeItem(KEY); } catch { }
}
