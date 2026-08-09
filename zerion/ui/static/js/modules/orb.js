// modules/orb.js — the Zerion Core visualization.
//
// NOW: a blue interactive STARFIELD. Dense point-stars on a black field,
// linked like a constellation, parallax by depth, pointer-responsive,
// and state-driven (speaking = center waves keyed to the voice amplitude,
// thinking = inward swirl, error = fast jitter, etc.).
//
// Public contract (unchanged): initOrb() → orb with
//   setState(state, detail), setAgents(n), setTools(list), setAmplitude(0..1)
// DOM ids unchanged:  #orb-canvas,  #orb-caption
//
// Performance contract (unchanged): one rAF loop, zero per-frame
// allocations, budget scaled by fx quality/device, auto-pauses when hidden.

import { on } from "../core/bus.js";
import { store } from "../core/store.js";

const TAU = Math.PI * 2;

// blue-only palette (user spec): deep denim → electric azure → ice
const BLUE_DEEP = [26, 55, 207];    // #1a37cf
const BLUE      = [42, 92, 255];    // #2a5cff
const BLUE_SKY  = [77, 163, 255];   // #4da3ff
const BLUE_ICE  = [143, 208, 255];  // #8fd0ff
const BLUE_BRIGHT = [207, 231, 255]; // #cfe7ff

function tint(rgb, a) { return `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${a})`; }

// per-state motion language: which subsystem runs + how hard
const STATES = {
  idle:      { label: "IDLE",     swirl: 0.0,  wave: false, scan: 0, jitter: 0.0,  speed: 0.22, breathe: 0.05, glow: 0.55 },
  ready:     { label: "READY",    swirl: 0.1,  wave: false, scan: 0, jitter: 0.0,  speed: 0.28, breathe: 0.05, glow: 0.60 },
  thinking:  { label: "THINKING", swirl: 1.0,  wave: false, scan: 0, jitter: 0.10, speed: 1.7,  breathe: 0.09, glow: 0.80 },
  analyzing: { label: "ANALYZING",swirl: 0.5,  wave: false, scan: 1, jitter: 0.05, speed: 1.25, breathe: 0.07, glow: 0.75 },
  executing: { label: "EXECUTING",swirl: 0.6,  wave: false, scan: 0, jitter: 0.08, speed: 1.6,  breathe: 0.08, glow: 0.90 },
  listening: { label: "LISTENING",swirl: 0.0,  wave: false, scan: 0, jitter: 0.0,  speed: 0.5,  breathe: 0.10, glow: 0.60 },
  speaking:  { label: "SPEAKING", swirl: 0.2,  wave: true,  scan: 0, jitter: 0.05, speed: 0.8,  breathe: 0.10, glow: 0.95 },
  searching: { label: "SEARCHING",swirl: 0.4,  wave: false, scan: 1, jitter: 0.06, speed: 1.1,  breathe: 0.07, glow: 0.75 },
  coding:    { label: "CODING",   swirl: 0.5,  wave: false, scan: 0, jitter: 0.12, speed: 1.05, breathe: 0.07, glow: 0.85 },
  learning:  { label: "LEARNING", swirl: 0.9,  wave: false, scan: 0, jitter: 0.06, speed: 1.3,  breathe: 0.09, glow: 0.85 },
  updating:  { label: "SELF-UPGRADING", swirl: 0.4, wave: false, scan: 1, jitter: 0.15, speed: 1.5, breathe: 0.06, glow: 0.85 },
  warning:   { label: "WARNING",  swirl: 0.2,  wave: false, scan: 0, jitter: 0.18, speed: 0.55, breathe: 0.16, glow: 0.80 },
  offline:   { label: "OFFLINE",  swirl: 0.0,  wave: false, scan: 0, jitter: 0.0,  speed: 0.08, breathe: 0.02, glow: 0.25 },
  focus:     { label: "FOCUS MODE", swirl: 0.15, wave: false, scan: 0, jitter: 0.0, speed: 0.3, breathe: 0.04, glow: 0.50 },
  error:     { label: "FAULT",    swirl: 0.7,  wave: false, scan: 0, jitter: 1.0,  speed: 1.9,  breathe: 0.12, glow: 1.00 },
  success:   { label: "DONE",     swirl: 0.3,  wave: false, scan: 0, jitter: 0.0,  speed: 1.4,  breathe: 0.08, glow: 1.00 },
};

class Starfield {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d", { alpha: false });
    this.dpr = 1;
    this.w = 0; this.h = 0; this.cx = 0; this.cy = 0;
    // "Zerion's position" = stage center (voice/emission origin)
    this.center = { x: 0, y: 0 };

    this.cur = { swirl: 0, speed: 0.22, breathe: 0.05, jitter: 0, glow: 0.55 };
    this.target = { ...this.cur };
    this.state = "idle";
    this.behavior = STATES.idle;

    this.amp = 0;              // voice amplitude 0..1 (set externally)
    this.ampSm = 0;
    this.pulse = 0;            // driving phase
    this.swirlPhase = 0;
    this.scanX = -1;
    this.burstT = -1;
    this.errorUntil = 0;
    this.visible = true;
    this.quality = 1;

    this.pointer = { x: -1e9, y: -1e9 };   // far offscreen until first touch/mouse
    this.agentNodes = 0;
    this.toolsActive = [];

    this.stars = [];
    this.burst = [];
    this.waves = [];
    this.waveT = 0;

    this._resize = this.resize.bind(this);
    this._frame = this.frame.bind(this);

    on("core:core_state", (d) => this.setState(d.state, d.detail));
    on("device", () => this.resize());
    on("settings", () => this.applySettings());
  }

  applySettings() {
    const q = store.settings.fxQuality;
    const p = store.device || { device: "desktop" };
    let budget = 1;
    if (q === "low") budget = 0.45;
    else if (q === "auto") {
      budget = p.device === "phone" ? 0.55 : p.device === "tablet" ? 0.8 : 1;
    }
    this.quality = budget;
    this.seed();
  }

  attach() {
    this.applySettings();
    this.resize();
    if ("ResizeObserver" in window) {
      new ResizeObserver(this._resize).observe(this.canvas.parentElement);
    }
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) this.last = 0;
    });
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(([e]) => { this.visible = e.isIntersecting; }, { threshold: 0.02 })
        .observe(this.canvas);
    }
    // pointer interaction: stars lean toward the pointer (from anywhere on stage)
    const host = this.canvas.parentElement || this.canvas;
    host.addEventListener("pointermove", (e) => {
      const r = this.canvas.getBoundingClientRect();
      this.pointer.x = e.clientX - r.left;
      this.pointer.y = e.clientY - r.top;
    });
    host.addEventListener("pointerleave", () => {
      this.pointer.x = -1e9; this.pointer.y = -1e9;
    });
    this.running = true;
    requestAnimationFrame((t) => { this.last = t; requestAnimationFrame(this._frame); });
  }

  resize() {
    const rect = this.canvas.parentElement.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    const dpr = Math.min((store.device?.dpr || 1), 2);
    this.dpr = dpr;
    this.w = Math.round(rect.width); this.h = Math.round(rect.height);
    this.canvas.width = Math.round(rect.width * dpr);
    this.canvas.height = Math.round(rect.height * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.cx = this.w / 2; this.cy = this.h / 2;
    this.center = { x: this.cx, y: this.cy };
    this.seed();
  }

  seed() {
    // dense field: ~1 star per 3200px² on desktop, scaled by quality; 3 parallax layers
    const area = Math.max(1000, this.w * this.h);
    const n = Math.max(80, Math.round(area / 3200 * this.quality));
    if (this.stars.length === n) return;
    this.stars = new Array(n);
    for (let i = 0; i < n; i++) {
      const layer = i % 3;                       // 0 far, 1 mid, 2 near
      this.stars[i] = {
        x: Math.random() * this.w, y: Math.random() * this.h,
        r: (0.55 + Math.random() * 1.35) * (0.7 + layer * 0.35),
        baseVx: (Math.random() - 0.5) * 0.12 * (layer + 1),
        baseVy: (Math.random() - 0.5) * 0.10 * (layer + 1),
        layer,
        tw: Math.random() * TAU,
        twSpeed: 0.9 + Math.random() * 1.9,
        ox: 0, oy: 0,                            // live offset from pointer/swirl/wave
      };
    }
    // spatial grid for constellation links (cell = link distance)
    this.cell = 48;
    this.grid = null;   // rebuilt each frame — Map cells → index lists
  }

  setState(state, detail = "") {
    this.state = state in STATES ? state : "idle";
    this.behavior = STATES[this.state];
    const t = this.behavior;
    this.target = { swirl: t.swirl, speed: t.speed, breathe: t.breathe,
                    jitter: t.jitter, glow: t.glow };
    const caption = document.getElementById("orb-caption");
    if (caption) caption.textContent = detail ? `${t.label} — ${detail}` : t.label;
    if (this.state === "success") this.burstT = 0;
    if (this.state === "error") this.errorUntil = performance.now() + 2400;
  }

  setAgents(count) { this.agentNodes = Math.max(0, count | 0); }
  setTools(list) { this.toolsActive = Array.isArray(list) ? list.slice(0, 5) : []; }
  setAmplitude(v) { this.amp = Math.max(0, Math.min(1, v)); }
  setCenter(x, y) { this.center = { x, y }; }   // "follow Zerion's position"

  frame(now) {
    if (!this.running) return;
    requestAnimationFrame(this._frame);
    if (document.hidden || !this.visible) return;
    const dt = Math.min(0.05, this.last ? (now - this.last) / 1000 : 0.016);
    this.last = now;

    if (this.state === "error" && now > this.errorUntil) {
      this.setState(store.core.state === "error" ? "error" : "idle");
    }

    const k = 1 - Math.pow(0.0025, dt);
    for (const key of ["swirl", "speed", "breathe", "jitter", "glow"]) {
      this.cur[key] += (this.target[key] - this.cur[key]) * k;
    }
    this.ampSm += (this.amp - this.ampSm) * (1 - Math.pow(0.001, dt));

    this.pulse += dt * 1.9;
    this.swirlPhase += dt * (0.4 + this.cur.speed);
    this.render(dt, now / 1000);
  }

  render(dt, t) {
    const { ctx, w, h } = this;
    const c = this.cur;
    const cx = this.center.x, cy = this.center.y;

    // --- black field (user spec) ---
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, w, h);

    // center glow (blue, gentle, alive with state)
    const breathe = 1 + Math.sin(this.pulse) * c.breathe * (1 + this.ampSm * 1.7);
    if (c.glow > 0.05) {
      const gr = Math.min(w, h) * 0.42 * breathe;
      if (gr > 4) {
        const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, gr);
        g.addColorStop(0, tint(BLUE_SKY, 0.22 * c.glow * breathe));
        g.addColorStop(0.5, tint(BLUE, 0.10 * c.glow));
        g.addColorStop(1, tint(BLUE, 0));
        ctx.fillStyle = g;
        ctx.fillRect(cx - gr, cy - gr, gr * 2, gr * 2);
      }
    }

    // --- move stars (drift + swirl + pointer lean + wave push) ---
    const ptr = this.pointer;
    const hasPtr = ptr.x > -1e8;
    const linkN = this.stars.length;
    for (let i = 0; i < linkN; i++) {
      const s = this.stars[i];
      // base drift with edge wrap
      s.x += s.baseVx * (0.4 + c.speed) * dt * 22;
      s.y += s.baseVy * (0.4 + c.speed) * dt * 22;
      if (s.x < -4) s.x = w + 4; else if (s.x > w + 4) s.x = -4;
      if (s.y < -4) s.y = h + 4; else if (s.y > h + 4) s.y = -4;

      // state motion — swirl toward zerion's center (rotate around cx/cy)
      let ox = 0, oy = 0;
      if (c.swirl > 0.01) {
        const dx = s.x - cx, dy = s.y - cy;
        const dist = Math.max(30, Math.sqrt(dx * dx + dy * dy));
        const tangential = this.swirlPhase * c.swirl * (12000 / (dist * dist + 400)) * 60;
        const nx = dx / dist, ny = dy / dist;
        ox -= ny * tangential * dt * dist * 0.12;
        oy += nx * tangential * dt * dist * 0.12;
        // mild inward pull while thinking
        ox -= nx * c.swirl * 0.4 * dt * 18;
        oy -= ny * c.swirl * 0.4 * dt * 18;
      }

      // pointer interaction: stars lean toward the pointer (bounded force)
      if (hasPtr) {
        const dx = ptr.x - s.x, dy = ptr.y - s.y;
        const d2 = dx * dx + dy * dy;
        if (d2 < 120 * 120 && d2 > 4) {
          const f = (1 - d2 / (120 * 120));
          ox += dx * 0.015 * f * dt * 60;
          oy += dy * 0.015 * f * dt * 60;
        }
      }

      // speaking: center-driven wavefront pushes stars outward in pulses
      if (this.behavior.wave) {
        const dx = s.x - cx, dy = s.y - cy;
        const dist = Math.max(28, Math.sqrt(dx * dx + dy * dy));
        const phase = dist * 0.045 - t * (3.2 + this.ampSm * 4.5);
        const wob = Math.sin(phase);
        const force = wob * (0.55 + this.ampSm * 2.2);
        ox += (dx / dist) * force * dt * 26;
        oy += (dy / dist) * force * dt * 26;
      }

      // jitter (error / thinking storms)
      if (c.jitter > 0.01) {
        ox += (Math.random() - 0.5) * c.jitter * 90 * dt;
        oy += (Math.random() - 0.5) * c.jitter * 90 * dt;
      }

      s.ox = ox; s.oy = oy;
    }

    // --- constellation links (spatial grid, near pairs only) ---
    const cell = this.cell;
    const grid = this.grid && this.gridW === w ? this.grid : (this.gridW = w, this.grid = new Map());
    grid.clear();
    for (let i = 0; i < linkN; i++) {
      const s = this.stars[i];
      const kx = ((s.x / cell) | 0), ky = ((s.y / cell) | 0);
      const key = kx * 10000 + ky;
      let bucket = grid.get(key);
      if (bucket === undefined) { bucket = []; grid.set(key, bucket); }
      bucket.push(i);
    }
    const maxLinksPerCell = 6;
    ctx.lineWidth = 0.55;
    for (const [key, bucket] of grid) {
      const kx = (key / 10000) | 0, ky = key % 10000;
      let shared = 0;
      for (const ox of [-1, 0, 1]) {
        for (const oy of [-1, 0, 1]) {
          const other = grid.get((kx + ox) * 10000 + (ky + oy));
          if (!other) continue;
          for (const i of bucket) {
            for (const j of other) {
              if (j <= i || shared >= maxLinksPerCell) continue;
              const a = this.stars[i], b = this.stars[j];
              const dx = (a.x + a.ox) - (b.x + b.ox);
              const dy = (a.y + a.oy) - (b.y + b.oy);
              const d2 = dx * dx + dy * dy;
              if (d2 > cell * cell || d2 < 9) continue;
              const alpha = (1 - Math.sqrt(d2) / cell) * 0.34 * c.glow;
              ctx.strokeStyle = tint(BLUE_DEEP, alpha);
              ctx.beginPath();
              ctx.moveTo(a.x + a.ox, a.y + a.oy);
              ctx.lineTo(b.x + b.ox, b.y + b.oy);
              ctx.stroke();
              shared++;
            }
          }
        }
      }
    }

    // --- stars themselves (twinkle; speaking amplifies radius near center) ---
    for (let i = 0; i < linkN; i++) {
      const s = this.stars[i];
      const tw = 0.45 + 0.55 * Math.sin(t * s.twSpeed * (0.6 + c.speed) + s.tw);
      const x = s.x + s.ox, y = s.y + s.oy;
      const layerBoost = 0.55 + s.layer * 0.25;
      let radius = s.r * layerBoost * (0.85 + tw * 0.3);
      if (this.behavior.wave) {
        const dx = x - cx, dy = y - cy;
        const dist = Math.max(24, Math.sqrt(dx * dx + dy * dy));
        radius += Math.max(0, Math.sin(dist * 0.045 - t * (3.2 + this.ampSm * 4.5))) * (0.6 + this.ampSm * 2.2);
        radius *= breathe;
      } else {
        radius *= breathe;
      }
      // brightness: ice-white twinkle inside, blue rim
      const bright = Math.min(1, (0.5 + tw * 0.5) * c.glow + (s.layer === 2 ? 0.12 : 0));
      ctx.fillStyle = s.layer === 0 ? tint(BLUE, 0.42 * bright)
                     : s.layer === 1 ? tint(BLUE_SKY, 0.62 * bright)
                     : tint(BLUE_ICE, 0.9 * bright);
      ctx.beginPath(); ctx.arc(x, y, radius, 0, TAU); ctx.fill();

      // pointer-near stars pop an ice-white core (interaction telegraphy)
      if (hasPtr) {
        const pdx = ptr.x - x, pdy = ptr.y - y;
        const pd2 = pdx * pdx + pdy * pdy;
        if (pd2 < 55 * 55) {
          const core = (1 - pd2 / (55 * 55));
          ctx.fillStyle = tint(BLUE_BRIGHT, 0.35 * core);
          ctx.beginPath(); ctx.arc(x, y, radius + 1.4, 0, TAU); ctx.fill();
        }
      }
    }

    // --- analyzing/searching: wide blue scan band sweeping vertically ---
    if (this.behavior.scan) {
      this.scanX += dt * (60 + c.speed * 90);
      if (this.scanX > w + 160) this.scanX = -160;
      const bw = 150;
      const g = ctx.createLinearGradient(this.scanX - bw, 0, this.scanX + bw, 0);
      g.addColorStop(0, tint(BLUE, 0));
      g.addColorStop(0.5, tint(BLUE_SKY, 0.10 * c.glow));
      g.addColorStop(1, tint(BLUE, 0));
      ctx.fillStyle = g;
      ctx.fillRect(this.scanX - bw, 0, bw * 2, h);
    }

    // --- agents: bright hub nodes linked to the center ---
    if (this.agentNodes > 0) {
      const n = Math.min(this.agentNodes, 6);
      const R = Math.min(w, h) * 0.24;
      for (let i = 0; i < n; i++) {
        const th = this.swirlPhase * 0.6 + (i / n) * TAU;
        const nx = cx + Math.cos(th) * R;
        const ny = cy + Math.sin(th) * R * 0.75;
        const flick = 0.4 + 0.3 * Math.sin(t * 2.4 + i * 2.1);
        ctx.strokeStyle = tint(BLUE_SKY, Math.max(0.10, flick * 0.55));
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(nx, ny); ctx.stroke();
        ctx.fillStyle = tint(BLUE_ICE, 0.95);
        ctx.beginPath(); ctx.arc(nx, ny, 3.0, 0, TAU); ctx.fill();
      }
    }

    // --- tool markers: glyphs at the hub edge ---
    if (this.toolsActive.length) {
      ctx.font = "600 10px sans-serif";
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      const R = Math.min(w, h) * 0.32;
      for (let i = 0; i < this.toolsActive.length; i++) {
        const th = this.swirlPhase * 1.3 + (i / this.toolsActive.length) * TAU;
        const tx = cx + Math.cos(th) * R;
        const ty = cy + Math.sin(th) * R * 0.82;
        ctx.fillStyle = tint(BLUE_ICE, 0.95);
        const glyph = { executecode: ">", file: "□", net: "◎", phone: "▣", agent: "◆" }[this.toolsActive[i]] || "◆";
        ctx.fillText(glyph, tx, ty);
        ctx.strokeStyle = tint(BLUE_SKY, 0.5);
        ctx.beginPath(); ctx.arc(tx, ty, 9, 0, TAU); ctx.stroke();
      }
    }

    // --- success burst: blue sparks flying outward from the center ---
    if (this.burstT >= 0) {
      if (this.burstT === 0) {
        this.burst.length = 0;
        const count = Math.round(34 * this.quality + 12);
        for (let i = 0; i < count; i++) {
          const a = Math.random() * TAU;
          const sp = Math.min(w, h) * (1.0 + Math.random() * 1.6);
          this.burst.push({ x: cx, y: cy, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp, life: 1 });
        }
      }
      let alive = false;
      for (const b of this.burst) {
        if (b.life <= 0) continue;
        alive = true;
        b.x += b.vx * dt; b.y += b.vy * dt;
        b.vx *= Math.pow(0.25, dt); b.vy *= Math.pow(0.25, dt);
        b.life -= dt * 1.15;
        ctx.fillStyle = tint(BLUE_ICE, Math.max(0, b.life) * 0.9);
        ctx.beginPath(); ctx.arc(b.x, b.y, 1.6, 0, TAU); ctx.fill();
      }
      this.burstT += dt;
      if (!alive && this.burstT > 1.1) {
        this.burstT = -1;
        if (this.state === "success") this.setState("idle");
      }
    }
  }
}

export function initOrb() {
  const canvas = document.getElementById("orb-canvas");
  const orb = new Starfield(canvas);
  orb.attach();
  // long-press on the field toggles listening (gesture module binds this)
  canvas.parentElement.addEventListener("orb:voice-toggle", () => {
    document.getElementById("btn-voice")?.click();
  });
  return orb;
}
