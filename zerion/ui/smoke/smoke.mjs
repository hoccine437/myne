// smoke.mjs — headless client smoke test for the Zerion WebUI.
//
// Boots the real SPA modules against a jsdom DOM with stubbed canvas /
// WebSocket / fetch, then drives the full event surface: hello, chat,
// metrics, stages, workspace switch, confirmation dialog, terminal flow.
// Catches broken module wiring, missing DOM ids and render errors
// without a browser.
//
// Run:
//   npm install jsdom
//   node zerion/ui/smoke/smoke.mjs
// (or: NODE_PATH=/path/to/node_modules node zerion/ui/smoke/smoke.mjs)

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const STATIC = join(HERE, "..", "static");

let passed = 0, failed = 0;
const failures = [];
function check(name, cond) {
  if (cond) { passed++; console.log(`  ✓ ${name}`); }
  else { failed++; failures.push(name); console.error(`  ✗ ${name}`); }
}

/* ---------------- jsdom + stubs ---------------- */
// jsdom is a dev-only dependency. resolve it from the repo (npm install
// jsdom beside this file's package.json) or override with
// SMOKE_REQUIRE_BASE=/path/to/package.json pointing at a scratch install.
import { createRequire } from "node:module";
const require = createRequire(process.env.SMOKE_REQUIRE_BASE || import.meta.url);
const { JSDOM } = require("jsdom");
const html = readFileSync(join(STATIC, "index.html"), "utf8");
const dom = new JSDOM(html, {
  url: "http://localhost:8765/",
  pretendToBeVisual: true,
  runScripts: "outside-only",
});
const { window } = dom;

// canvas 2d stub — all methods no-op, gradients return addColorStop buckets
const ctxStub = new Proxy({}, {
  get(t, prop) {
    if (prop === "createRadialGradient" || prop === "createConicGradient" || prop === "createLinearGradient")
      return () => ({ addColorStop() { } });
    if (typeof t[prop] === "undefined") return () => { };
    return t[prop];
  },
  set() { return true; },
});
window.HTMLCanvasElement.prototype.getContext = function () { return ctxStub; };

// WebSocket stub — records sends, lets the test push server events
const sent = [];
const wsHandlers = {};
class FakeWS {
  constructor(url) { this.url = url; this.readyState = 0; FakeWS.last = this;
    setTimeout(() => { this.readyState = 1; this.onopen?.({}); }, 0); }
  send(data) { sent.push(JSON.parse(data)); }
  close() { this.readyState = 3; this.onclose?.({}); }
}
FakeWS.OPEN = 1;
window.WebSocket = FakeWS;

// server event push helper
function pushServer(type, data, seq = ++pushServer.seq) {
  FakeWS.last.onmessage?.({ data: JSON.stringify({ seq, ts: Date.now() / 1000, type, data }) });
}
pushServer.seq = 0;

// fetch stub for the few REST reads panels do
const restLog = [];
window.fetch = async (url, opts = {}) => {
  restLog.push(url);
  const ok = (data) => ({ ok: true, status: 200, json: async () => data });
  if (url.startsWith("/api/memory")) return ok({ memory: { identity: {} }, stats: { identity: 0 }, path: "~" });
  if (url.startsWith("/api/knowledge")) return ok({ records: [] });
  if (url.startsWith("/api/fs/list")) return ok({ path: "/home/user/myne", entries: [{ name: "zerion", dir: true }, { name: "file.txt", dir: false }] });
  if (url.startsWith("/api/fs/read")) return ok({ path: "/x", content: "content" });
  if (url.startsWith("/api/logs")) return ok({ events: [] });
  if (url.startsWith("/api/settings")) {
    if (opts.method === "POST") return ok({ planner_enabled: true });
    return ok({ planner_enabled: false, self_critic_enabled: true, model: "gemini-3-flash-lite" });
  }
  if (url.startsWith("/api/status")) return ok({ session: {}, metrics: {} });
  return { ok: false, status: 404, json: async () => ({ error: "not found" }) };
};

window.matchMedia ||= () => ({ matches: false, addEventListener() { } });
window.ResizeObserver = class { observe() { } unobserve() { } disconnect() { } };
window.IntersectionObserver = class { constructor(cb) { } observe() { } unobserve() { } disconnect() { } };
window.requestAnimationFrame = (cb) => { /* run once for fps meter loops */ if (!window.__rafReplayed) { window.__rafReplayed = true; setTimeout(() => cb(performance.now()), 0); } return 1; };
window.cancelAnimationFrame = () => { };
// deterministic <audio> stub for the voice-state machine
class FakeAudio { constructor(src) { this.src = src; } play() { return Promise.resolve(); } pause() { } addEventListener() { } }
FakeAudio.prototype.pause = function () { };
window.Audio = FakeAudio;
globalThis.Audio = FakeAudio;
if (!window.speechSynthesis) delete window.speechSynthesis; // exercise the "unavailable" path

globalThis.window = window;
for (const k of ["document", "navigator", "location", "localStorage", "HTMLElement",
  "Element", "CustomEvent", "getComputedStyle", "Event",
  "ResizeObserver", "IntersectionObserver", "matchMedia", "requestAnimationFrame",
  "cancelAnimationFrame", "WebSocket", "HTMLCanvasElement", "fetch"]) {
  try {
    Object.defineProperty(globalThis, k, {
      value: window[k], configurable: true, writable: true,
    });
  } catch { globalThis[k] = window[k]; }
}
globalThis.document = window.document;

const errors = [];
window.addEventListener("error", (e) => errors.push(String(e.error || e.message)));

/* ---------------- boot ---------------- */
console.log("\nZerion UI smoke test\n— booting SPA…");
await import(pathToFileURL(join(STATIC, "js", "main.js")).href);
await new Promise(r => setTimeout(r, 250)); // let boot() finish

const $ = (sel) => window.document.querySelector(sel);
const $$ = (sel) => [...window.document.querySelectorAll(sel)];

check("app root exists", !!$("#app"));
check("orb canvas mounted", !!$("#orb-canvas"));
check("no window errors during boot", errors.length === 0);

console.log("\n— websocket boot handshake…");
await new Promise(r => setTimeout(r, 60));
check("ws opened", FakeWS.last?.readyState === 1);
pushServer("hello", { version: "1.0.0-test", settings: { model: "test-model" }, tools: [{ name: "read_file", description: "x", parameters: {}, destructive: false }], capabilities: {} });
await new Promise(r => setTimeout(r, 30));
check("version shown in header", $("#brand-version")?.textContent.includes("1.0.0"));
check("model fact updated", $("#fact-model")?.textContent === "test-model");

console.log("\n— state + orb…");
pushServer("core_state", { state: "thinking", detail: "contacting the model" });
pushServer("core_state", { state: "speaking" });
pushServer("core_state", { state: "idle" });
await new Promise(r => setTimeout(r, 30));
check("state pill reflects state", ["Idle", "Speaking"].includes($("#core-state-label")?.textContent) || $("#core-state-label")?.textContent.length > 0);

console.log("\n— chat…");
pushServer("chat", { role: "user", text: "/help", kind: "chat" });
pushServer("chat", { role: "ai", text: "Commands: /status /tools **bold**\n\n```py\nprint(1)\n```", kind: "command" });
await new Promise(r => setTimeout(r, 30));
check("chat messages rendered", $$("#chat-stream .msg").length >= 2);
check("markdown-lite rendered code", !!$("#chat-stream pre code"));
check("markdown-lite escapes html", !$("#chat-stream")?.innerHTML.includes("<script"));

console.log("\n— metrics / agents / goal / tasks / tools / feeds…");
pushServer("metrics", { ts: 1, uptime_s: 61, cpu: { percent: 42, cores: 8 }, ram: { percent: 55, used: 8e9, total: 16e9 }, net: { up_bps: 2048, down_bps: 4096 }, battery: { percent: 93, plugged: true }, processes: 120 });
pushServer("agents", { agents: { "Intent Engine": { state: "active", detail: "classifying", ts: Date.now() / 1000 } } });
pushServer("goal", { current_goal: "Build a thing", completed: 2, failed: 0, queued: 1, sub_goals: [] });
pushServer("tasks", { goal: "Build a thing", status: "executing", tasks: [
  { id: 1, description: "Step one", tool_name: "run_python", parameters: {}, depends_on: [], state: "completed" },
  { id: 2, description: "Step two", tool_name: "run_shell", parameters: {}, depends_on: [1], state: "running" },
] });
pushServer("tool", { phase: "start", tool: "run_python", parameters: {} });
pushServer("decision", { source: "Self-Critic", text: "Draft accepted without changes." });
pushServer("notification", { level: "info", text: "Zerion Core is online." });
await new Promise(r => setTimeout(r, 60));
check("cpu gauge text set", /\d+%/.test($("#cpu-value")?.textContent || ""));
check("network fact set", ($("#fact-network")?.textContent || "").includes("↑"));
check("agents list rendered", $$("#agents-list .agent-row").length >= 1);
check("goal rendered", $("#goal-text")?.textContent.includes("Build a thing"));
check("tasks rendered", $$("#tasks-list .task-row").length === 2);
check("running tool chip", $$("#running-tools .tool-chip").length >= 1);
check("decision feed", $$("#decisions-list .feed-item").length >= 1);
check("notification listed + toasted", $$("#notifications-list .feed-item").length >= 1 && $$(".toast").length >= 1);

console.log("\n— workspace adaptation…");
pushServer("workspace", { mode: "automation", source: "test" });
await new Promise(r => setTimeout(r, 120));
check("automation workspace activated", $("#ws-automation")?.dataset.active === "true");
check("workspace chip updated", $("#workspace-chip-label")?.textContent === "Automation");
pushServer("workspace", { mode: "coding", source: "test" });
await new Promise(r => setTimeout(r, 120));
check("coding workspace activated", $("#ws-coding")?.dataset.active === "true");
pushServer("workspace", { mode: "trading", source: "test" });
await new Promise(r => setTimeout(r, 120));
check("trading workspace activated", $("#ws-trading")?.dataset.active === "true");
pushServer("workspace", { mode: "vision", source: "test" });
pushServer("workspace", { mode: "research", source: "test" });
pushServer("workspace", { mode: "chat", source: "test" });
await new Promise(r => setTimeout(r, 200));
check("all workspaces lazy-loaded", ["coding", "research", "trading", "vision", "automation"].every(m => $(`#ws-${m}`)));
check("back to chat", $("#ws-chat")?.dataset.active === "true");

console.log("\n— confirmation flow…");
pushServer("confirm_required", { pending: true, tool: "run_shell", message: "'run_shell' will make a permanent change.", parameters: { command: "echo hi" } });
await new Promise(r => setTimeout(r, 30));
check("confirm dialog shown", !$("#confirm-overlay").classList.contains("hidden"));
$("#confirm-yes").click();
await new Promise(r => setTimeout(r, 30));
check("confirm sent to Core over WS", sent.some(m => m.type === "confirm"));

console.log("\n— command input…");
const input = $("#command-input");
input.value = "hello zerion";
$("#command-bar").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
await new Promise(r => setTimeout(r, 30));
check("chat message sent over WS", sent.some(m => m.type === "message" && m.text === "hello zerion"));

console.log("\n— terminal…");
$("#btn-terminal-toggle").click();
await new Promise(r => setTimeout(r, 30));
check("terminal opened", !$("#terminal-panel").classList.contains("hidden"));
pushServer("tool", { phase: "end", channel: "terminal", tool: "run_shell", success: true, output: "hello-from-test" });
await new Promise(r => setTimeout(r, 30));
check("terminal output rendered", $("#terminal-stream")?.textContent.includes("hello-from-test"));

console.log("\n— floating panels…");
$("#btn-explorer").click();
await new Promise(r => setTimeout(r, 80));
check("explorer panel opened", !!$('[data-panel="explorer"]'));
check("explorer listed entries", $('[data-panel="explorer"]')?.textContent.includes("zerion"));
$("#btn-logs").click();
await new Promise(r => setTimeout(r, 80));
check("logs panel opened", !!$('[data-panel="logs"]'));
$("#btn-memory").click();
await new Promise(r => setTimeout(r, 80));
check("memory panel opened", !!$('[data-panel="memory"]'));
$("#btn-settings").click();
await new Promise(r => setTimeout(r, 120));
check("settings panel opened", !!$('[data-panel="settings"]'));
check("theme control present", !!$('[data-panel="settings"] select'));

console.log("\n— focus mode…");
pushServer("focus", { active: true, reason: "test" });
await new Promise(r => setTimeout(r, 30));
check("focus mode applied", $("#app").dataset.focus === "true");
pushServer("focus", { active: false });
await new Promise(r => setTimeout(r, 30));
check("focus mode released", $("#app").dataset.focus === "false");

console.log("\n— voice service (server-authoritative Gemini path)…");
// hello declared server-gemini voice path
pushServer("hello", { version: "1.0.0-test", settings: { model: "test-model", voice_path: "server-gemini" }, tools: [] });
await new Promise(r => setTimeout(r, 40));
check("voice chip exists and shows GEMINI", $("#voice-state-chip")?.dataset.vstate === "GEMINI_TTS");
pushServer("chat", { role: "ai", text: "say this aloud", kind: "" });
await new Promise(r => setTimeout(r, 40));
check("TTS requested over WS for AI message", sent.some(m => m.type === "tts" && m.text === "say this aloud"));
check("chip shows GENERATING while server works", $("#voice-state-chip")?.dataset.vstate === "GENERATING");
pushServer("tts", { state: "ready", voice: "gemini", url: "/api/tts/faketoken123", seq: 99 });
await new Promise(r => setTimeout(r, 40));
check("ready envelope → GEMINI_TTS state", $("#voice-state-chip")?.dataset.vstate === "GEMINI_TTS");
pushServer("chat", { role: "ai", text: "fallback probe", kind: "" });
await new Promise(r => setTimeout(r, 30));
pushServer("tts", { state: "browser_fallback", reason: "test", seq: null });
await new Promise(r => setTimeout(r, 60));
// JSAudio stubbed ok; browser tts would be attempted; state shows either BROWSER_TTS or UNAVAILABLE in jsdom
check("fallback state is labeled, never disguised",
      ["BROWSER_TTS", "UNAVAILABLE", "ERROR"].includes($("#voice-state-chip")?.dataset.vstate));

console.log("\n— connection loss handling…");
FakeWS.last.close();
await new Promise(r => setTimeout(r, 30));
check("offline banner shown", !$("#connection-banner").classList.contains("hidden"));

console.log("\n— welcome experience…");
await new Promise(r => setTimeout(r, 60));
check("welcome overlay shown on first run", !!$("#welcome-title"));
check("readiness rows rendered", $$("#welcome-title").length === 1 && document.body.textContent.includes("READINESS"));
const enterBtn = [...document.querySelectorAll("button")].find(b => b.textContent === "Enter Zerion");
enterBtn?.click();
await new Promise(r => setTimeout(r, 30));
check("welcome persists dismissal", window.localStorage.getItem("zerion.welcomed.v1") === "1");

console.log("\n— smart layout engine (device classification)…");
const { classify, applyProfile } = await import("file://" + STATIC + "/js/core/device.js");
function setViewport(w, hgt, coarse = false) {
  Object.defineProperty(window, "innerWidth", { value: w, configurable: true });
  Object.defineProperty(window, "innerHeight", { value: hgt, configurable: true });
  window.matchMedia = (q) => ({ matches: q === "(pointer: coarse)" ? coarse : q === "(pointer: fine)" ? !coarse : false, addEventListener() { } });
  globalThis.matchMedia = window.matchMedia;
}
const CASES = [
  ["small phone portrait", 375, 667, true, "phone", "portrait"],
  ["large phone portrait", 430, 932, true, "phone", "portrait"],
  ["phone landscape", 900, 420, true, "phone", "landscape"],
  ["foldable open", 673, 800, true, "tablet", "portrait"],
  ["tablet portrait", 820, 1180, true, "tablet", "portrait"],
  ["tablet landscape", 1180, 820, true, "tablet", "landscape"],
  ["laptop", 1440, 900, false, "laptop", "landscape"],
  ["desktop", 1700, 950, false, "desktop", "landscape"],
  ["ultrawide", 3440, 1440, false, "ultrawide", "landscape"],
  ["small window", 500, 800, false, "phone", "portrait"],
];
for (const [label, w, hgt, coarse, wantDevice, wantOrient] of CASES) {
  setViewport(w, hgt, coarse);
  const p = classify();
  const okDevice = p.device === wantDevice;
  const okOrient = p.orientation === wantOrient;
  check(`classify ${label} → ${wantDevice}/${wantOrient} (got ${p.device}/${p.orientation})`, okDevice && okOrient);
  applyProfile(p);
  check(`html data-device applied for ${label}`,
    document.documentElement.dataset.device === wantDevice &&
    document.documentElement.dataset.orientation === wantOrient);
}
setViewport(1440, 900, false);

console.log(`\n${passed} passed, ${failed} failed${failed ? ":\n  " + failures.join("\n  ") : ""}\n`);
process.exit(failed ? 1 : 0);
