// core/store.js — central client state: settings (persisted), live Core
// state, derived device profile. Modules read from here; writes go
// through the helpers so persistence + bus emission stay consistent.

import { emit } from "./bus.js";

const SETTINGS_KEY = "zerion.settings.v1";

const DEFAULT_SETTINGS = {
  theme: "obsidian",          // obsidian | glacier | ember | mono
  language: "en",             // en | fr | es | de
  highContrast: false,
  textScale: 1,               // 0.9 | 1 | 1.1 | 1.25
  animations: "full",         // full | reduced | off
  fxQuality: "auto",          // auto | high | low
  autoFullscreen: false,
  voiceOutput: true,          // browser TTS for AI replies
  voiceName: "",              // speechSynthesis voice URI ("" = default)
  voiceRate: 1,
  devMode: false,
  dockCollapsed: false,
};

function loadSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return { ...DEFAULT_SETTINGS, ...parsed };
    }
  } catch { /* corrupted settings reset to defaults */ }
  return { ...DEFAULT_SETTINGS };
}

export const store = {
  settings: loadSettings(),

  core: {
    state: "idle",          // idle|thinking|listening|speaking|searching|coding|learning|updating|error|success
    stateDetail: "",
    version: "",
    serverSettings: {},     // runtime Core toggles from /api/settings
    tools: [],
    connected: false,
  },

  boot: null,               // hello/bootstrap payload (welcome readiness etc.)

  runtime: {
    workspace: "chat",      // adaptive workspace mode
    focus: false,
    metrics: null,
    agents: {},
    goal: null,
    tasks: null,            // latest planner workflow snapshot
    runningTools: [],       // [{tool, phase, ...}]
    pendingConfirm: null,   // confirm_required payload
  },

  seq: 0,                   // last event seq seen (for replay on reconnect)
};

export function updateSettings(patch) {
  Object.assign(store.settings, patch);
  try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(store.settings)); } catch { /* private mode */ }
  emit("settings", store.settings);
}
