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

/* ======================= Communication ======================= */
registerPanel("comms", {
  title: "Communication",
  mount(body) {
    const healthBox = h("div", { class: "comm-health" });
    const countsBox = h("div", { class: "comm-counts mono" });
    const inboxList = h("div", { class: "comm-list" });
    const draftsList = h("div", { class: "comm-list" });
    const controlsBox = h("div", { class: "comm-controls" });
    const qualityBox = h("div", { class: "comm-list" });
    const queueList = h("div", { class: "comm-list" });
    const flowsList = h("div", { class: "comm-list" });
    const auditList = h("div", { class: "comm-list" });

    body.append(
      h("h4", { class: "section-title" }, "Connectors"), healthBox,
      h("h4", { class: "section-title" }, "Unified Inbox"), countsBox, inboxList,
      h("h4", { class: "section-title" }, "Pending Drafts (approval)"), draftsList,
      h("h4", { class: "section-title" }, "Workflows"), flowsList,
      h("h4", { class: "section-title" }, "Audit Trail"), auditList,
      h("h4", { class: "section-title" }, "Autonomy & Controls"), controlsBox, qualityBox,
      h("h4", { class: "section-title" }, "Outbound Queue"), queueList,
    );

    let lastOverview = null;
    async function refresh() {
      // connector + account state
      try {
        const ov = await api("/api/comm/overview");
        lastOverview = ov;
        clear(healthBox);
        const entries = Object.entries(ov.connectors || {});
        healthBox.appendChild(entries.length
          ? h("div", {}, entries.map(([p, st]) =>
              h("div", { class: "fact" },
                h("span", { class: "mono" }, `${p}`),
                h("span", {}, ` ${st.state}${st.detail ? " — " + st.detail : ""}`))))
          : h("div", { class: "empty-hint" }, "No connectors configured (email/telegram env or Termux access)."));
        clear(countsBox);
        const by = Object.entries(ov.inbox?.by_platform || {}).map(([p, n]) => `${p}:${n}`).join("  ");
        countsBox.append(`messages ${ov.inbox?.total ?? 0}${by ? "  (" + by + ")" : ""}  ·  drafts ${ov.drafts_pending ?? 0}  ·  workflows ${ov.workflows ?? 0}${ov.serious_mode ? "  ·  SERIOUS MODE: ON" : ""}`);
      } catch (e) { countsBox.textContent = `overview unavailable: ${e.message || e}`; }

      try {
        const data = await api("/api/comm/inbox?limit=15");
        clear(inboxList);
        for (const m of data.messages || []) {
          inboxList.appendChild(h("div", { class: "comm-item" },
            h("span", { class: "mono" }, `[${m.platform}] `),
            h("b", {}, m.sender || "?"),
            h("span", {}, ` — ${(m.content || m.reply_context || "").slice(0, 120)}`),
            h("span", { class: "mono" }, ` ${m.urgency || ""}`)));
        }
        if (!(data.messages || []).length) inboxList.append(h("div", { class: "empty-hint" }, "(inbox empty)"));
      } catch (e) { inboxList.textContent = `inbox unavailable: ${e.message || e}`; }

      try {
        const d = await api("/api/comm/drafts");
        clear(draftsList);
        for (const dr of d.drafts || []) {
          const btn = h("button", { class: "mini-btn" }, "approve & send");
          btn.addEventListener("click", async () => {
            btn.disabled = true;
            try {
              const res = await api("/api/comm/send", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ draft_id: dr.draft_id, confirmed: true }),
              });
              btn.textContent = res.ok ? "sent ✓" : (res.status || "failed");
            } catch (e) { btn.textContent = "error"; }
            refresh();
          });
          const risk = (dr.risk_markers || []).length ? ` risk:${dr.risk_markers.join(",")}` : "";
          draftsList.appendChild(h("div", { class: "comm-item" },
            h("span", { class: "mono" }, `[${dr.platform}] `),
            h("b", {}, dr.recipient || "?"),
            h("span", {}, ` — ${(dr.body || "").slice(0, 90)}`),
            h("span", { class: "mono" }, risk),
            btn));
        }
        if (!(d.drafts || []).length) draftsList.append(h("div", { class: "empty-hint" }, "(no drafts waiting)"));
      } catch (e) { draftsList.textContent = `drafts unavailable: ${e.message || e}`; }

      try {
        const w = await api("/api/comm/workflows");
        clear(flowsList);
        for (const wf of w.workflows || []) {
          flowsList.appendChild(h("div", { class: "comm-item" },
            h("span", { class: "mono" }, `${wf.definition?.trigger?.type || "?"}`),
            h("span", {}, ` ${wf.name}`),
            h("span", { class: "mono" }, wf.enabled ? "" : " (disabled)")));
        }
        for (const f of ((lastOverview && lastOverview.bg_flows) || [])) {
          const st = f.status === "active" ? "ACTIVE" : f.status;
          const row = h("div", { class: "comm-item" },
            h("span", { class: "mono" }, `[bg:${st}] `),
            h("span", {}, `${f.platform}${f.account ? "/" + f.account : ""} risk=${f.risk_level} exp ${new Date(f.expires_at * 1000).toLocaleString()}`));
          if (f.status === "active") {
            const stopBtn = h("button", { class: "mini-btn" }, "stop");
            stopBtn.addEventListener("click", async () => {
              await api("/api/comm/control", { method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ op: "stop_bg_flow", target: f.flow_id }) });
              refresh();
            });
            row.appendChild(stopBtn);
          }
          flowsList.appendChild(row);
        }
        if (!(w.workflows || []).length) flowsList.append(h("div", { class: "empty-hint" }, "(no workflows)"));
        for (const r of (w.recent_runs || []).slice(0, 5)) {
          flowsList.appendChild(h("div", { class: "comm-item mono" },
            `run ${r.run_id} ${r.success ? "ok" : "FAIL"} ${r.trigger_summary || ""}`.slice(0, 120)));
        }
      } catch (e) { flowsList.textContent = `workflows unavailable: ${e.message || e}`; }

      try {
        const a = await api("/api/comm/audit?limit=10");
        clear(auditList);
        for (const e of a.entries || []) {
          auditList.appendChild(h("div", { class: "comm-item mono" },
            `${e.action} ${e.platform} → ${e.target || "-"} [${e.result || e.error || ""}]`.slice(0, 140)));
        }
        if (!(a.entries || []).length) auditList.append(h("div", { class: "empty-hint" }, "(no external actions yet)"));
      } catch (e) { auditList.textContent = `audit unavailable: ${e.message || e}`; }
    }

    async function refreshAutonomy() {
      try {
        const a = await api("/api/comm/autonomy");
        clear(controlsBox);
        const paused = a.overrides && (a.overrides.paused || a.overrides.estop);
        const mkBtn = (label, op, target) => {
          const b = h("button", { class: "mini-btn" }, label);
          b.addEventListener("click", async () => {
            await api("/api/comm/control", { method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ op, target: target || "" }) });
            refreshAutonomy(); refresh();
          });
          return b;
        };
        controlsBox.append(
          mkBtn(paused ? "Resume" : "Pause", paused ? "resume" : "pause"),
          mkBtn("EMERGENCY STOP", "estop"),
          mkBtn("Clear queue", "clear_queue"),
        );
        const row2 = h("div", { class: "comm-controls2" });
        for (const p of a.platforms || []) {
          row2.appendChild(mkBtn(
            p.shadow === "shadow" ? `graduate ${p.platform}` : `shadow ${p.platform}`,
            p.shadow === "shadow" ? "graduate" : "ungraduate", p.platform));
          row2.appendChild(mkBtn(`disable ${p.platform}`, "disable_platform", p.platform));
          row2.appendChild(mkBtn(`enable ${p.platform}`, "enable_platform", p.platform));
        }
        controlsBox.appendChild(row2);
        clear(qualityBox);
        for (const p of a.platforms || []) {
          const m = p.metrics || {};
          qualityBox.appendChild(h("div", { class: "comm-item mono" },
            `${p.platform}: ${p.shadow}${p.forced_max?.forced_max_level != null ? " max=" + p.forced_max.forced_max_level : ""} `
            + `accept=${m.reply_acceptance_rate ?? "—"} corr=${m.user_correction_rate ?? "—"} fails=${m.failed_send_rate ?? "—"}`));
        }
        if (!(a.platforms || []).length) qualityBox.append(h("div", { class: "empty-hint" }, "(no platform telemetry yet)"));
      } catch (e) { controlsBox.textContent = `autonomy unavailable: ${e.message || e}`; }
      try {
        const q = await api("/api/comm/outbox");
        clear(queueList);
        for (const r of q.queue || []) {
          queueList.appendChild(h("div", { class: "comm-item mono" },
            `[${r.status}] ${r.platform} → ${r.recipient} (try ${r.attempts})`.slice(0, 130)));
        }
        if (!(q.queue || []).length) queueList.append(h("div", { class: "empty-hint" }, "(queue empty)"));
      } catch (e) { queueList.textContent = `queue unavailable: ${e.message || e}`; }
    }
    refresh();
    refreshAutonomy();
    const timer = setInterval(refresh, 30000);
    const timer2 = setInterval(refreshAutonomy, 30000);
    return () => { clearInterval(timer); clearInterval(timer2); };
  },
});
