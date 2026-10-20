import { api } from "../api.js";
import { state } from "../state.js";
import { esc, toast } from "../ui.js";

const localDateKey = (date) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};

const parseDateOnly = (value) => {
  const [year, month, day] = String(value).split("-").map(Number);
  return new Date(year, month - 1, day);
};

const formatWhen = (item) => item.kind === "prospect"
  ? parseDateOnly(item.due).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })
  : new Date(item.due).toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });

export function buildMyWork(data, now = new Date()) {
  const today = localDateKey(now);
  const items = [
    ...(data.activities || []).map((row) => ({
      kind: "activity", activityId: row.id, due: row.due_at, title: row.subject || row.activity_type || "Activity",
      detail: row.body || "", relationship: [row.account_name, row.opportunity_name].filter(Boolean).join(" · ") || "CRM activity",
      route: row.opportunity_id ? "opportunities" : "activities",
    })),
    ...(data.prospects || []).map((row) => ({
      kind: "prospect", due: row.follow_up_date, title: row.next_action || `Follow up · ${row.stage}`,
      detail: row.stage_note || "", relationship: [row.account_name, row.contact_name].filter(Boolean).join(" · ") || "Prospect",
      route: "prospects",
    })),
  ].filter((item) => item.due);

  const buckets = { overdue: [], today: [], upcoming: [] };
  for (const item of items) {
    const dueDay = item.kind === "prospect"
      ? item.due
      : localDateKey(new Date(item.due));
    const isOverdue = item.kind === "prospect"
      ? dueDay < today
      : new Date(item.due).getTime() < now.getTime();
    buckets[isOverdue ? "overdue" : dueDay === today ? "today" : "upcoming"].push(item);
  }
  for (const rows of Object.values(buckets)) {
    rows.sort((a, b) => {
      const aTime = a.kind === "prospect" ? parseDateOnly(a.due).getTime() : new Date(a.due).getTime();
      const bTime = b.kind === "prospect" ? parseDateOnly(b.due).getTime() : new Date(b.due).getTime();
      return aTime - bTime;
    });
  }
  return buckets;
}

function itemMarkup(item, bucket, canComplete) {
  const dateLabel = bucket === "today" ? `Today · ${formatWhen(item)}` : formatWhen(item);
  const complete = canComplete && item.kind === "activity" && item.activityId && ["overdue", "today"].includes(bucket)
    ? `<button class="button small" type="button" data-complete-activity="${esc(item.activityId)}">Mark complete</button>` : "";
  return `<article class="crm-mywork-item ${bucket}"><div><strong>${esc(item.title)}</strong><small>${esc(item.relationship)} · ${esc(item.kind === "prospect" ? "Prospect follow-up" : "Activity")}</small>${item.detail ? `<p>${esc(item.detail)}</p>` : ""}</div><time>${esc(dateLabel)}</time><div class="crm-mywork-actions">${complete}<button class="button secondary small" data-mywork-tab="${esc(item.route)}">Open</button></div></article>`;
}

export function renderMyWork(data) {
  const buckets = buildMyWork(data);
  const canComplete = !data.read_only;
  const sections = [
    ["overdue", "Overdue"], ["today", "Today"], ["upcoming", "Upcoming"],
  ].map(([key, label]) => `<section class="crm-mywork-section"><header><h3>${label}</h3><span>${buckets[key].length}</span></header>${buckets[key].length ? buckets[key].map((item) => itemMarkup(item, key, canComplete)).join("") : `<p class="crm-mywork-empty">No ${label.toLowerCase()} reminders.</p>`}</section>`).join("");
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "local timezone";
  return `<div class="crm-mywork"><p class="crm-mywork-timezone">Dates are shown in your local timezone (${esc(timezone)}).</p>${sections}</div>`;
}

export function bindMyWorkActions(container, ctx) {
  container.querySelectorAll("[data-complete-activity]").forEach((button) => button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await api(`/api/activities/${encodeURIComponent(button.dataset.completeActivity)}/complete`, { method: "PATCH", body: {} });
      toast("Activity marked complete");
      state.crmTab = "mywork";
      state.unifiedTab.crm = "mywork";
      state.unifiedTab.v53Crm = "mywork";
      ctx.navigate("crm?tab=mywork");
    } catch (error) {
      button.disabled = false;
      toast(error.message || "Could not complete activity", "error");
    }
  }));
}

export async function loadMyWork() {
  return api(`/api/tenants/${state.selectedTenantId}/crm/my-work`);
}

export function maybeShowMyWorkReminder(buckets, page, ctx) {
  if (!buckets.overdue.length && !buckets.today.length) return;
  const identity = `${state.selectedTenantId || "tenant"}:${state.user?.id || "user"}`;
  const key = `rmr-mywork-reminder:${identity}`;
  try {
    if (sessionStorage.getItem(key)) return;
    sessionStorage.setItem(key, "shown");
  } catch {
    // A blocked sessionStorage should not prevent access to CRM.
  }
  const count = buckets.overdue.length + buckets.today.length;
  const reminder = document.createElement("aside");
  reminder.className = "crm-mywork-reminder";
  reminder.setAttribute("role", "status");
  reminder.innerHTML = `<button class="crm-mywork-reminder-close" type="button" aria-label="Dismiss reminder">×</button><strong>Today's MyWork</strong><p>${count} reminder${count === 1 ? "" : "s"} due today or overdue.</p><button class="button" type="button" data-open-mywork>Open MyWork</button>`;
  reminder.querySelector("[data-open-mywork]").addEventListener("click", () => {
    reminder.remove();
    state.unifiedTab.crm = "mywork";
    state.unifiedTab.v53Crm = "mywork";
    state.crmTab = "mywork";
    ctx.navigate("crm?tab=mywork");
  });
  reminder.querySelector(".crm-mywork-reminder-close").addEventListener("click", () => reminder.remove());
  page.append(reminder);
}
