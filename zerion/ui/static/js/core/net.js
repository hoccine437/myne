// core/net.js — Core connectivity: WebSocket event stream + REST helpers.
//
// The socket is the primary channel (server → client events, client →
// Core messages). It auto-reconnects with capped backoff and replays
// missed events using the server's seq buffer, so state survives flaky
// networks with zero loss of causally-visible information.

import { emit } from "./bus.js";
import { store } from "./store.js";

let ws = null;
let reconnectTimer = null;
let backoff = 800;
const BACKOFF_MAX = 12000;
const queue = [];

function wsUrl() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/ws`;
}

function flushQueue() {
  while (queue.length && ws?.readyState === WebSocket.OPEN) {
    ws.send(queue.shift());
  }
}

export function send(payload) {
  const raw = JSON.stringify(payload);
  if (ws?.readyState === WebSocket.OPEN) ws.send(raw);
  else queue.push(raw);
}

export const core = {
  message: (text) => send({ type: "message", text }),
  confirm: () => send({ type: "confirm" }),
  cancel: () => send({ type: "cancel" }),
  terminal: (command) => send({ type: "terminal", command }),
  tts: (text, seq) => send({ type: "tts", text, seq }),
};

export function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;

  ws = new WebSocket(wsUrl());

  ws.onopen = () => {
    backoff = 800;
    const replayed = store.seq > 0;
    // Ask the server for anything we missed since the last live event.
    if (replayed) send({ type: "replay", since_seq: store.seq });
    flushQueue();
    store.core.connected = true;
    emit("connection", { connected: true, replayed });
  };

  ws.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }
    if (msg.seq && msg.seq <= store.seq && msg.type !== "hello") return; // duplicate after replay
    if (msg.seq > store.seq) store.seq = msg.seq;
    if (msg.type === "hello") {
      Object.assign(store.core, {
        version: msg.data.version || "",
        serverSettings: msg.data.settings || {},
        tools: msg.data.tools || [],
      });
      store.boot = msg.data;
      emit("hello", msg.data);
      return;
    }
    emit("core:" + msg.type, msg.data, msg);
    emit("core:event", msg);
  };

  ws.onclose = () => {
    store.core.connected = false;
    emit("connection", { connected: false });
    scheduleReconnect();
  };

  ws.onerror = () => { try { ws.close(); } catch { /* closing anyway */ } };
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    backoff = Math.min(backoff * 1.7, BACKOFF_MAX);
    connect();
  }, backoff);
}

export async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = `${res.status}`;
    try { detail = (await res.json()).error || detail; } catch { /* keep status */ }
    throw new Error(detail);
  }
  return res.json();
}

export function postJSON(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// Keepalive — some proxies idle-close sockets.
setInterval(() => { if (ws?.readyState === WebSocket.OPEN) send({ type: "ping" }); }, 25000);

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && (!ws || ws.readyState > WebSocket.OPEN)) {
    connect(); // seq is kept — the server replays only what we missed
  }
});
