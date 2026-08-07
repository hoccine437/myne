// modules/settings.js — Settings panel: themes, language, voice,
// performance, animations, fullscreen, accessibility, and the live
// Core toggles the server exposes (planner / self-critic / voice).
//
// Client-side settings persist to localStorage; Core-side toggles round-
// trip through POST /api/settings, which mutates the running config and
// persists to .env — the UI never touches Core internals directly.

import { h, clear } from "../core/dom.js";
import { on, emit } from "../core/bus.js";
import { store, updateSettings } from "../core/store.js";
import { api, postJSON } from "../core/net.js";
import { registerPanel } from "./floating.js";
import { applyI18n, t } from "./i18n.js";
import { fullscreen } from "../core/device.js";
import { getVoices, available as ttsAvailable, stopSpeaking } from "./voice.js";

function applySettings() {
  const s = store.settings;
  const html = document.documentElement;
  html.dataset.theme = s.theme;
  html.dataset.anim = s.animations;
  html.dataset.contrast = s.highContrast ? "high" : "normal";
  html.style.setProperty("--text-scale", s.textScale);
  applyI18n();
}

function row(label, desc, control) {
  return h("div", { class: "setting-row" },
    h("div", {}, h("div", {}, label), desc ? h("div", { class: "setting-desc" }, desc) : null),
    control,
  );
}

function select(options, value, onchange, attrs = {}) {
  const el = h("select", attrs,
    ...options.map(([v, label]) => h("option", { value: v, selected: v === value }, label)));
  el.addEventListener("change", () => onchange(el.value));
  return el;
}

function toggleRow(label, desc, checked, onchange) {
  const labelEl = h("div", {}, h("div", {}, label), desc ? h("div", { class: "setting-desc" }, desc) : null);
  const input = h("input", { type: "checkbox", "aria-label": label });
  input.checked = !!checked;
  input.addEventListener("change", () => onchange(input.checked));
  const tgl = h("span", { class: "toggle", dataset: { toggleFor: label } },
    input,
    h("span", { class: "toggle-track" }, h("span", { class: "toggle-thumb" })),
  );
  return h("div", { class: "setting-row" }, labelEl, tgl);
}

registerPanel("settings", {
  title: "Settings",
  mount(body) {
    const s = store.settings;

    const wrap = h("div", { class: "settings-panel" });

    /* ---- appearance ---- */
    wrap.appendChild(h("div", { class: "settings-group" },
      h("h4", {}, "Appearance"),
      row("Theme", null, select(
        [["obsidian", "Obsidian"], ["glacier", "Glacier"], ["ember", "Ember"], ["mono", "Mono"]],
        s.theme, v => updateSettings({ theme: v }))),
      toggleRow("High contrast", "stronger text and borders", s.highContrast,
        v => updateSettings({ highContrast: v })),
      row("Text size", null, select(
        [["0.9", "Compact"], ["1", "Default"], ["1.1", "Large"], ["1.25", "Extra large"]],
        String(s.textScale), v => updateSettings({ textScale: parseFloat(v) }))),
      row("Language / Langue / Idioma", "interface language", select(
        [["en", "English"], ["fr", "Français"], ["es", "Español"], ["de", "Deutsch"]],
        s.language, v => updateSettings({ language: v }))),
    ));

    /* ---- motion & performance ---- */
    wrap.appendChild(h("div", { class: "settings-group" },
      h("h4", {}, "Motion & Performance"),
      row("Animations", null, select(
        [["full", "Full"], ["reduced", "Reduced"], ["off", "Off"]],
        s.animations, v => updateSettings({ animations: v }))),
      row("Visual quality", "particle budget & glow effects", select(
        [["auto", "Auto (device-aware)"], ["high", "High"], ["low", "Low (battery/quiet)"]],
        s.fxQuality, v => updateSettings({ fxQuality: v }))),
      toggleRow("Auto fullscreen", "enter fullscreen on first interaction", s.autoFullscreen,
        v => updateSettings({ autoFullscreen: v })),
      toggleRow("Developer mode", "pipeline timeline & runtime metrics", s.devMode,
        v => updateSettings({ devMode: v })),
    ));

    /* ---- voice ---- */
    const voiceControls = [];
    if (ttsAvailable()) {
      const voiceSel = select(
        [["", "System default"], ...getVoices().map(v => [v.voiceURI || v.name, `${v.name} (${v.lang})`])],
        s.voiceName, v => updateSettings({ voiceName: v }),
        { "aria-label": "Voice" });
      voiceControls.push(
        toggleRow("Speak replies", "read AI responses aloud (client-side TTS)", s.voiceOutput,
          v => { updateSettings({ voiceOutput: v }); if (!v) stopSpeaking(); }),
        row("Voice", null, voiceSel),
        row("Speech rate", null, (() => {
          const r = h("input", { type: "range", min: "0.5", max: "2", step: "0.1", value: s.voiceRate });
          r.addEventListener("change", () => updateSettings({ voiceRate: parseFloat(r.value) }));
          return r;
        })()),
      );
    } else {
      voiceControls.push(h("div", { class: "setting-desc" }, "Speech synthesis is not available in this browser."));
    }
    wrap.appendChild(h("div", { class: "settings-group" }, h("h4", {}, "Voice"), ...voiceControls));

    /* ---- core (server-side toggles) ---- */
    const coreGroup = h("div", { class: "settings-group" }, h("h4", {}, "Core"),
      h("div", { class: "setting-row" },
        h("div", {}, h("div", {}, "Model"),
          h("div", { class: "setting-desc" }, "configured server-side via GEMINI_MODEL")),
        h("span", { class: "mono", style: "font-size:12px" }, store.core.serverSettings.model || "—")),
    );
    const plannerRow = h("div", {}, "loading…");
    const criticRow = h("div", {}, "loading…");
    coreGroup.append(plannerRow, criticRow);
    wrap.appendChild(coreGroup);

    api("/api/settings").then(cfg => {
      store.core.serverSettings = cfg;
      clear(plannerRow);
      plannerRow.replaceWith(toggleRow("AI Planner", "multi-step planning (extra model call per turn)",
        cfg.planner_enabled, v => postJSON("/api/settings", { planner_enabled: v })
          .then(r => { store.core.serverSettings = r; })
          .catch(() => emit("toast", { text: "Couldn't update planner setting.", level: "error" }))));
      clear(criticRow);
      criticRow.replaceWith(toggleRow("Self-Critic", "reviews & improves draft answers",
        cfg.self_critic_enabled, v => postJSON("/api/settings", { self_critic_enabled: v })
          .then(r => { store.core.serverSettings = r; })
          .catch(() => emit("toast", { text: "Couldn't update self-critic setting.", level: "error" }))));
    }).catch(() => {
      plannerRow.textContent = "Core settings unavailable.";
    });

    /* ---- plugins note ---- */
    wrap.appendChild(h("div", { class: "settings-group" },
      h("h4", {}, "Plugins"),
      h("div", { class: "setting-desc" },
        `${store.core.tools?.length || 0} capability tools installed. Zerion's tools/ directory is the plugin system — ` +
        `drop in a tool file and it's discovered automatically.`),
    ));

    /* ---- welcome ---- */
    wrap.appendChild(h("div", { class: "settings-group" },
      h("h4", {}, "Welcome"),
      row("Welcome screen", "shown on first run; reopens from here", h("button", {
        class: "mini-btn", type: "button",
        onclick: async () => {
          const w = await import("./welcome.js");
          w.resetWelcome(); w.show();
        },
      }, "Show again")),
    ));

    clear(body); body.appendChild(wrap);

    return null;
  },
});

export function applySettingsNow() { applySettings(); }

export function initSettings() {
  applySettings();
  on("settings", applySettings);
  document.getElementById("btn-settings").addEventListener("click", () =>
    import("./floating.js").then(m => m.togglePanel("settings")));
  document.getElementById("btn-fullscreen").addEventListener("click", () => fullscreen.toggle());
  document.addEventListener("fullscreenchange", () => {
    document.getElementById("btn-fullscreen").setAttribute("aria-pressed", String(fullscreen.active()));
  });
}
