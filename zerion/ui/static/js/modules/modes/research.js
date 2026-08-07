// modules/modes/research.js — research workspace: knowledge the Core
// retrieved/learned (from its own knowledge DB), memory notes the Core
// wrote this session, and a live "sources of this turn" strip.

import { h, clear } from "../../core/dom.js";
import { api } from "../../core/net.js";

export function createMode() {
  const sourcesList = h("div", { class: "research-list" });
  const memoryList = h("div", { class: "research-list" });

  const root = h("section", { "aria-label": "Research workspace" },
    h("div", { class: "ws-banner" },
      h("span", { class: "ws-mode-dot" }),
      h("span", { class: "ws-mode-name" }, "Research"),
      h("span", { class: "ws-mode-sub" }, "knowledge retrieved & recorded by the Core"),
    ),
    h("div", { class: "research-grid" },
      h("div", { class: "ws-card glass" },
        h("div", { class: "ws-card-title" }, "Knowledge Base — recent"),
        memoryList,
      ),
      h("div", { class: "ws-card glass" },
        h("div", { class: "ws-card-title" }, "Working Notes — this turn"),
        sourcesList,
      ),
    ),
  );

  async function loadKnowledge() {
    try {
      const { records } = await api("/api/knowledge?limit=24");
      clear(memoryList);
      if (!records.length) {
        memoryList.appendChild(h("div", { class: "empty-hint" },
          "The Core hasn't stored knowledge yet — ask it to remember or research something."));
        return;
      }
      for (const r of records) {
        memoryList.appendChild(h("div", { class: "research-item" },
          h("span", { class: "ri-title" }, (r.content || "").slice(0, 160)),
          h("span", { class: "ri-meta" },
            `${r.layer}/${r.category} · importance ${Number(r.importance ?? 0).toFixed(2)} · confidence ${Number(r.confidence ?? 0).toFixed(2)}`),
        ));
      }
    } catch {
      clear(memoryList);
      memoryList.appendChild(h("div", { class: "empty-hint" }, "Knowledge base unavailable."));
    }
  }

  const notes = [];
  function pushNote(text) {
    if (!text) return;
    notes.unshift(text);
    if (notes.length > 12) notes.pop();
    clear(sourcesList);
    for (const n of notes) {
      sourcesList.appendChild(h("div", { class: "research-item" }, n));
    }
  }

  return {
    root,
    activate() { loadKnowledge(); },
    event(type, d) {
      if (type === "stage" && d.stage === "context" && d.status === "done") {
        const det = d.detail || {};
        sourcesList && pushNote(
          `reasoning: ${det.reasoning_mode ?? "—"} · strategy: ${det.reasoning_strategy ?? "—"} · confidence: ${det.reasoning_confidence ?? "—"}${det.retrieved ? " · knowledge retrieved" : ""}`
        );
      }
      if (type === "memory_update") {
        pushNote(`memory updated: ${(d.keys || []).join(", ") || "entry"}`);
        loadKnowledge();
      }
    },
  };
}
