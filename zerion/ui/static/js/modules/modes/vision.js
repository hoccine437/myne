// modules/modes/vision.js — vision workspace: drag/drop or pick an
// image, inspect it (pinch/zoom/pan on touch and wheel), and route it to
// the Core for analysis. The Core is text-first, so the image itself is
// staged client-side; any analysis events the Core emits later render
// into the analysis rail without layout changes.

import { h, clear } from "../../core/dom.js";
import { core } from "../../core/net.js";
import { on } from "../../core/bus.js";

export function createMode() {
  const frame = h("div", { class: "vision-frame" });
  const analysis = h("div", { class: "kv-list" });
  const objects = h("div", { class: "kv-list" });

  const drop = h("div", { class: "vision-drop" },
    h("span", { class: "hint-glyph", style: "font-size:26px; display:block" }, "◍"),
    "Drop an image here, or tap to choose — it stays local until you ask Zerion about it.",
  );

  const fileInput = h("input", { type: "file", accept: "image/*", class: "hidden", "aria-label": "Choose an image" });

  const root = h("section", { "aria-label": "Vision workspace" },
    h("div", { class: "ws-banner" },
      h("span", { class: "ws-mode-dot" }),
      h("span", { class: "ws-mode-name" }, "Vision"),
      h("span", { class: "ws-mode-sub" }, "image staged locally · analysis via the Core on request"),
    ),
    h("div", { class: "vision-grid" },
      h("div", { class: "ws-card glass" },
        h("div", { class: "ws-card-title" }, "Image"),
        frame, fileInput,
        h("div", { class: "action-row", style: "margin-top:8px" },
          h("button", { class: "mini-btn", type: "button", onclick: () => fileInput.click() }, "Choose image"),
          h("button", {
            class: "mini-btn hidden", type: "button", id: "vision-ask",
            onclick: () => sendImageToCore(),
          }, "Ask Zerion about it"),
        ),
      ),
      h("div", { class: "ws-sidecol" },
        h("div", { class: "ws-card glass" },
          h("div", { class: "ws-card-title" }, "Analysis"),
          analysis,
        ),
        h("div", { class: "ws-card glass" },
          h("div", { class: "ws-card-title" }, "Detected Objects / OCR"),
          objects,
        ),
      ),
    ),
  );

  frame.appendChild(drop);

  let currentName = "";
  let imgEl = null;

  function kv(list, k, v) {
    list.prepend(h("div", { class: "kv" }, h("kbd", {}, k), h("span", {}, v)));
    while (list.children.length > 16) list.lastElementChild.remove();
  }

  function stageFile(file) {
    if (!file || !file.type.startsWith("image/")) return;
    currentName = file.name;
    const url = URL.createObjectURL(file);
    clear(frame);
    imgEl = h("img", { src: url, alt: `Staged image ${file.name}` });
    frame.appendChild(imgEl);
    enableZoom(imgEl, frame);
    document.getElementById("vision-ask")?.classList.remove("hidden");
    kv(analysis, "image", file.name);
    kv(analysis, "size", `${(file.size / 1024).toFixed(0)} KB`);
    kv(analysis, "type", file.type);
    imgEl.onload = () => kv(analysis, "dimensions", `${imgEl.naturalWidth}×${imgEl.naturalHeight}px`);
  }

  // pinch / wheel zoom + drag pan — pointer-event based, touch & mouse
  function enableZoom(img, container) {
    let scale = 1, tx = 0, ty = 0;
    const pts = new Map();
    let pinchDist = 0, panStart = null;

    const apply = () => { img.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`; };
    img.style.transformOrigin = "center center";
    container.style.touchAction = "none";

    container.addEventListener("wheel", (e) => {
      e.preventDefault();
      scale = Math.min(6, Math.max(0.5, scale * (e.deltaY < 0 ? 1.12 : 0.89)));
      apply();
    }, { passive: false });

    container.addEventListener("pointerdown", (e) => {
      pts.set(e.pointerId, [e.clientX, e.clientY]);
      container.setPointerCapture(e.pointerId);
      if (pts.size === 2) {
        const [a, b] = [...pts.values()];
        pinchDist = Math.hypot(a[0] - b[0], a[1] - b[1]);
      } else {
        panStart = [e.clientX - tx, e.clientY - ty];
      }
    });
    container.addEventListener("pointermove", (e) => {
      if (!pts.has(e.pointerId)) return;
      pts.set(e.pointerId, [e.clientX, e.clientY]);
      if (pts.size === 2) {
        const [a, b] = [...pts.values()];
        const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        if (pinchDist) scale = Math.min(6, Math.max(0.5, scale * (d / pinchDist)));
        pinchDist = d;
      } else if (panStart) {
        tx = e.clientX - panStart[0]; ty = e.clientY - panStart[1];
      }
      apply();
    });
    const up = (e) => { pts.delete(e.pointerId); if (!pts.size) panStart = null; };
    container.addEventListener("pointerup", up);
    container.addEventListener("pointercancel", up);
    container.addEventListener("dblclick", () => { scale = 1; tx = ty = 0; apply(); });
  }

  frame.addEventListener("click", () => { if (!imgEl) fileInput.click(); });
  fileInput.addEventListener("change", () => stageFile(fileInput.files[0]));
  for (const ev of ["dragover", "dragleave", "drop"]) {
    frame.addEventListener(ev, (e) => {
      e.preventDefault();
      if (ev === "drop") stageFile(e.dataTransfer.files[0]);
    });
  }

  kv(objects, "ocr", "via shared vision pipeline (no separate OCR engine — never faked)");
  kv(objects, "objects", "detected by the model's real visual analysis, not invented here");

  // wire the real multimodal turn: actual image bytes → Core → same brain
  let currentFile = null;
  const origStage = stageFile;
  function sendImageToCore() {
    const file = currentFile;
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      core.image({
        text: "Describe this image precisely: content, layout, quality, and anything readable in it.",
        data: String(reader.result).split(",").pop(),
        name: file.name, mime: file.type || "image/jpeg",

      });
    };
    reader.readAsDataURL(file);
  }
  window.__zerionSendImage = sendImageToCore;
  stageFile = (file) => { currentFile = file; origStage(file); };

  // global drag & drop of an image stages here (gestures.js); a stash
  // covers the race where the drop preceded this mode's creation
  const offStage = on("ui:stage-image", ({ file }) => stageFile(file));
  if (window.__zerionPendingImage) {
    stageFile(window.__zerionPendingImage);
    window.__zerionPendingImage = null;
  }

  return {
    root,
    activate() { },
    event(type, d) {
      if (type === "stage" && d.stage === "llm" && d.status === "done") {
        kv(analysis, "last model pass", "see conversation");
      }
    },
    dispose() { offStage(); },
  };
}
