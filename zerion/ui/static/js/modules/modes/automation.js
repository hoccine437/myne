// modules/modes/automation.js — automation workspace: the planner's
// workflow as a live dependency graph (canvas) plus an execution state
// strip. Fed exclusively by 'tasks' events that mirror the Core's
// planner state — the graph is a view, never a model.

import { h, clear } from "../../core/dom.js";
import { on } from "../../core/bus.js";

const STATE_COLORS = {
  pending: "#63708c", running: "#66e3ff", completed: "#43e6a4",
  failed: "#ff5d73", skipped: "#ffb454", cancelled: "#ffb454",
};

export function createMode() {
  const canvas = h("canvas", { "aria-label": "Workflow graph" });
  const execStrip = h("div", { class: "exec-state" });
  const goalEl = h("span", { class: "ws-mode-sub" }, "no active workflow");

  const root = h("section", { "aria-label": "Automation workspace" },
    h("div", { class: "ws-banner" },
      h("span", { class: "ws-mode-dot" }),
      h("span", { class: "ws-mode-name" }, "Automation"),
      goalEl,
    ),
    h("div", { class: "automation-grid" },
      h("div", { class: "ws-card glass" },
        h("div", { class: "ws-card-title" }, "Workflow Graph"),
        h("div", { class: "graph-wrap" }, canvas),
      ),
      h("div", { class: "ws-card glass" },
        h("div", { class: "ws-card-title" }, "Execution State"),
        execStrip,
      ),
    ),
  );

  let workflow = null;

  function layout(tasks, w, hgt) {
    // columns by dependency depth (longest chain from a root)
    const depth = new Map();
    const byId = new Map(tasks.map(t => [t.id, t]));
    const calc = (t, seen = new Set()) => {
      if (depth.has(t.id)) return depth.get(t.id);
      if (seen.has(t.id)) return 0;
      seen.add(t.id);
      const d = (t.depends_on || []).length
        ? Math.max(...t.depends_on.map(id => byId.has(id) ? calc(byId.get(id), seen) + 1 : 0))
        : 0;
      depth.set(t.id, d);
      return d;
    };
    tasks.forEach(t => calc(t));
    const cols = new Map();
    tasks.forEach(t => {
      const d = depth.get(t.id);
      if (!cols.has(d)) cols.set(d, []);
      cols.get(d).push(t);
    });
    const maxCol = Math.max(0, ...cols.keys());
    const pos = new Map();
    for (const [col, items] of cols) {
      items.forEach((t, row) => {
        const x = 70 + (col / Math.max(maxCol, 1)) * Math.max(w - 160, 60);
        const y = 34 + (row + 0.5) * (hgt - 56) / items.length;
        pos.set(t.id, { x, y });
      });
    }
    return pos;
  }

  function draw() {
    if (!workflow) return;
    const wrap = canvas.parentElement;
    const w = wrap.clientWidth, hgt = wrap.clientHeight;
    if (!w || !hgt) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = w * dpr; canvas.height = hgt * dpr;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, hgt);

    const tasks = workflow.tasks || [];
    if (!tasks.length) return;
    const pos = layout(tasks, w, hgt);
    const byId = new Map(tasks.map(t => [t.id, t]));

    // edges
    for (const t of tasks) {
      for (const dep of t.depends_on || []) {
        if (!pos.has(dep)) continue;
        const a = pos.get(dep), b = pos.get(t.id);
        const done = byId.get(dep)?.state === "completed";
        ctx.strokeStyle = done ? "rgba(67,230,164,0.55)" : "rgba(148,178,255,0.25)";
        ctx.lineWidth = done ? 1.8 : 1.1;
        ctx.beginPath();
        ctx.moveTo(a.x + 34, a.y);
        ctx.bezierCurveTo(a.x + 64, a.y, b.x - 64, b.y, b.x - 36, b.y);
        ctx.stroke();
        // arrowhead
        ctx.fillStyle = ctx.strokeStyle;
        ctx.beginPath();
        ctx.moveTo(b.x - 36, b.y); ctx.lineTo(b.x - 44, b.y - 4); ctx.lineTo(b.x - 44, b.y + 4);
        ctx.closePath(); ctx.fill();
      }
    }

    // nodes
    for (const t of tasks) {
      const p = pos.get(t.id);
      const color = STATE_COLORS[t.state] || STATE_COLORS.pending;
      ctx.fillStyle = "rgba(7, 11, 20, 0.92)";
      ctx.strokeStyle = color;
      ctx.lineWidth = t.state === "running" ? 2 : 1.2;
      const bw = 68, bh = 30;
      ctx.beginPath();
      ctx.roundRect(p.x - bw / 2, p.y - bh / 2, bw, bh, 8);
      ctx.fill(); ctx.stroke();
      ctx.fillStyle = color;
      ctx.font = "600 9px " + getComputedStyle(canvas).getPropertyValue("--font-mono");
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText((t.tool_name || `#${t.id}`).slice(0, 11), p.x, p.y + 1);

      // label under node
      ctx.fillStyle = "rgba(169,184,212,0.85)";
      ctx.font = "10px " + getComputedStyle(canvas).getPropertyValue("--font-ui");
      const label = (t.description || "").slice(0, 34);
      ctx.fillText(label, p.x, Math.min(p.y + 24, hgt - 8));
    }
  }

  function renderStrip() {
    clear(execStrip);
    const tasks = workflow?.tasks || [];
    const counts = {};
    tasks.forEach(t => counts[t.state] = (counts[t.state] || 0) + 1);
    const mk = (k, v) => h("div", { class: "kv" },
      h("span", { style: "color:var(--text-2)" }, k), h("span", {}, String(v)));
    execStrip.append(
      mk("status", workflow?.status || "—"),
      mk("tasks", tasks.length),
      ...Object.entries(counts).map(([s, n]) => mk(s, n)),
    );
  }

  on("device", draw);

  return {
    root,
    activate() { setTimeout(draw, 80); },
    event(type, d) {
      if (type === "tasks") {
        workflow = d;
        goalEl.textContent = d.goal ? `goal: ${d.goal}` : "no active workflow";
        renderStrip();
        draw();
      }
      if (type === "stage" && (d.stage === "planner" || d.stage === "intent")) {
        draw();
      }
    },
  };
}
