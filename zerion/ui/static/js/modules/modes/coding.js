// modules/modes/coding.js — coding workspace: a code viewer fed by the
// Core's file/exec tool activity, execution log, and project context.
// Editing and execution never happen client-side — quick actions phrase
// a request and send it to the Core, which owns all execution.

import { h, timeOf } from "../../core/dom.js";
import { core } from "../../core/net.js";

/* featherweight syntax highlighter: strings, comments, numbers,
   keywords, calls — enough for readability, zero dependencies. */
const KEYWORDS = new Set(("def class return if elif else for while import from as with try except finally raise " +
  "lambda None True False pass break continue global nonlocal yield async await in is not and or " +
  "function const let var new export extends super this switch case default of typeof instanceof void " +
  "package public private static final int float str bool void null true false fn struct impl pub use mod").split(" "));

function highlight(text) {
  const esc = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return esc.replace(
    /("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')|(#[^\n]*|\/\/[^\n]*)|(\b\d[\d_]*\.?[\d_]*(?:e[+-]?\d+)?\b)|(\b[A-Za-z_]\w*(?=\())|(\b[A-Za-z_]\w*\b)/g,
    (m, str, com, num, fn, word) => {
      if (str) return `<span class="tok-s">${str}</span>`;
      if (com) return `<span class="tok-c">${com}</span>`;
      if (num) return `<span class="tok-n">${num}</span>`;
      if (fn) return `<span class="tok-f">${fn}</span>`;
      if (word && KEYWORDS.has(word)) return `<span class="tok-k">${word}</span>`;
      return m;
    });
}

export function createMode() {
  const codeView = h("pre", { class: "code-view" });
  const execList = h("div", { class: "kv-list" });
  const ctxList = h("div", { class: "kv-list" });

  const action = (label, text) => h("button", {
    class: "mini-btn", type: "button",
    onclick: () => { core.message(text); },
  }, label);

  const actions = h("div", { class: "action-row" },
    action("Explain a file", "Read and explain the file "),
    action("Write a script", "Write a Python script that "),
    action("Run & verify", "Run the script with run_python and fix any errors"),
    action("Refactor", "Suggest a refactor for "),
  );

  const root = h("section", { "aria-label": "Coding workspace" },
    h("div", { class: "ws-banner" },
      h("span", { class: "ws-mode-dot" }),
      h("span", { class: "ws-mode-name" }, "Coding"),
      h("span", { class: "ws-mode-sub" }, "file context, executions and edits flow through the Core"),
    ),
    h("div", { class: "ws-grid" },
      h("div", { class: "ws-card glass" },
        h("div", { class: "ws-card-title" }, "Editor Context"),
        codeView,
        actions,
      ),
      h("div", { class: "ws-sidecol" },
        h("div", { class: "ws-card glass" },
          h("div", { class: "ws-card-title" }, "Project"),
          ctxList,
        ),
        h("div", { class: "ws-card glass" },
          h("div", { class: "ws-card-title" }, "Execution Log"),
          execList,
        ),
      ),
    ),
  );

  let fileShown = "";
  function showCode(title, text) {
    codeView.innerHTML = highlight(String(text).slice(0, 60000));
    codeView.dataset.title = title;
    fileShown = title;
  }

  async function openPath(path) {
    try {
      const res = await fetch(`/api/fs/read?path=${encodeURIComponent(path)}`);
      if (!res.ok) return;
      const data = await res.json();
      showCode(path, data.content || "");
    } catch { /* panel is best-effort */ }
  }

  function logExec(tool, ok) {
    execList.prepend(h("div", { class: "kv" },
      h("kbd", {}, tool),
      h("span", { style: ok ? "color:var(--ok)" : "color:var(--danger)" }, `${ok ? "ok" : "failed"} · ${timeOf()}`),
    ));
    while (execList.children.length > 24) execList.lastElementChild.remove();
  }

  function projectKv(k, v) {
    ctxList.prepend(h("div", { class: "kv" }, h("kbd", {}, k), h("span", {}, v)));
    while (ctxList.children.length > 14) ctxList.lastElementChild.remove();
  }

  projectKv("cwd", "~/myne");
  return {
    root,
    activate() { },
    event(type, d) {
      if (type === "tool") {
        const execTools = ["run_python", "run_shell", "write_file", "read_file", "search_files", "list_directory"];
        if (!execTools.includes(d.tool)) return;
        if (d.phase === "end") {
          logExec(d.tool, !!d.success);
          projectKv(d.tool, d.success ? "ok" : (d.error || "failed"));
        }
        // show the path the Core just touched (via the Core's read tool)
        const path = d.parameters?.path;
        if ((d.tool === "read_file" || d.tool === "write_file") && path && d.phase !== "start" && path !== fileShown) {
          openPath(path);
        }
      }
    },
  };
}
