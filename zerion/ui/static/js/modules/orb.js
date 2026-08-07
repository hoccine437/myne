// modules/orb.js — the Zerion Core visualization.
//
// A state-driven particle renderer: the orb IS the status display.
// Every Core state (idle → thinking → listening → speaking → searching →
// coding → learning → updating → error → success) has its own motion
// language, palette and glyph behavior; transitions crossfade so the
// interface reads as one continuous organism, not a spinner.
//
// Performance contract: one rAF loop, zero per-frame allocations in the
// hot path, particle budget scaled by device profile + fx quality,
// auto-pauses when the tab or the stage is hidden.

import { on } from "../core/bus.js";
import { store } from "../core/store.js";

const TAU = Math.PI * 2;

// Per-state look & motion. hue/sat/light drive all strokes/glows;
// behavior flags toggle subsystems (ripples, speak-wave, sweep, runes).
const STATES = {
  idle:      { h: 192, s: 100, l: 68, speed: 0.22, converge: 0.0, breath: 0.055, jitter: 0,
               ripples: false, wave: false, sweep: false, runes: false, spiral: 0, label: "IDLE" },
  thinking:  { h: 192, s: 100, l: 62, speed: 1.7, converge: 0.72, breath: 0.10, jitter: 0.12,
               ripples: false, wave: false, sweep: false, runes: false, spiral: 0, label: "THINKING" },
  listening: { h: 152, s: 90, l: 60, speed: 0.55, converge: 0.25, breath: 0.07, jitter: 0,
               ripples: true, wave: false, sweep: false, runes: false, spiral: 0, label: "LISTENING" },
  speaking:  { h: 258, s: 85, l: 70, speed: 0.8, converge: 0.45, breath: 0.085, jitter: 0.05,
               ripples: false, wave: true, sweep: false, runes: false, spiral: 0, label: "SPEAKING" },
  searching: { h: 214, s: 100, l: 66, speed: 1.1, converge: 0.5, breath: 0.07, jitter: 0.06,
               ripples: false, wave: false, sweep: true, runes: false, spiral: 0, label: "SEARCHING" },
  coding:    { h: 36, s: 100, l: 62, speed: 1.05, converge: 0.55, breath: 0.07, jitter: 0.10,
               ripples: false, wave: false, sweep: false, runes: true, spiral: 0, label: "CODING" },
  learning:  { h: 316, s: 90, l: 68, speed: 1.3, converge: 0.6, breath: 0.09, jitter: 0.06,
               ripples: false, wave: false, sweep: false, runes: false, spiral: 1, label: "LEARNING" },
  updating:  { h: 172, s: 90, l: 60, speed: 1.5, converge: 0.4, breath: 0.06, jitter: 0.15,
               ripples: false, wave: false, sweep: true, runes: true, spiral: 0, label: "UPDATING" },
  error:     { h: 350, s: 100, l: 64, speed: 1.9, converge: 0.68, breath: 0.14, jitter: 1.0,
               ripples: false, wave: false, sweep: false, runes: false, spiral: 0, label: "FAULT" },
  success:   { h: 152, s: 95, l: 62, speed: 1.4, converge: 0.3, breath: 0.08, jitter: 0,
               ripples: false, wave: false, sweep: false, runes: false, spiral: 0, label: "DONE" },
};

class Orb {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d", { alpha: true });
    this.dpr = 1;
    this.w = 0; this.h = 0; this.cx = 0; this.cy = 0; this.radius = 60;

    // current (lerped) visual params
    this.cur = { h: 192, s: 100, l: 68, speed: 0.22, converge: 0, breath: 0.055, jitter: 0, spiral: 0 };
    this.target = { ...this.cur };
    this.state = "idle";

    this.rot = 0;               // master rotation, advanced by speed
    this.breathPhase = 0;
    this.sweepAngle = 0;
    this.amp = 0;               // voice amplitude 0..1 (set externally)
    this.ampSm = 0;
    this.burstT = -1;           // success burst progress
    this.errorUntil = 0;        // error auto-return timer
    this.visible = true;
    this.quality = 1;           // 0..1 particle budget multiplier

    this.particles = [];
    this.stars = [];
    this.ripples = [];
    this.burst = [];

    this._resize = this.resize.bind(this);
    this._frame = this.frame.bind(this);

    on("core:core_state", (d) => this.setState(d.state, d.detail));
    on("device", () => this.resize());
    on("settings", () => this.applySettings());
  }

  applySettings() {
    const q = store.settings.fxQuality;
    const p = store.device || { device: "desktop", dpr: 1 };
    let budget = 1;
    if (q === "low") budget = 0.45;
    else if (q === "auto") {
      budget = p.device === "phone" ? 0.55 : p.device === "tablet" ? 0.8 : 1;
    }
    this.quality = budget;
    this.seedParticles();
  }

  attach() {
    this.applySettings();
    this.resize();
    if ("ResizeObserver" in window) {
      new ResizeObserver(this._resize).observe(this.canvas.parentElement);
    }
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) this.last = 0; // avoid dt spike on return
    });
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(([e]) => { this.visible = e.isIntersecting; }, { threshold: 0.02 })
        .observe(this.canvas);
    }
    this.running = true;
    requestAnimationFrame((t) => { this.last = t; requestAnimationFrame(this._frame); });
  }

  resize() {
    const rect = this.canvas.parentElement.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    const dpr = Math.min((store.device?.dpr || 1), 2); // cap: crisp but cheap
    this.dpr = dpr;
    this.w = Math.round(rect.width); this.h = Math.round(rect.height);
    this.canvas.width = Math.round(rect.width * dpr);
    this.canvas.height = Math.round(rect.height * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.cx = this.w / 2; this.cy = this.h / 2;
    this.radius = Math.max(34, Math.min(this.w, this.h) * 0.30);
    this.seedStars();
    this.seedParticles();
  }

  seedStars() {
    const count = Math.round((this.w * this.h) / 16000 * this.quality);
    this.stars = new Array(Math.max(0, count));
    for (let i = 0; i < this.stars.length; i++) {
      this.stars[i] = {
        x: Math.random() * this.w, y: Math.random() * this.h,
        r: Math.random() * 1.1 + 0.3, tw: Math.random() * TAU,
      };
    }
  }

  seedParticles() {
    const base = 110;
    const n = Math.max(28, Math.round(base * this.quality));
    if (this.particles.length === n) return;
    this.particles = new Array(n);
    for (let i = 0; i < n; i++) {
      const band = i % 3; // three orbital bands for depth
      this.particles[i] = {
        a: Math.random() * TAU,
        orbit: (0.62 + band * 0.24) + Math.random() * 0.10,       // ×radius
        speed: (0.4 + Math.random() * 0.9) * (band % 2 ? 1 : -1), // direction variety
        size: Math.random() * 1.8 + 0.7,
        tilt: (Math.random() - 0.5) * 0.9,
        tw: Math.random() * TAU,
      };
    }
  }

  setState(state, detail = "") {
    const def = STATES[state] || STATES.idle;
    this.state = state in STATES ? state : "idle";
    const t = STATES[this.state];
    this.target = { h: t.h, s: t.s, l: t.l, speed: t.speed, converge: t.converge,
                    breath: t.breath, jitter: t.jitter, spiral: t.spiral };
    this.behavior = t;
    const caption = document.getElementById("orb-caption");
    if (caption) caption.textContent = detail ? `${t.label} — ${detail}` : t.label;
    if (this.state === "success") this.burstT = 0;
    if (this.state === "error") this.errorUntil = performance.now() + 2600;
  }

  setAmplitude(v) { this.amp = Math.max(0, Math.min(1, v)); }

  frame(now) {
    if (!this.running) return;
    requestAnimationFrame(this._frame);
    if (document.hidden || !this.visible) return;
    const dt = Math.min(0.05, this.last ? (now - this.last) / 1000 : 0.016);
    this.last = now;

    // error is transient — ease back to idle unless a new state arrived
    if (this.state === "error" && now > this.errorUntil) {
      this.setState(store.core.state === "error" ? "error" : "idle");
    }

    // ease current params toward target (exponential, framerate-safe)
    const k = 1 - Math.pow(0.0025, dt);
    for (const key of ["h", "s", "l", "speed", "converge", "breath", "jitter", "spiral"]) {
      this.cur[key] += (this.target[key] - this.cur[key]) * k;
    }
    this.ampSm += (this.amp - this.ampSm) * (1 - Math.pow(0.001, dt));

    this.rot += this.cur.speed * dt;
    this.breathPhase += dt * 1.8;
    this.sweepAngle += dt * 2.2;

    this.render(dt, now / 1000);
  }

  render(dt, t) {
    const { ctx, cx, cy, w, h } = this;
    const c = this.cur;
    const R = this.radius;
    ctx.clearRect(0, 0, w, h);

    const breath = 1 + Math.sin(this.breathPhase) * c.breath * (1 + this.ampSm);
    const jx = (Math.random() - 0.5) * c.jitter * 7;
    const jy = (Math.random() - 0.5) * c.jitter * 7;
    const px = cx + jx, py = cy + jy;

    const col = (l, a) => `hsla(${c.h}, ${c.s}%, ${l}%, ${a})`;

    // --- starfield ---
    for (const s of this.stars) {
      const tw = 0.25 + 0.2 * Math.sin(t * 0.8 + s.tw);
      ctx.fillStyle = col(78, tw * 0.5);
      ctx.fillRect(s.x, s.y, s.r, s.r);
    }

    // --- nebular core glow ---
    const glowR = R * 2.05 * breath;
    let g = ctx.createRadialGradient(px, py, R * 0.1, px, py, glowR);
    g.addColorStop(0, col(c.l, 0.30));
    g.addColorStop(0.45, col(c.l - 8, 0.10));
    g.addColorStop(1, col(c.l, 0));
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(px, py, glowR, 0, TAU); ctx.fill();

    // --- outer dashed rings ---
    this.ring(px, py, R * 1.42, this.rot * 0.5, 34, 0.32, col(c.l, 0.5));
    this.ring(px, py, R * 1.62, -this.rot * 0.33, 46, 0.22, col(c.l, 0.30));
    this.ring(px, py, R * 1.20, this.rot * 0.8, 26, 0.5, col(c.l + 8, 0.75), 1.6);

    // --- spindle: converge ellipses when busy ---
    if (c.converge > 0.05) {
      ctx.save();
      ctx.translate(px, py);
      for (let i = 0; i < 3; i++) {
        ctx.save();
        ctx.rotate(this.rot * (1 + i * 0.35) + (i * TAU) / 3);
        ctx.strokeStyle = col(c.l + 6, 0.34 * c.converge);
        ctx.lineWidth = 1.1;
        ctx.beginPath();
        ctx.ellipse(0, 0, R * (1.05 - i * 0.13), R * 0.30 * (1 - i * 0.18), 0, 0, TAU);
        ctx.stroke();
        ctx.restore();
      }
      ctx.restore();
    }

    // --- core body ---
    const coreR = R * 0.52 * breath * (1 - 0.08 * c.converge) + this.ampSm * R * 0.05;
    g = ctx.createRadialGradient(px - coreR * 0.3, py - coreR * 0.35, coreR * 0.12, px, py, coreR * 1.25);
    g.addColorStop(0, `hsla(${c.h}, ${c.s}%, ${Math.min(96, c.l + 26)}%, 0.98)`);
    g.addColorStop(0.55, col(c.l, 0.9));
    g.addColorStop(1, col(c.l - 26, 0.12));
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(px, py, coreR, 0, TAU); ctx.fill();
    // crisp rim
    ctx.strokeStyle = col(Math.min(90, c.l + 18), 0.9);
    ctx.lineWidth = 1.2;
    ctx.beginPath(); ctx.arc(px, py, coreR, 0, TAU); ctx.stroke();

    // --- particles ---
    for (let i = 0; i < this.particles.length; i++) {
      const p = this.particles[i];
      const dirRadius = R * p.orbit * (1 - c.converge * 0.28) * breath;
      p.a += p.speed * dt * (0.6 + c.speed);
      const spiral = c.spiral ? (Math.sin(t * 0.9 + p.tw) * 0.5 + 0.5) * R * 0.42 : 0;
      const rr = dirRadius - spiral;
      const wob = Math.sin(t * 2.1 + p.tw) * 4 * c.jitter;
      const x = px + Math.cos(p.a) * (rr + wob);
      const y = py + Math.sin(p.a) * (rr + wob) * (0.92 + 0.08 * Math.sin(p.tilt));
      const tw = 0.5 + 0.5 * Math.sin(t * 3 + p.tw);
      ctx.fillStyle = col(c.l + 10, 0.28 + tw * 0.55);

      if (this.behavior?.runes && i % 4 === 0) {
        // coding/updating: square "bracket" glyphs
        const s = p.size + 1.6;
        ctx.fillRect(x - s / 2, y - s / 2, s, s);
      } else {
        ctx.beginPath(); ctx.arc(x, y, p.size, 0, TAU); ctx.fill();
      }
    }

    // --- listening ripples ---
    if (this.behavior?.ripples) {
      this.rippleT = (this.rippleT || 0) - dt;
      if (this.rippleT <= 0) {
        this.ripples.push({ r: R * 0.6, a: 0.5 });
        this.rippleT = 1.15;
      }
    }
    for (let i = this.ripples.length - 1; i >= 0; i--) {
      const rp = this.ripples[i];
      rp.r += dt * R * 0.85;
      rp.a *= Math.pow(0.35, dt);
      if (rp.r > R * 2.2 || rp.a < 0.01) { this.ripples.splice(i, 1); continue; }
      ctx.strokeStyle = col(c.l, rp.a);
      ctx.lineWidth = 1.4;
      ctx.beginPath(); ctx.arc(px, py, rp.r, 0, TAU); ctx.stroke();
    }

    // --- speaking waveform ring ---
    if (this.behavior?.wave) {
      ctx.save();
      ctx.translate(px, py);
      ctx.strokeStyle = col(c.l + 14, 0.85);
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      const bars = 56;
      for (let i = 0; i <= bars; i++) {
        const th = (i / bars) * TAU;
        const w = Math.sin(th * 5 + t * 7) * Math.sin(th * 3 - t * 4.3);
        const r = R * 1.02 + w * (4 + this.ampSm * 22) + Math.sin(th * 9 + t * 11) * this.ampSm * 6;
        const x = Math.cos(th) * r, y = Math.sin(th) * r;
        i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      }
      ctx.closePath(); ctx.stroke();
      ctx.restore();
    }

    // --- searching sweep ---
    if (this.behavior?.sweep) {
      const grd = ctx.createConicGradient
        ? ctx.createConicGradient(this.sweepAngle, px, py)
        : null;
      if (grd) {
        grd.addColorStop(0, col(c.l + 20, 0.5));
        grd.addColorStop(0.12, col(c.l, 0.12));
        grd.addColorStop(0.4, col(c.l, 0));
        grd.addColorStop(1, col(c.l, 0));
        ctx.fillStyle = grd;
        ctx.beginPath(); ctx.arc(px, py, R * 1.5, 0, TAU); ctx.fill();
      } else {
        // fallback beam
        ctx.save();
        ctx.translate(px, py); ctx.rotate(this.sweepAngle);
        ctx.strokeStyle = col(c.l + 20, 0.6); ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(R * 1.4, 0); ctx.stroke();
        ctx.restore();
      }
    }

    // --- success burst ---
    if (this.burstT >= 0) {
      if (this.burstT === 0) {
        this.burst.length = 0;
        for (let i = 0; i < 26 * this.quality + 10; i++) {
          const a = Math.random() * TAU, sp = R * (1.4 + Math.random() * 1.8);
          this.burst.push({ x: px, y: py, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp, life: 1 });
        }
      }
      let alive = false;
      for (const b of this.burst) {
        if (b.life <= 0) continue;
        alive = true;
        b.x += b.vx * dt; b.y += b.vy * dt;
        b.vx *= Math.pow(0.2, dt); b.vy *= Math.pow(0.2, dt);
        b.life -= dt * 1.1;
        ctx.fillStyle = col(c.l + 10, Math.max(0, b.life) * 0.8);
        ctx.beginPath(); ctx.arc(b.x, b.y, 1.8, 0, TAU); ctx.fill();
      }
      // expanding halo
      const haloR = R * (0.6 + this.burstT * 1.1);
      ctx.strokeStyle = col(c.l, Math.max(0, 0.5 - this.burstT * 0.28));
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(px, py, haloR, 0, TAU); ctx.stroke();
      this.burstT += dt;
      if (!alive && this.burstT > 1.1) { this.burstT = -1; if (this.state === "success") this.setState("idle"); }
    }
  }

  ring(x, y, r, rot, segs, duty, style, lw = 1) {
    const { ctx } = this;
    ctx.strokeStyle = style; ctx.lineWidth = lw;
    const seg = TAU / segs;
    ctx.beginPath();
    for (let i = 0; i < segs; i++) {
      const a0 = rot + i * seg, a1 = a0 + seg * duty;
      ctx.moveTo(x + Math.cos(a0) * r, y + Math.sin(a0) * r);
      ctx.arc(x, y, r, a0, a1);
    }
    ctx.stroke();
  }
}

export function initOrb() {
  const canvas = document.getElementById("orb-canvas");
  const orb = new Orb(canvas);
  orb.attach();
  // long-press on the orb toggles listening (gesture module binds this)
  canvas.parentElement.addEventListener("orb:voice-toggle", () => {
    document.getElementById("btn-voice")?.click();
  });
  return orb;
}
