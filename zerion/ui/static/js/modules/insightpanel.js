// modules/insightpanel.js — right rail: Current Goal, Active Tasks,
// Running Tools, Recent Decisions, Notifications. Everything here is a
// live mirror of Core state events; nothing is computed client-side.

import { h, clear, timeOf } from "../core/dom.js";
import { on, emit } from "../core/bus.js";
import { store } from "../core/store.js";

const FEED_MAX = 24;
const TOAST_TTL = 5200;

/* ---------------- current goal ---------------- */
function renderGoal(d) {
  store.runtime.goal = d;
  const el = document.getElementById("goal-text");
  const counters = document.getElementById("goal-counters");
  const active = d.current_goal;
  el.textContent = active || "No active goal.";
  el.dataset.active = active ? "true" : "false";
  clear(counters);
  const mk = (label) => h("span", { class: "section-badge" }, label);
  counters.append(
    mk(`✓ ${d.completed ?? 0}`),
    mk(`✕ ${d.failed ?? 0}`),
    mk(`queued ${d.queued ?? 0}`),
  );
}

/* ---------------- tasks (planner workflow) ---------------- */
function renderTasks(d) {
  store.runtime.tasks = d;
  const list = document.getElementById("tasks-list");
  clear(list);
  const tasks = d.tasks || [];
  document.getElementById("tasks-count").textContent =
    tasks.length ? `${tasks.filter(t => t.state === "completed").length}/${tasks.length}` : "";
  if (!tasks.length) {
    list.appendChild(h("li", { class: "empty-hint" }, "No running plan."));
    return;
  }
  for (const t of tasks) {
    list.appendChild(h("li", { class: "task-row", dataset: { state: t.state } },
      h("span", { class: "task-state", "aria-label": t.state }),
      h("span", { class: "task-desc" },
        t.description,
        t.tool_name ? h("span", { class: "task-tool" }, `→ ${t.tool_name}`) : null,
      ),
    ));
  }
  emit("tasks", d); // automation workspace renders the graph from this
}

/* ---------------- running tools ---------------- */
function renderTool(d) {
  const list = document.getElementById("running-tools");
  const ph = d.phase, name = d.tool || "tool";

  // remove the "Idle." hint on first real entry
  const hint = list.querySelector(".empty-hint");
  if (hint) hint.remove();

  if (ph === "start") {
    const chip = h("li", { class: "tool-chip", dataset: { tool: name } },
      h("span", { class: "spin", "aria-hidden": "true" }),
      h("span", {}, name),
    );
    while (list.children.length >= 6) list.lastElementChild.remove();
    list.appendChild(chip);
    return;
  }
  // finalize matching chip in place
  const chip = [...list.querySelectorAll(".tool-chip")]
    .reverse()
    .find(c => c.dataset.tool === name && !c.dataset.done);
  if (chip) {
    chip.dataset.done = "true";
    chip.dataset.error = d.error || "";
    chip.querySelector(".spin")?.remove();
    chip.appendChild(h("span", { style: "margin-left:auto" },
      ph === "confirm" ? "awaiting approval" : d.success === false ? "failed" : "done"));
  } else if (ph === "end") {
    list.appendChild(h("li", { class: "tool-chip", dataset: { done: "true", tool: name } },
      h("span", {}, name),
      h("span", { style: "margin-left:auto" }, d.success ? "done" : "failed"),
    ));
  }
  // expire finished chips
  if (ph === "end") {
    setTimeout(() => {
      chip?.remove();
      if (!list.children.length) list.appendChild(h("li", { class: "empty-hint" }, "Idle."));
    }, 6000);
  }
}

/* ---------------- feeds ---------------- */
function feedPush(listId, node) {
  const list = document.getElementById(listId);
  if (!list) return;
  list.prepend(node);
  while (list.children.length > FEED_MAX) list.lastElementChild.remove();
}

function renderDecision(d) {
  feedPush("decisions-list", h("li", { class: "feed-item" },
    h("span", { class: "feed-src" }, d.source || "Core"),
    h("time", {}, timeOf()),
    d.text,
  ));
}

function renderNotificationList(d) {
  feedPush("notifications-list", h("li", { class: "feed-item", dataset: { level: d.level || "info" } },
    h("time", {}, timeOf()),
    d.text,
  ));
}

/* ---------------- toasts (big moments only) ---------------- */
export function toast(text, level = "info", ttl = TOAST_TTL) {
  const region = document.getElementById("toast-region");
  const el = h("div", { class: "toast", dataset: { level }, role: "status" }, text);
  region.appendChild(el);
  while (region.children.length > 4) region.firstElementChild.remove();
  setTimeout(() => {
    el.dataset.leaving = "true";
    setTimeout(() => el.remove(), 300);
  }, ttl);
}

on("toast", (d) => toast(d.text, d.level, d.ttl));

/* ---------------- confirmation dialog ---------------- */
function renderConfirm(d) {
  store.runtime.pendingConfirm = d.pending ? d : null;
  const overlay = document.getElementById("confirm-overlay");
  if (!d.pending) { overlay.classList.add("hidden"); return; }
  document.getElementById("confirm-message").textContent =
    d.message || "This action requires your approval.";
  const params = document.getElementById("confirm-params");
  const meta = { ...(d.tool ? { tool: d.tool } : {}), ...(d.command ? { command: d.command } : {}),
                 ...(d.parameters && Object.keys(d.parameters).length ? { parameters: d.parameters } : {}) };
  if (Object.keys(meta).length) {
    params.textContent = JSON.stringify(meta, null, 2);
    params.classList.remove("hidden");
  } else {
    params.classList.add("hidden");
  }
  overlay.classList.remove("hidden");
  document.getElementById("confirm-yes").focus();
}

export function initInsightPanel() {
  on("core:goal", renderGoal);
  on("core:tasks", renderTasks);
  on("core:tool", renderTool);
  on("core:decision", renderDecision);
  on("core:notification", (d) => { renderNotificationList(d); toast(d.text, d.level); });
  on("core:confirm_required", renderConfirm);

  document.getElementById("confirm-yes").addEventListener("click", async () => {
    document.getElementById("confirm-overlay").classList.add("hidden");
    (await import("../core/net.js")).core.confirm();
  });
  document.getElementById("confirm-no").addEventListener("click", async () => {
    document.getElementById("confirm-overlay").classList.add("hidden");
    (await import("../core/net.js")).core.cancel();
  });
  document.getElementById("confirm-overlay").addEventListener("keydown", (e) => {
    if (e.key === "Escape") document.getElementById("confirm-no").click();
  });
}
