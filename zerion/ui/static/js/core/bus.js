// core/bus.js — minimal typed event emitter used across all UI modules

const listeners = new Map();

export function on(type, fn) {
  if (!listeners.has(type)) listeners.set(type, new Set());
  listeners.get(type).add(fn);
  return () => off(type, fn);
}

export function off(type, fn) {
  listeners.get(type)?.delete(fn);
}

export function emit(type, data) {
  const set = listeners.get(type);
  if (set) for (const fn of [...set]) {
    try { fn(data); } catch (err) { console.error(`[bus] ${type} handler failed`, err); }
  }
  const all = listeners.get("*");
  if (all) for (const fn of [...all]) {
    try { fn(type, data); } catch (err) { console.error("[bus] * handler failed", err); }
  }
}
