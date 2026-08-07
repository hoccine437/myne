// modules/statuspanel.js — left rail: CPU/RAM gauges with sparkline
// history, model/memory/network facts, and the Active Agents roster
// (which Core engines did something recently).

import { h, clear, fmtBytes, fmtBits, fmtUptime } from "../core/dom.js";
import { on } from "../core/bus.js";
import { store } from "../core/store.js";

const SPARK_LEN = 60;
const cpuHist = [];
const ramHist = [];

function pushCapped(arr, v) {
  arr.push(v);
  if (arr.length > SPARK_LEN) arr.shift();
}

function drawSpark(canvas, hist) {
  const ctx = canvas.getContext("2d");
  const { width: w, height: hh } = canvas;
  ctx.clearRect(0, 0, w, hh);
  if (hist.length < 2) return;
  const css = getComputedStyle(canvas);
  const accent = css.getPropertyValue("--accent").trim() || "#66e3ff";
  ctx.strokeStyle = accent;
  ctx.globalAlpha = 0.85;
  ctx.lineWidth = 1.4;
  ctx.beginPath();
  hist.forEach((v, i) => {
    const x = (i / (SPARK_LEN - 1)) * w;
    const y = hh - 2 - (Math.min(v, 100) / 100) * (hh - 4);
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
  // soft fill under the line
  ctx.globalAlpha = 0.12;
  ctx.lineTo(w, hh); ctx.lineTo(0, hh); ctx.closePath();
  ctx.fillStyle = accent;
  ctx.fill();
  ctx.globalAlpha = 1;
}

function renderMetrics(m) {
  store.runtime.metrics = m;
  const cpu = m.cpu?.percent, ram = m.ram;

  const cpuVal = document.getElementById("cpu-value");
  const ramVal = document.getElementById("ram-value");
  if (cpuVal) cpuVal.textContent = cpu == null ? "—" : `${cpu.toFixed(0)}%  ·  ${m.cpu.cores ?? "?"} cores`;
  if (ramVal) ramVal.textContent = ram.percent == null ? "—"
    : `${ram.percent.toFixed(0)}%  ·  ${fmtBytes(ram.used)} / ${fmtBytes(ram.total)}`;

  document.getElementById("cpu-bar").style.width = `${cpu ?? 0}%`;
  document.getElementById("ram-bar").style.width = `${ram.percent ?? 0}%`;

  if (cpu != null) { pushCapped(cpuHist, cpu); drawSpark(document.getElementById("cpu-spark"), cpuHist); }
  if (ram.percent != null) { pushCapped(ramHist, ram.percent); drawSpark(document.getElementById("ram-spark"), ramHist); }

  const net = m.net;
  const netText = (net.up_bps == null && net.down_bps == null) ? "—"
    : `↑ ${fmtBits(net.up_bps)}  ↓ ${fmtBits(net.down_bps)}`;
  document.getElementById("fact-network").textContent = netText;
  document.getElementById("fact-uptime").textContent = fmtUptime(m.uptime_s);
}

function renderModelFacts() {
  const s = store.core.serverSettings || {};
  const model = document.getElementById("fact-model");
  if (model) {
    model.textContent = s.model || "—";
    model.title = `${s.provider || ""} · text model · speech: ${s.tts_model || "n/a"}`;
  }
  const version = document.getElementById("brand-version");
  if (version && store.core.version) version.textContent = "v" + store.core.version;
}

let memoryFact = "";
on("core:memory_update", () => { refreshMemoryFact(); });

async function refreshMemoryFact() {
  try {
    const { stats } = await (await import("../core/net.js")).api("/api/memory");
    const total = Object.values(stats || {}).reduce((a, b) => a + b, 0);
    memoryFact = `${total} entries`;
  } catch { memoryFact = "—"; }
  const el = document.getElementById("fact-memory");
  if (el) el.textContent = memoryFact;
}

function renderAgents(agents) {
  store.runtime.agents = agents;
  const list = document.getElementById("agents-list");
  const order = Object.entries(agents); // stable insertion order from server
  const now = Date.now() / 1000;
  let activeCount = 0;
  clear(list);
  for (const [name, info] of order) {
    const fresh = info.ts && now - info.ts < 30;
    const state = fresh ? info.state : "standby";
    if (state === "active") activeCount++;
    list.appendChild(h("li", { class: "agent-row", dataset: { state } },
      h("span", { class: "agent-dot" }),
      h("span", { class: "agent-name" }, name),
      h("span", { class: "agent-detail" }, fresh ? (info.detail || state) : "standby"),
    ));
  }
  document.getElementById("agents-count").textContent = activeCount ? `${activeCount} active` : "";
}

export function initStatusPanel() {
  on("core:metrics", renderMetrics);
  on("core:agents", (d) => renderAgents(d.agents || {}));
  on("hello", () => { renderModelFacts(); refreshMemoryFact(); });
  // agents dim back to standby on a timer even without new events
  setInterval(() => {
    if (Object.keys(store.runtime.agents).length) renderAgents(store.runtime.agents);
  }, 30000);
}
