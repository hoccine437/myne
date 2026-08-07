// modules/panels.js — the floating panels themselves:
// File Explorer, Logs, Memory Inspector, Developer Tools.
// Registered lazily with floating.js; each panel reads via /api/* which
// routes through the Core (list_directory / read_file tools, session
// snapshot, knowledge DB, event buffer).

import { h, clear, timeOf } from "../core/dom.js";
import { on } from "../core/bus.js";
import { api } from "../core/net.js";
import { registerPanel } from "./floating.js";

/* =================--------- File Explorer ----------================= */
registerPanel("explorer", {
  title: "File Explorer",
  mount(body) {
    const list = h("div", { class: "explorer-list", role: "tree" });
    const pathInput = h("input", {
      type: "text", value: ".", "aria-label": "Directory path", spellcheck: "false",
    });
    const viewer = h("div", { class: "explorer-viewer hidden" });

    body.append(
      h("div", { class: "explorer-path" },
        h("button", { class: "mini-btn", onclick: () => load("..") }, "up"),
        pathInput,
        h("button", { class: "mini-btn", onclick: () => load(pathInput.value) }, "go"),
      ),
      list, viewer,
    );

    async function load(path) {
      clear(list);
      try {
        const data = await api(`/api/fs/list?path=${encodeURIComponent(path)}`);
        pathInput.value = data.path;
        for (const e of data.entries) {
          list.appendChild(h("div", {
            class: "explorer-item", role: "treeitem", tabindex: "0",
            onclick: () => e.dir ? load(joinPath(data.path, e.name)) : view(joinPath(data.path, e.name)),
            onkeydown: (ev) => { if (ev.key === "Enter") ev.target.click(); },
          },
            h("span", { class: "fi" }, e.dir ? "▸" : "·"),
            h("span", {}, e.name),
          ));
        }
        if (!data.entries.length) list.append(h("div", { class: "empty-hint" }, "(empty directory)"));
      } catch (err) {
        list.append(h("div", { class: "empty-hint" }, `${err.message || "unavailable"}`));
      }
    }

    function joinPath(base, name) {
      if (base === "/" ) return "/" + name;
      return base.replace(/\/+$/, "") + "/" + name;
    }

    async function view(path) {
      try {
        const data = await api(`/api/fs/read?path=${encodeURIComponent(path)}`);
        clear(viewer);
        viewer.classList.remove("hidden");
        viewer.appendChild(h("pre", { class: "mono" }, data.content || ""));
      } catch (err) {
        clear(viewer);
        viewer.classList.remove("hidden");
        viewer.appendChild(h("div", { class: "empty-hint" }, String(err.message || err)));
      }
    }

    pathInput.addEventListener("keydown", (e) => { if (e.key === "Enter") load(pathInput.value); });
    load(".");
  },
});

/* ============================ Logs ============================ */
registerPanel("logs", {
  title: "Logs",
  mount(body) {
    const list = h("div", { class: "log-list" });
    body.appendChild(list);

    api("/api/logs?limit=220").then(({ events }) => {
      events.forEach(addEvent);
      list.scrollTop = 0;
    }).catch(() => {});

    function addEvent(e) {
      const d = e.data || {};
      let text = "", level = d.level || "INFO";
      if (e.type === "log") text = d.text || "";
      else if (e.type === "stage") text = `stage ${d.stage}: ${d.status}${d.duration ? ` (${d.duration}s)` : ""}`;
      else if (e.type === "tool") text = `tool ${d.tool}: ${d.phase}${d.error ? " — " + d.error : ""}`;
      else if (e.type === "decision") text = `[${d.source}] ${d.text}`;
      else if (e.type === "notification") { text = d.text; level = (d.level || "info").toUpperCase(); }
      else if (e.type === "turn") text = `turn ${d.phase}${d.seconds ? ` in ${d.seconds}s` : ""}`;
      else if (e.type === "error") { text = d.text || JSON.stringify(d); level = "ERROR"; }
      else return;
      list.appendChild(h("div", { class: "log-line", dataset: { level } },
        h("time", {}, timeOf(e.ts)),
        h("span", { class: "log-type" }, e.type),
        h("span", { class: "log-msg" }, text),
      ));
      while (list.children.length > 500) list.firstElementChild.remove();
      list.parentElement.scrollTop = list.parentElement.scrollHeight;
    }

    const offLog = on("core:event", addEvent);
    return () => offLog();
  },
});

/* ====================== Memory Inspector ====================== */
registerPanel("memory", {
  title: "Memory Inspector",
  mount(body) {
    const stats = h("div", { class: "mem-stats" });
    const json = h("pre", { class: "mem-json mono" });
    const notes = h("div", { class: "knowledge-list" });
    body.append(
      stats,
      h("h4", { class: "section-title" }, "Long-term memory (memory.json)"),
      json,
      h("h4", { class: "section-title", style: "margin-top:12px" }, "Knowledge records (recent)"),
      notes,
    );

    async function refresh() {
      try {
        const mem = await api("/api/memory");
        clear(stats);
        for (const [k, v] of Object.entries(mem.stats || {})) {
          stats.appendChild(h("span", { class: "section-badge" }, `${k}: ${v}`));
        }
        stats.appendChild(h("span", { class: "section-badge" }, mem.path));
        json.textContent = JSON.stringify(mem.memory, null, 2);
      } catch { json.textContent = "(memory unavailable)"; }
      try {
        const { records } = await api("/api/knowledge?limit=14");
        clear(notes);
        for (const r of records) {
          notes.appendChild(h("div", { class: "knowledge-item" },
            (r.content || "").slice(0, 220),
            h("div", { class: "ki-meta" }, `#${r.id} · ${r.layer}/${r.category} · conf ${Number(r.confidence ?? 0).toFixed(2)}`),
          ));
        }
        if (!records.length) notes.appendChild(h("div", { class: "empty-hint" }, "No knowledge records yet."));
      } catch { /* keep panel alive */ }
    }
    refresh();
    const off = on("core:memory_update", refresh);
    const timer = setInterval(refresh, 30000);
    return () => { off(); clearInterval(timer); };
  },
});

/* ======================= Developer Tools ====================== */
registerPanel("devtools", {
  title: "Developer Mode — Pipeline",
  mount(body) {
    const metrics = h("div", { class: "dev-metrics" });
    const timeline = h("div", { class: "dev-timeline" });
    body.append(
      h("h4", { class: "section-title" }, "Runtime"),
      metrics,
      h("h4", { class: "section-title" }, "Execution timeline (current session)"),
      timeline,
    );

    const values = {
      turns: 0, tools: 0, lastTurn: "—", avgTurn: "—", fps: "—",
    };
    let turnTotalMs = 0;

    function renderMetrics() {
      clear(metrics);
      for (const [k, v] of Object.entries(values)) {
        metrics.appendChild(h("div", { class: "dev-metric" },
          h("div", { class: "dm-v" }, String(v)),
          h("div", { class: "dm-k" }, k),
        ));
      }
    }
    renderMetrics();

    const offStage = on("core:stage", (d) => {
      timeline.appendChild(h("div", { class: "dev-stage", dataset: { status: d.status } },
        h("span", { class: "ds-time" }, timeOf()),
        h("span", { class: "ds-dot" }),
        h("span", {}, h("div", { class: "ds-name" }, `${d.stage} — ${d.status}`),
          h("div", { class: "ds-detail" }, summarize(d.detail))),
        h("span", { class: "ds-dur" }, d.duration != null ? `${(d.duration * 1000).toFixed(0)}ms` : ""),
      ));
      while (timeline.children.length > 60) timeline.firstElementChild.remove();
    });
    const offTurn = on("core:turn", (d) => {
      if (d.phase === "end") {
        values.turns++;
        turnTotalMs += d.seconds * 1000;
        values.lastTurn = `${d.seconds}s`;
        values.avgTurn = `${Math.round(turnTotalMs / values.turns)}ms`;
        renderMetrics();
      }
    });
    const offTool = on("core:tool", (d) => { if (d.phase === "end") { values.tools++; renderMetrics(); } });
    const offFps = on("fps", (fps) => { values.fps = fps; renderMetrics(); });

    function summarize(detail) {
      if (!detail) return "";
      try { return JSON.stringify(detail).slice(0, 140); } catch { return ""; }
    }

    return () => { offStage(); offTurn(); offTool(); offFps(); };
  },
});
