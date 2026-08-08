// modules/modes/phone.js — phone-control workspace.
//
// Surfaces ONLY real device state from the phone body manager:
// capabilities discovered by the registry, the live action lifecycle,
// approvals, permissions, verification verdicts, and the audit trail.
// Nothing fabricated; what the platform cannot answer lists as unknown.

import { h, clear, timeOf } from "../../core/dom.js";
import { on } from "../../core/bus.js";
import { api } from "../../core/net.js";

export function createMode() {
  const stateCard = h("div", { class: "kv-list" });
  const actionCard = h("div", { class: "kv-list" });
  const auditCard = h("div", { class: "research-list" });

  const root = h("section", { "aria-label": "Phone body workspace" },
    h("div", { class: "ws-banner" },
      h("span", { class: "ws-mode-dot" }),
      h("span", { class: "ws-mode-name" }, "Phone Control"),
      h("span", { class: "ws-mode-sub" }, "Zerion's physical body — approvals govern every effect"),
    ),
    h("div", { class: "ws-grid" },
      h("div", { class: "ws-card glass" },
        h("div", { class: "ws-card-title" }, "Active Action & Permissions"),
        actionCard),
      h("div", { class: "ws-sidecol" },
        h("div", { class: "ws-card glass" },
          h("div", { class: "ws-card-title" }, "Device State"),
          stateCard),
        h("div", { class: "ws-card glass" },
          h("div", { class: "ws-card-title" }, "Action Trail"),
          auditCard),
      ),
    ),
  );

  function kv(list, k, v, tone) {
    list.prepend(h("div", { class: "kv" },
      h("kbd", {}, k), h("span", tone ? { style: `color:${tone}` } : {}, v)));
    while (list.children.length > 20) list.lastElementChild.remove();
  }

  async function refresh() {
    try {
      const { phone } = await api("/api/phone/state");
      clear(stateCard);
      kv(stateCard, "platform", phone.platform ?? "—");
      kv(stateCard, "battery", phone.battery?.percent != null ? `${phone.battery.percent}%` : "unknown");
      kv(stateCard, "wifi", phone.network?.ssid_or_status ? phone.network.ssid_or_status
         : (phone.network ? "connected" : "unknown"));
      kv(stateCard, "capabilities", `${phone.available_capabilities?.length ?? 0}/${phone.capabilities_total ?? 0} present`);
      kv(stateCard, "denied", (phone.permissions?.denied ?? []).join(", ") || "none");
      const pending = phone.pending_approvals || [];
      if (pending.length) {
        kv(stateCard, "awaiting approval", pending.map(a => a.capability).join(", "), "var(--warn)");
      }
    } catch { /* body optional */ }
  }

  on("core:phone_state", (snap) => {
    const act = snap.current_action ? `action ${snap.current_action}` : "idle";
    kv(actionCard, "now", act);
    const pend = snap.permissions?.denied || [];
    kv(actionCard, "denied perms", pend.join(", ") || "none", pend.length ? "var(--danger)" : null);
    const recent = snap.recent_actions || [];
    if (recent.length) {
      clear(auditCard);
      for (const a of recent.slice(-8)) {
        auditCard.appendChild(h("div", { class: "research-item" },
          h("span", { class: "ri-title" }, `${a.capability} ${a.risk_level === "consequential" ? "⚠" : ""}`),
          h("span", { class: "ri-meta" },
            `${a.execution_state} · ${a.approval_state} · ${a.verification} · ${a.attempts} attempt(s)`),
        ));
      }
    }
  });

  return { root, activate() { refresh(); }, event() { } };
}
