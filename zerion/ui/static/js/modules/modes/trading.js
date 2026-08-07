// modules/modes/trading.js — trading workspace.
//
// The current Core has no market-data tools installed, so this view is
// honest by construction: it renders the chart canvas, axes and signal
// rails, plots any numeric series the Core sends via workspace payload
// events, and clearly states when no feed exists instead of inventing
// numbers. The finance skill (skills/finance.py) can feed it later
// without any layout change.

import { h, clear } from "../../core/dom.js";
import { on } from "../../core/bus.js";
import { core } from "../../core/net.js";

export function createMode() {
  const chart = h("canvas", { "aria-label": "Market chart" });
  const signalsList = h("div", { class: "signal-list" });
  const posture = h("div", { class: "kv-list" });

  const root = h("section", { "aria-label": "Trading workspace" },
    h("div", { class: "ws-banner" },
      h("span", { class: "ws-mode-dot" }),
      h("span", { class: "ws-mode-name" }, "Trading"),
      h("span", { class: "ws-mode-sub" }, "signals appear when the Core receives market data"),
    ),
    h("div", { class: "trading-grid" },
      h("div", { class: "ws-card glass" },
        h("div", { class: "ws-card-title" }, "Market"),
        h("div", { class: "chart-wrap" }, chart,
          h("div", { class: "ws-hint", id: "trading-empty" },
            h("span", { class: "hint-glyph" }, "📈"),
            "No market feed is configured on this Core — ask Zerion to fetch prices with its web tools and the chart comes alive."),
        ),
      ),
      h("div", { class: "ws-sidecol" },
        h("div", { class: "ws-card glass" },
          h("div", { class: "ws-card-title" }, "Posture"),
          posture,
        ),
        h("div", { class: "ws-card glass" },
          h("div", { class: "ws-card-title" }, "Signals"),
          signalsList,
          h("div", { class: "action-row", style: "margin-top:10px" },
            h("button", {
              class: "mini-btn", type: "button",
              onclick: () => core.message("Fetch the latest BTC and ETH prices from the web and summarize the trend."),
            }, "Fetch crypto snapshot"),
          ),
        ),
      ),
    ),
  );

  let series = [];

  function kv(k, v) {
    let row = [...posture.children].find(r => r.firstChild.textContent === k);
    if (!row) { row = h("div", { class: "kv" }, h("kbd", {}, k), h("span", {}, "")); posture.appendChild(row); }
    row.lastChild.textContent = v;
  }

  function draw() {
    const wrap = chart.parentElement;
    const w = wrap.clientWidth, hh = wrap.clientHeight;
    if (!w || !hh) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    chart.width = w * dpr; chart.height = hh * dpr;
    const ctx = chart.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, hh);

    const pad = { l: 46, r: 12, t: 10, b: 18 };
    const accent = getComputedStyle(chart).getPropertyValue("--accent").trim() || "#66e3ff";

    // frame
    ctx.strokeStyle = "rgba(148,178,255,0.14)";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 3; i++) {
      const y = pad.t + (i / 3) * (hh - pad.t - pad.b);
      ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
    }

    if (series.length >= 2) {
      const min = Math.min(...series), max = Math.max(...series);
      const span = Math.max(max - min, 1e-9);
      ctx.strokeStyle = accent; ctx.lineWidth = 1.8;
      ctx.beginPath();
      series.forEach((v, i) => {
        const x = pad.l + (i / (series.length - 1)) * (w - pad.l - pad.r);
        const y = pad.t + (1 - (v - min) / span) * (hh - pad.t - pad.b);
        i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      });
      ctx.stroke();
      document.getElementById("trading-empty")?.classList.add("hidden");
      kv("last", String(series[series.length - 1]));
      kv("points", String(series.length));
    }
  }

  on("device", draw);

  // If any future Core event carries {workspace:"trading", data:{series}}
  // the chart upgrades itself — no UI work needed then.
  on("core:event", (msg) => {
    if (msg.type === "workspace" && msg.data?.mode === "trading" && Array.isArray(msg.data.series)) {
      series = msg.data.series.filter((v) => typeof v === "number").slice(-400);
      draw();
    }
    if (msg.type === "workspace" && msg.data?.mode === "trading" && msg.data.signal) {
      const s = msg.data.signal;
      signalsList.prepend(h("div", { class: "signal-chip" },
        h("span", {}, s.label || "signal"),
        h("span", { class: s.direction === "down" ? "dir-down" : "dir-up" },
          s.direction === "down" ? "▼" : "▲"),
      ));
      while (signalsList.children.length > 14) signalsList.lastElementChild.remove();
    }
  });

  kv("feed", "not configured");
  kv("positions", "—");

  return { root, activate() { setTimeout(draw, 60); }, event() { } };
}
