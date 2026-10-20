const OPPORTUNITY_STAGES = [
  "Qualified", "Proposal", "Verbal Commitment", "Closed Won", "Closed Lost",
];

const INTERACTIVE_SELECTOR =
  "button, select, input, textarea, a, label, [contenteditable='true']";

function dragRecord(handle) {
  return {
    type: handle.dataset.pipelineDragType,
    id: handle.dataset.pipelineDragId,
    stage: handle.dataset.pipelineDragStage || "",
  };
}

function transferRecord(event) {
  try {
    return JSON.parse(event.dataTransfer?.getData("text/plain") || "null");
  } catch {
    return null;
  }
}

function isInteractiveTarget(target, card) {
  const control = target instanceof Element ? target.closest(INTERACTIVE_SELECTOR) : null;
  return Boolean(control && control !== card && card.contains(control));
}

function accepts(record, zone) {
  if (!record || !zone) return false;
  if (record.type === "prospect") return zone.dataset.stage === "Qualified";
  return record.type === "opportunity" && zone.dataset.stage !== record.stage;
}

export function bindUnifiedPipeline(root, options) {
  if (!root) return;
  const scroll = root.querySelector("[data-pipeline-main-scroll]");
  // Native wheel/trackpad/touch scrolling remains untouched. Some browsers do
  // not translate Shift+wheel into horizontal movement for nested scrollers.
  scroll?.addEventListener("wheel", (event) => {
    if (!event.shiftKey || event.deltaX || !event.deltaY) return;
    const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? scroll.clientWidth : 1;
    const before = scroll.scrollLeft;
    scroll.scrollLeft += event.deltaY * unit;
    if (scroll.scrollLeft !== before) event.preventDefault();
  }, { passive: false });
  const handles = [...root.querySelectorAll("[data-pipeline-drag-handle]")];
  const zones = [...root.querySelectorAll("[data-pipeline-dropzone]")];
  let activeRecord = null;
  let touchHandle = null;
  let sourceCard = null;
  let touchStart = null;
  let touchMoved = false;

  const announce = (message) => {
    if (!message) return;
    const live = root.querySelector("[data-pipeline-live]");
    if (live) live.textContent = message;
  };
  const markTargets = (record) => {
    zones.forEach((zone) => {
      zone.classList.toggle("is-valid-drop", accepts(record, zone));
      zone.classList.toggle("is-invalid-drop", !accepts(record, zone));
    });
  };
  const clearTargets = () => {
    zones.forEach((zone) =>
      zone.classList.remove("is-valid-drop", "is-invalid-drop", "is-drop-over"),
    );
    root.classList.remove("is-pipeline-dragging");
    sourceCard?.classList.remove("is-drag-source");
    activeRecord = null;
    touchHandle = null;
    sourceCard = null;
    touchStart = null;
    touchMoved = false;
  };
  const pending = new Set();
  const perform = async (record, stage, handle) => {
    const key = `${record.type}:${record.id}`;
    if (pending.has(key)) return;
    pending.add(key);
    const card = handle?.closest("[data-pipeline-card]");
    card?.setAttribute("aria-busy", "true");
    handle?.setAttribute("aria-disabled", "true");
    try {
      const message = record.type === "prospect"
        ? await options.onPromoteProspect(record.id, stage)
        : await options.onMoveOpportunity(record.id, record.stage, stage);
      announce(message);
    } catch (error) {
      announce(`Move failed. ${error.message}`);
      options.onError?.(error);
    } finally {
      pending.delete(key);
      card?.removeAttribute("aria-busy");
      handle?.removeAttribute("aria-disabled");
    }
  };
  const dropOn = (record, zone, handle) => {
    if (!accepts(record, zone)) {
      announce(record?.type === "prospect"
        ? "Prospects can only be promoted into Qualified."
        : "That Opportunity is already in this stage.");
      return;
    }
    void perform(record, zone.dataset.stage, handle);
  };

  handles.forEach((handle) => {
    let blockNativeDrag = false;
    let suppressClicksUntil = 0;

    handle.querySelectorAll(INTERACTIVE_SELECTOR).forEach((control) => {
      control.setAttribute("draggable", "false");
      control.addEventListener("dragstart", (event) => event.preventDefault());
    });
    handle.addEventListener("click", (event) => {
      if (Date.now() >= suppressClicksUntil) return;
      event.preventDefault();
      event.stopImmediatePropagation();
    }, true);
    handle.addEventListener("dragstart", (event) => {
      if (blockNativeDrag || isInteractiveTarget(event.target, handle)) {
        event.preventDefault();
        return;
      }
      activeRecord = dragRecord(handle);
      sourceCard = handle.closest("[data-pipeline-card]");
      sourceCard?.classList.add("is-drag-source");
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", JSON.stringify(activeRecord));
      }
      root.classList.add("is-pipeline-dragging");
      markTargets(activeRecord);
      announce(`Moving ${handle.dataset.pipelineDragLabel}. Choose a highlighted stage.`);
    });
    handle.addEventListener("dragend", () => {
      suppressClicksUntil = Date.now() + 400;
      blockNativeDrag = false;
      clearTargets();
    });
    handle.addEventListener("keydown", (event) => {
      if (isInteractiveTarget(event.target, handle)) return;
      const record = dragRecord(handle);
      if (record.type !== "opportunity" || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      event.stopPropagation();
      const current = OPPORTUNITY_STAGES.indexOf(record.stage);
      const destination = OPPORTUNITY_STAGES[current + (event.key === "ArrowRight" ? 1 : -1)];
      if (!destination) {
        announce(`No ${event.key === "ArrowRight" ? "later" : "earlier"} stage is available.`);
        return;
      }
      void perform(record, destination, handle);
    });
    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || event.isPrimary === false) return;
      blockNativeDrag = isInteractiveTarget(event.target, handle);
      if (blockNativeDrag) return;
      touchHandle = handle;
      activeRecord = dragRecord(handle);
      sourceCard = handle.closest("[data-pipeline-card]");
      touchStart = { x: event.clientX, y: event.clientY };
      touchMoved = false;
      handle.setPointerCapture?.(event.pointerId);
    });
    handle.addEventListener("pointermove", (event) => {
      if (touchHandle !== handle || !activeRecord || !touchStart) return;
      if (!touchMoved) {
        const distance = Math.hypot(event.clientX - touchStart.x, event.clientY - touchStart.y);
        if (distance < 7) return;
        touchMoved = true;
        sourceCard?.classList.add("is-drag-source");
        root.classList.add("is-pipeline-dragging");
        markTargets(activeRecord);
        announce(`Moving ${handle.dataset.pipelineDragLabel}. Drag to a highlighted stage.`);
      }
      event.preventDefault();
      if (scroll) {
        const bounds = scroll.getBoundingClientRect();
        if (event.clientX < bounds.left + 32) scroll.scrollLeft -= 18;
        else if (event.clientX > bounds.right - 32) scroll.scrollLeft += 18;
      }
      zones.forEach((zone) => zone.classList.remove("is-drop-over"));
      const zone = document.elementFromPoint(event.clientX, event.clientY)?.closest?.("[data-pipeline-dropzone]");
      if (zone && accepts(activeRecord, zone)) zone.classList.add("is-drop-over");
    });
    handle.addEventListener("pointerup", (event) => {
      blockNativeDrag = false;
      if (touchHandle !== handle || !activeRecord) return;
      const record = activeRecord;
      const wasMoved = touchMoved;
      const zone = wasMoved
        ? document.elementFromPoint(event.clientX, event.clientY)?.closest?.("[data-pipeline-dropzone]")
        : null;
      clearTargets();
      if (!wasMoved) return;
      suppressClicksUntil = Date.now() + 400;
      if (zone) dropOn(record, zone, handle);
      else announce("Move cancelled.");
    });
    handle.addEventListener("pointercancel", () => {
      if (touchMoved) suppressClicksUntil = Date.now() + 400;
      blockNativeDrag = false;
      clearTargets();
    });
  });

  zones.forEach((zone) => {
    zone.addEventListener("dragover", (event) => {
      const record = activeRecord || transferRecord(event);
      if (!accepts(record, zone)) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
      zone.classList.add("is-drop-over");
    });
    zone.addEventListener("dragleave", () => zone.classList.remove("is-drop-over"));
    zone.addEventListener("drop", (event) => {
      event.preventDefault();
      const record = activeRecord || transferRecord(event);
      const handle = handles.find((item) => item.dataset.pipelineDragId === record?.id);
      clearTargets();
      if (record) dropOn(record, zone, handle);
    });
  });
}
