const TYPE_META = {
  observation: {
    label: "实验观察",
    hint: "记录现象、测量值、异常或实验条件。",
    placeholder:
      "例如：第 3 组在 37.2°C 下反应 24h，产率 68%，较上批高 4 个百分点。",
  },
  decision: {
    label: "研究决策",
    hint: "记录取舍、判断依据与影响范围，方便下一次交接复核。",
    placeholder:
      "例如：下一阶段优先复现异常组，暂停扩大样本量，待三次重复后再评估。",
  },
  todo: {
    label: "下一步待办",
    hint: "把下一步写成可执行动作，交接时可直接继续。",
    placeholder:
      "例如：补齐 3 次重复实验，并在周五前完成统计分析。",
  },
  link: {
    label: "原始资料",
    hint: "链接会写入 Memory，并额外保存为 PowerContext Source 证据。",
    placeholder: "",
  },
  other: {
    label: "其他记录",
    hint: "未识别的记录类型。",
    placeholder: "",
  },
};

const MATCH_LABELS = {
  fts: "全文命中",
  vector: "向量命中",
};

const state = {
  health: null,
  tasks: [],
  activeId: null,
  detail: null,
  renderedTaskId: null,
  activeTab: "timeline",
  search: null,
  handoff: null,
  searchLoading: false,
  handoffLoading: false,
  entryBusy: false,
  creating: false,
  detailController: null,
};

const $ = (id) => document.getElementById(id);

const timeFormatter = new Intl.DateTimeFormat("zh-CN", {
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZone: "Asia/Shanghai",
});

const dateTimeFormatter = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZone: "Asia/Shanghai",
});

const dayFormatter = new Intl.DateTimeFormat("zh-CN", {
  month: "long",
  day: "numeric",
  weekday: "long",
  timeZone: "Asia/Shanghai",
});

const keyFormatter = new Intl.DateTimeFormat("en-CA", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  timeZone: "Asia/Shanghai",
});

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (
      key === "checked" ||
      key === "disabled" ||
      key === "hidden" ||
      key === "value"
    ) {
      node[key] = value;
    } else {
      node.setAttribute(key, value === true ? "" : String(value));
    }
  }
  for (const child of children.flat()) {
    if (child === undefined || child === null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function parseDate(iso) {
  if (!iso) return null;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatTime(iso) {
  const date = parseDate(iso);
  return date ? timeFormatter.format(date) : "时间未知";
}

function formatDateTime(iso) {
  const date = parseDate(iso);
  return date ? dateTimeFormatter.format(date) : "时间未知";
}

function dateKey(value) {
  const date = value instanceof Date ? value : parseDate(value);
  if (!date) return "unknown";
  const parts = keyFormatter.formatToParts(date);
  const pick = (type) => parts.find((part) => part.type === type)?.value ?? "";
  return `${pick("year")}-${pick("month")}-${pick("day")}`;
}

function dayLabel(iso) {
  const date = parseDate(iso);
  if (!date) return "时间未知";
  const key = dateKey(date);
  const today = dateKey(new Date());
  const yesterday = dateKey(new Date(Date.now() - 24 * 60 * 60 * 1000));
  const label = dayFormatter.format(date);
  if (key === today) return `今天 · ${label}`;
  if (key === yesterday) return `昨天 · ${label}`;
  return label;
}

function shortId(value, length = 18) {
  const text = String(value ?? "");
  if (!text) return "—";
  if (text.length <= length) return text;
  return `${text.slice(0, 10)}…${text.slice(-6)}`;
}

function isOnline() {
  return Boolean(state.health?.powercontext?.online);
}

function byteLength(value) {
  return new TextEncoder().encode(String(value ?? "")).length;
}

async function api(path, { method = "GET", body, signal } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
      cache: "no-store",
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    const wrapped = new Error("无法连接本地应用服务。");
    wrapped.code = "app_unreachable";
    wrapped.cause = error;
    throw wrapped;
  }

  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    const error = new Error(
      data?.error?.message || `请求失败（HTTP ${response.status}）。`,
    );
    error.status = response.status;
    error.code = data?.error?.code || "request_failed";
    error.details = data?.error?.details ?? null;
    error.requestId = data?.error?.requestId ?? null;
    throw error;
  }
  return data;
}

let toastSequence = 0;
function toast(message, tone = "info", duration = 4200) {
  const region = $("toast-region");
  while (region.children.length >= 4) {
    region.firstElementChild?.remove();
  }
  const node = el(
    "div",
    { class: `toast toast-${tone}`, role: "status" },
    el("span", { class: "toast-dot", "aria-hidden": "true" }),
    el("span", { text: message }),
  );
  node.dataset.toastId = String(++toastSequence);
  region.append(node);
  requestAnimationFrame(() => node.classList.add("is-visible"));
  window.setTimeout(() => {
    node.classList.remove("is-visible");
    window.setTimeout(() => node.remove(), 220);
  }, duration);
}

async function copyText(text, successMessage = "已复制") {
  try {
    await navigator.clipboard.writeText(text);
    toast(successMessage, "success");
    return;
  } catch {
    const area = el("textarea", {
      class: "sr-only",
      value: text,
      "aria-hidden": "true",
    });
    document.body.append(area);
    area.select();
    let copied = false;
    try {
      copied = document.execCommand("copy");
    } catch {
      copied = false;
    }
    area.remove();
    toast(copied ? successMessage : "复制失败，请手动选择文本。", copied ? "success" : "warning");
  }
}

function readHashTaskId() {
  const match = /^#\/task\/(.+)$/.exec(window.location.hash);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return null;
  }
}

function writeHash(taskId, { replace = false } = {}) {
  const hash = `#/task/${encodeURIComponent(taskId)}`;
  if (window.location.hash === hash) return;
  if (replace) {
    window.history.replaceState(null, "", hash);
  } else {
    window.history.pushState(null, "", hash);
  }
}

function clearHash() {
  window.history.replaceState(
    null,
    "",
    `${window.location.pathname}${window.location.search}`,
  );
}

function extractUrl(text) {
  const match = String(text ?? "").match(/https?:\/\/[^\s<>"']+/i);
  if (!match) return null;
  try {
    const url = new URL(match[0]);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    return url.toString();
  } catch {
    return null;
  }
}

function updateAvailability() {
  const online = isOnline();
  document.querySelectorAll("[data-requires-service]").forEach((button) => {
    const busy = button.dataset.busy === "true";
    button.disabled = !online || busy;
    button.title = online ? "" : "PowerContext 服务不可用";
  });
  const createSubmit = $("create-submit");
  if (createSubmit) {
    createSubmit.disabled = !online || state.creating;
    createSubmit.title = online ? "" : "PowerContext 服务不可用";
  }
}

function setBusy(button, busy, busyText, fallbackIdleText = null) {
  if (!button) return;
  if (busy) {
    if (!button.dataset.idleText) {
      button.dataset.idleText = button.textContent.trim();
    }
    button.dataset.busy = "true";
    button.textContent = busyText;
  } else {
    button.dataset.busy = "false";
    if (fallbackIdleText) {
      button.textContent = fallbackIdleText;
    } else if (button.dataset.idleText) {
      button.textContent = button.dataset.idleText;
    }
    delete button.dataset.idleText;
  }
  updateAvailability();
}

function applyHealth(data, { appUnreachable = false } = {}) {
  state.health = data;
  const pc = data?.powercontext || {};
  const status = pc.status || "offline";
  const chip = $("health-chip");
  const banner = $("offline-banner");
  const serviceCard = $("service-card");

  chip.classList.remove("is-online", "is-warning", "is-offline", "is-checking");
  if (status === "online") {
    chip.classList.add("is-online");
    chip.textContent = "PowerContext 在线";
  } else if (status === "auth-error" || status === "degraded") {
    chip.classList.add("is-warning");
    chip.textContent =
      status === "auth-error" ? "PowerContext 鉴权异常" : "PowerContext 状态异常";
  } else {
    chip.classList.add("is-offline");
    chip.textContent = "PowerContext 不可用";
  }

  $("service-endpoint").textContent = pc.endpoint || "—";
  $("service-token").textContent = pc.tokenConfigured
    ? "已配置（不展示）"
    : "未配置";
  $("service-version").textContent = pc.version || "未知";
  $("service-checked").textContent = pc.checkedAt
    ? formatTime(pc.checkedAt)
    : "—";
  serviceCard.classList.toggle("is-online", status === "online");
  serviceCard.classList.toggle("is-offline", status !== "online");

  if (status === "online") {
    $("service-status").textContent = "已连接，可读写";
    banner.hidden = true;
  } else {
    $("service-status").textContent =
      status === "auth-error"
        ? "鉴权失败"
        : status === "degraded"
          ? "API 状态异常"
          : "服务不可用";
    banner.hidden = false;
    banner.classList.toggle(
      "is-warning",
      status === "auth-error" || status === "degraded",
    );
    const title = appUnreachable
      ? "本地应用连接中断"
      : status === "auth-error"
        ? "PowerContext 鉴权失败"
        : status === "degraded"
          ? "PowerContext 状态异常"
          : "PowerContext 服务不可用";
    $("banner-title").textContent = title;
    $("banner-detail").textContent = `${pc.detail || "无法读取服务状态。"} 端点：${
      pc.endpoint || "—"
    }。本应用不会使用本地 JSON 或模拟后端替代。`;
  }

  updateAvailability();
}

async function refreshHealth({ silent = false } = {}) {
  const chip = $("health-chip");
  if (!silent) {
    chip.classList.remove("is-online", "is-warning", "is-offline");
    chip.classList.add("is-checking");
    chip.textContent = "检测服务中…";
  }

  try {
    const data = await api("/api/health");
    applyHealth(data);
    return data;
  } catch (error) {
    applyHealth(
      {
        app: { name: "实验续航 / Research Relay" },
        storage: { mode: "powercontext-http", localFallback: false },
        powercontext: {
          status: "offline",
          online: false,
          endpoint: "—",
          tokenConfigured: false,
          version: null,
          checkedAt: new Date().toISOString(),
          detail: error.message,
        },
      },
      { appUnreachable: true },
    );
    if (!silent) toast(error.message, "danger", 6000);
    return null;
  }
}

function renderTaskList() {
  const list = $("task-list");
  list.replaceChildren();
  if (state.tasks.length === 0) {
    list.append(el("p", { class: "task-list-empty", text: "还没有研究任务" }));
    return;
  }

  for (const task of state.tasks) {
    const active = task.id === state.activeId;
    const button = el(
      "button",
      {
        class: `task-item${active ? " is-active" : ""}`,
        type: "button",
        "aria-current": active ? "true" : null,
        title: task.title,
      },
      el("span", { class: "task-item-title", text: task.title }),
      el(
        "span",
        { class: "task-item-meta" },
        el("span", { class: "task-dot", "aria-hidden": "true" }),
        task.createdAt
          ? formatDateTime(task.createdAt)
          : task.version
            ? `Scope v${task.version}`
            : "时间未知",
      ),
    );
    button.addEventListener("click", () => selectTask(task.id));
    list.append(button);
  }
}

function showEmptyWorkspace() {
  $("workspace-empty").hidden = false;
  $("workspace-status").hidden = true;
  $("workspace-task").hidden = true;
  document.title = "实验续航 / Research Relay";
}

function showStatusLoading() {
  $("workspace-empty").hidden = true;
  $("workspace-task").hidden = true;
  const status = $("workspace-status");
  status.hidden = false;
  status.replaceChildren(
    el(
      "div",
      { class: "status-card" },
      el("div", { class: "status-mark is-loading", text: "…" }),
      el("h2", { text: "正在读取 PowerContext" }),
      el("p", { class: "loading-note", text: "正在从真实 PowerContext HTTP API 读取研究任务与记录。" }),
      el("div", { class: "skeleton skeleton-title" }),
      el("div", { class: "skeleton skeleton-line wide" }),
      el("div", { class: "skeleton skeleton-line" }),
      el("div", { class: "skeleton skeleton-card" }),
    ),
  );
}

function showStatusError(title, message, retry) {
  $("workspace-empty").hidden = true;
  $("workspace-task").hidden = true;
  const status = $("workspace-status");
  status.hidden = false;
  const retryButton = el("button", {
    class: "btn btn-primary btn-small",
    type: "button",
    text: "重新尝试",
  });
  retryButton.addEventListener("click", async () => {
    retryButton.disabled = true;
    retryButton.textContent = "正在重试…";
    try {
      await retry();
    } finally {
      retryButton.disabled = false;
      retryButton.textContent = "重新尝试";
    }
  });
  status.replaceChildren(
    el(
      "div",
      { class: "status-card" },
      el("div", { class: "status-mark", text: "!" }),
      el("h2", { text: title }),
      el("p", { text: message }),
      el("p", {
        class: "loading-note",
        text: "本应用不保存本地任务副本；服务恢复后将从 PowerContext 重新读取。",
      }),
      el("div", { class: "status-actions" }, retryButton),
    ),
  );
}

async function loadTasks({ selectId = null, keepSelection = false, replaceHash = false } = {}) {
  try {
    const data = await api("/api/tasks");
    state.tasks = Array.isArray(data.tasks) ? data.tasks : [];
    renderTaskList();

    if (state.tasks.length === 0) {
      state.activeId = null;
      state.detail = null;
      state.renderedTaskId = null;
      clearHash();
      showEmptyWorkspace();
      return;
    }

    const hashId = readHashTaskId();
    const hashValid = Boolean(hashId && state.tasks.some((task) => task.id === hashId));
    const targetId =
      selectId ||
      (keepSelection && state.activeId) ||
      (hashValid ? hashId : null) ||
      state.tasks[0].id;
    const exists = state.tasks.some((task) => task.id === targetId);
    const finalId = exists ? targetId : state.tasks[0].id;

    if (state.activeId === finalId && state.detail) {
      writeHash(finalId, { replace: replaceHash || !hashValid });
      return;
    }

    await selectTask(finalId, { updateHash: false });
    writeHash(finalId, {
      replace: replaceHash || !hashValid || Boolean(selectId),
    });
  } catch (error) {
    renderTaskList();
    handleApiError(error);
    showStatusError(
      "无法读取研究任务",
      `${error.message} 本应用没有本地任务副本。`,
      () => loadTasks({ selectId, keepSelection, replaceHash }),
    );
  }
}

async function selectTask(taskId, { updateHash = true } = {}) {
  if (!state.tasks.some((task) => task.id === taskId)) return;
  state.activeId = taskId;
  state.search = null;
  state.handoff = null;
  state.searchLoading = false;
  state.handoffLoading = false;
  renderTaskList();
  resetSearchPanel();
  resetHandoffPanel();
  activateTab("timeline", { silent: true });
  if (updateHash) writeHash(taskId);
  await loadDetail(taskId);
}

async function loadDetail(taskId, { quiet = false } = {}) {
  if (state.detailController) state.detailController.abort();
  const controller = new AbortController();
  state.detailController = controller;
  if (!quiet) showStatusLoading();

  try {
    const data = await api(`/api/tasks/${encodeURIComponent(taskId)}`, {
      signal: controller.signal,
    });
    if (controller.signal.aborted) return;
    state.detail = data;
    renderTask();
  } catch (error) {
    if (error.name === "AbortError") return;
    state.detail = null;
    handleApiError(error);
    showStatusError(
      "无法读取研究任务",
      error.message,
      () => loadDetail(taskId),
    );
  }
}

function renderTask() {
  if (!state.detail) return;
  const { task, entries, sources, stats } = state.detail;
  $("workspace-empty").hidden = true;
  $("workspace-status").hidden = true;
  $("workspace-task").hidden = false;

  document.title = `${task.title} · 实验续航`;
  $("task-title").textContent = task.title;
  $("task-summary").textContent = task.summary || "尚未补充研究摘要。";
  $("scope-short").textContent = shortId(task.id, 20);
  $("copy-scope").title = `复制 PowerContext Scope ID：${task.id}`;
  $("task-created").textContent = task.createdAt
    ? `创建于 ${formatDateTime(task.createdAt)}`
    : task.version
      ? `Scope 版本 v${task.version}`
      : "创建时间未知";

  renderStats(stats, sources.length);
  $("tab-count").textContent = String(stats.total);
  renderTimeline(entries);

  const switched = state.renderedTaskId !== task.id;
  state.renderedTaskId = task.id;
  if (switched) {
    resetEntryForm();
    resetSearchPanel();
    resetHandoffPanel();
    activateTab("timeline", { silent: true });
  }
}

function renderStats(stats, sourceCount) {
  const definitions = [
    { key: "observation", label: "实验观察", value: stats.observation },
    { key: "decision", label: "研究决策", value: stats.decision },
    { key: "todo", label: "下一步待办", value: stats.todo },
    { key: "link", label: "原始资料", value: stats.link },
    { key: "source", label: "Source 证据", value: sourceCount },
  ];

  $("task-stats").replaceChildren(
    ...definitions.map((definition) =>
      el(
        "div",
        { class: `stat stat-${definition.key}` },
        el("span", { class: "stat-value", text: String(definition.value) }),
        el("span", { class: "stat-label", text: definition.label }),
      ),
    ),
  );
}

function renderTimeline(entries) {
  const timeline = $("timeline");
  timeline.replaceChildren();

  if (!entries || entries.length === 0) {
    const empty = el(
      "div",
      { class: "inline-empty" },
      el("span", { text: "还没有记录。用右侧表单写入第一条实验观察、决策、待办或资料链接。" }),
    );
    timeline.append(empty);
    return;
  }

  const groups = new Map();
  for (const entry of entries) {
    const key = entry.createdAt ? dateKey(entry.createdAt) : "unknown";
    if (!groups.has(key)) groups.set(key, { label: entry.createdAt ? dayLabel(entry.createdAt) : "时间未知", entries: [] });
    groups.get(key).entries.push(entry);
  }

  for (const group of groups.values()) {
    const section = el(
      "section",
      { class: "timeline-group" },
      el("h3", { class: "day-heading", text: group.label }),
    );
    const list = el("div", { class: "entry-list" });
    for (const entry of group.entries) list.append(renderEntry(entry));
    section.append(list);
    timeline.append(section);
  }
}

function citationParts(citation) {
  if (!citation) return null;
  if (citation.artifactId !== undefined) {
    return {
      artifactId: citation.artifactId,
      artifactRevision: citation.artifactRevision,
      entryId: citation.entryId,
      entryVersionId: citation.entryVersionId,
    };
  }
  const ref = citation.memory_ref || {};
  return {
    artifactId: ref.artifact_id ?? null,
    artifactRevision: ref.revision ?? null,
    entryId: citation.entry_id ?? null,
    entryVersionId: citation.entry_version_id ?? null,
  };
}

function citationText(entry, citation = citationParts(entry?.citation)) {
  if (!citation) return "";
  let text = `PowerContext memory ${citation.artifactId}@r${citation.artifactRevision}; entry ${citation.entryId}; entry_version ${citation.entryVersionId}; scope ${state.activeId}`;
  if (entry?.source?.sourceId) text += `; source ${entry.source.sourceId}`;
  return text;
}

function renderCitationChips(container, citation, source) {
  const parts = citationParts(citation);
  if (parts) {
    container.append(
      el("span", { class: "cite-chip" }, el("strong", { text: "Memory" }), `${shortId(parts.artifactId, 16)}@r${parts.artifactRevision ?? "?"}`),
      el("span", { class: "cite-chip" }, el("strong", { text: "entry" }), shortId(parts.entryId, 16)),
      el("span", { class: "cite-chip" }, el("strong", { text: "v" }), shortId(parts.entryVersionId, 12)),
    );
  }
  if (source?.sourceId) {
    container.append(
      el(
        "span",
        { class: "cite-chip", title: source.contentPreview || "" },
        el("strong", { text: "Source" }),
        shortId(source.sourceId, 20),
      ),
    );
    if (source.digest) {
      container.append(
        el("span", { class: "cite-chip" }, el("strong", { text: "digest" }), shortId(source.digest, 16)),
      );
    }
  }
}

function renderEntry(entry) {
  const type = TYPE_META[entry.type] ? entry.type : "other";
  const meta = TYPE_META[type];
  const card = el("article", { class: `entry-card type-${type}` });

  card.append(
    el(
      "div",
      { class: "entry-top" },
      el(
        "span",
        { class: `type-badge badge-${type}` },
        el("span", { class: "badge-dot", "aria-hidden": "true" }),
        meta.label,
      ),
      el("time", {
        class: "entry-time",
        datetime: entry.createdAt || "",
        text: entry.createdAt ? formatTime(entry.createdAt) : "时间未知",
      }),
    ),
    el("p", { class: "entry-text", text: entry.text }),
  );

  if (type === "link") {
    const url = extractUrl(entry.text);
    if (url) {
      card.append(
        el(
          "a",
          {
            class: "entry-link",
            href: url,
            target: "_blank",
            rel: "noreferrer noopener",
          },
          "打开原始资料",
        ),
      );
    }
  }

  const footer = el("div", { class: "entry-footer" });
  renderCitationChips(footer, entry.citation, entry.source);
  if (!entry.citation && !entry.source) {
    footer.append(el("span", { class: "cite-chip", text: "等待条目引用" }));
  }
  if (entry.citation) {
    const copy = el("button", {
      class: "cite-copy",
      type: "button",
      text: "复制引用",
    });
    copy.addEventListener("click", () =>
      copyText(citationText(entry), "引用已复制"),
    );
    footer.append(copy);
  }
  card.append(footer);
  return card;
}

function getEntryType() {
  return document.querySelector('input[name="entry-type"]:checked')?.value || "observation";
}

function resetEntryForm() {
  const form = $("entry-form");
  form.reset();
  const first = form.querySelector('input[name="entry-type"][value="observation"]');
  if (first) first.checked = true;
  $("link-title").value = "";
  $("link-url").value = "";
  $("entry-text").value = "";
  $("entry-note").value = "";
  $("entry-error").hidden = true;
  $("entry-error").textContent = "";
  syncEntryForm();
}

function syncEntryForm() {
  const type = getEntryType();
  const meta = TYPE_META[type] || TYPE_META.other;
  document.querySelectorAll(".type-option").forEach((option) => {
    option.classList.toggle("is-selected", option.dataset.type === type);
  });

  const isLink = type === "link";
  $("link-fields").hidden = !isLink;
  $("text-field").hidden = isLink;
  $("entry-text").required = !isLink;
  $("link-url").required = isLink;
  $("text-label").textContent = `${meta.label}内容`;
  $("entry-text").placeholder = meta.placeholder;
  $("type-hint").textContent = meta.hint;
  updateCharCount();
}

function updateCharCount() {
  const type = getEntryType();
  const text = $("entry-text").value;
  const note = $("entry-note").value;
  const counter = $("char-count");
  let bytes;
  let label;

  if (type === "link") {
    bytes =
      byteLength($("link-title").value) +
      byteLength($("link-url").value) +
      byteLength(note) +
      24;
    label = `资料内容约 ${bytes} 字节`;
  } else {
    bytes = byteLength(text) + byteLength(note) + 20;
    label = `${bytes} / 8192 字节`;
  }

  counter.textContent = label;
  counter.classList.toggle("is-over", bytes > 8192);
}

function showEntryError(message) {
  const node = $("entry-error");
  if (!message) {
    node.hidden = true;
    node.textContent = "";
    return;
  }
  node.hidden = false;
  node.textContent = message;
}

function showCreateError(message) {
  const node = $("create-error");
  if (!message) {
    node.hidden = true;
    node.textContent = "";
    return;
  }
  node.hidden = false;
  node.textContent = message;
}

async function submitEntry(event) {
  event.preventDefault();
  if (state.entryBusy) return;
  if (!isOnline()) {
    showEntryError("PowerContext 服务不可用，保存已禁用。请先恢复服务并重新检测。");
    return;
  }

  showEntryError("");
  const type = getEntryType();
  const note = $("entry-note").value;
  let payload;

  if (type === "link") {
    const url = $("link-url").value.trim();
    if (!url) {
      showEntryError("请填写资料链接。");
      $("link-url").focus();
      return;
    }
    try {
      const parsed = new URL(url);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
        throw new Error("protocol");
      }
      if (parsed.username || parsed.password) {
        showEntryError("资料链接不能包含用户名或密码。");
        $("link-url").focus();
        return;
      }
    } catch {
      showEntryError("资料链接必须是有效的 http 或 https URL。");
      $("link-url").focus();
      return;
    }
    payload = {
      type,
      title: $("link-title").value,
      url,
      note,
    };
  } else {
    const text = $("entry-text").value.trim();
    if (!text) {
      showEntryError("请填写记录内容。");
      $("entry-text").focus();
      return;
    }
    payload = { type, text, note };
  }

  updateCharCount();
  if (byteLength(JSON.stringify(payload)) > 20000) {
    showEntryError("记录过长，请缩短后再保存。");
    return;
  }

  state.entryBusy = true;
  setBusy($("entry-submit"), true, "写入中…");
  try {
    const result = await api(`/api/tasks/${encodeURIComponent(state.activeId)}/entries`, {
      method: "POST",
      body: payload,
    });
    toast("已写入 PowerContext Memory。", "success");
    if (result.warning) toast(result.warning, "warning", 7000);
    resetEntryForm();
    state.search = null;
    state.handoff = null;
    resetSearchPanel();
    resetHandoffPanel();
    await loadDetail(state.activeId, { quiet: true });
    activateTab("timeline", { silent: true });
  } catch (error) {
    showEntryError(error.message);
    handleApiError(error);
  } finally {
    state.entryBusy = false;
    setBusy($("entry-submit"), false);
  }
}

function resetSearchPanel() {
  $("search-query").value = "";
  $("search-meta").replaceChildren();
  $("search-results").replaceChildren(
    el("div", {
      class: "search-placeholder",
      text: "输入关键词后，PowerContext 会在当前任务的 Scope 内执行检索。",
    }),
  );
}

function renderSearchLoading(query) {
  $("search-meta").replaceChildren(
    el("span", { class: "result-meta" }, "正在调用 ", el("strong", { text: "PowerContext /v1/memory/search" }), "…"),
  );
  $("search-results").replaceChildren(
    el(
      "div",
      { class: "result-card" },
      el("div", { class: "skeleton skeleton-line short" }),
      el("div", { class: "skeleton skeleton-line" }),
      el("div", { class: "skeleton skeleton-line wide" }),
    ),
  );
  $("search-query").value = query;
}

function highlightFragment(text, query) {
  const fragment = document.createDocumentFragment();
  if (!query) {
    fragment.append(document.createTextNode(String(text ?? "")));
    return fragment;
  }
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const regex = new RegExp(`(${escaped})`, "gi");
  let lastIndex = 0;
  let match;
  const source = String(text ?? "");
  while ((match = regex.exec(source)) !== null) {
    if (match.index > lastIndex) {
      fragment.append(document.createTextNode(source.slice(lastIndex, match.index)));
    }
    const mark = el("mark", { text: match[0] });
    fragment.append(mark);
    lastIndex = match.index + match[0].length;
    if (match[0].length === 0) regex.lastIndex += 1;
  }
  if (lastIndex < source.length) {
    fragment.append(document.createTextNode(source.slice(lastIndex)));
  }
  return fragment;
}

function renderSearchResults(data) {
  const meta = $("search-meta");
  const results = $("search-results");
  meta.replaceChildren(
    el("span", { class: "source-pill", text: data.engine || "PowerContext" }),
    el(
      "span",
      { class: "result-meta" },
      `模式：${data.mode || "未报告"} · 结果 `,
      el("strong", { text: String(data.hits?.length ?? 0) }),
      " 条",
    ),
  );
  if (data.warning) {
    meta.append(el("span", { class: "result-meta", text: data.warning }));
  }

  results.replaceChildren();
  if (!data.hits || data.hits.length === 0) {
    results.append(
      el("div", {
        class: "search-placeholder",
        text: "PowerContext 未检索到匹配内容。可以换一个关键词，或先补充研究记录。",
      }),
    );
    return;
  }

  for (const hit of data.hits) {
    const metaInfo = TYPE_META[hit.type] || TYPE_META.other;
    const card = el("article", {
      class: "result-card type-" + (TYPE_META[hit.type] ? hit.type : "other"),
    });
    const progress = el("progress", {
      max: 100,
      value: hit.score === null ? 0 : Math.round(hit.score * 100),
    });
    const head = el(
      "div",
      { class: "result-head" },
      el(
        "span",
        { class: "type-badge badge-" + (TYPE_META[hit.type] ? hit.type : "other") },
        el("span", { class: "badge-dot", "aria-hidden": "true" }),
        metaInfo.label,
      ),
      hit.createdAt
        ? el("time", { class: "entry-time", datetime: hit.createdAt, text: formatTime(hit.createdAt) })
        : null,
      el(
        "span",
        { class: "result-score" },
        hit.score === null ? "score —" : `score ${(hit.score * 100).toFixed(0)}%`,
        progress,
      ),
    );
    const text = el("p", { class: "result-text" });
    text.append(highlightFragment(hit.text, data.query));
    const footer = el("div", { class: "result-footer" });
    for (const matchedBy of hit.matchedBy || []) {
      footer.append(
        el("span", { class: "match-chip", text: MATCH_LABELS[matchedBy] || matchedBy }),
      );
    }
    renderCitationChips(footer, hit.citation, null);
    if (hit.citation) {
      const copy = el("button", { class: "cite-copy", type: "button", text: "复制引用" });
      copy.addEventListener("click", () => {
        const parts = citationParts(hit.citation);
        copyText(
          `PowerContext memory ${parts.artifactId}@r${parts.artifactRevision}; entry ${parts.entryId}; entry_version ${parts.entryVersionId}; scope ${state.activeId}`,
          "引用已复制",
        );
      });
      footer.append(copy);
    }
    card.append(head, text, footer);
    results.append(card);
  }
}

async function submitSearch(event) {
  event.preventDefault();
  if (state.searchLoading) return;
  if (!isOnline()) {
    toast("PowerContext 服务不可用，搜索已禁用。", "danger");
    return;
  }
  const query = $("search-query").value.trim();
  if (!query) {
    $("search-query").focus();
    return;
  }

  state.searchLoading = true;
  setBusy($("search-submit"), true, "搜索中…");
  renderSearchLoading(query);
  try {
    const data = await api(`/api/tasks/${encodeURIComponent(state.activeId)}/search`, {
      method: "POST",
      body: { query },
    });
    state.search = data;
    renderSearchResults(data);
  } catch (error) {
    state.search = null;
    $("search-meta").replaceChildren();
    $("search-results").replaceChildren(
      el("div", { class: "search-placeholder", text: error.message }),
    );
    handleApiError(error);
  } finally {
    state.searchLoading = false;
    setBusy($("search-submit"), false);
  }
}

function resetHandoffPanel() {
  state.handoff = null;
  $("handoff-meta").replaceChildren();
  $("handoff-warnings").replaceChildren();
  $("handoff-output-wrap").hidden = true;
  $("handoff-output").textContent = "";
  $("handoff-empty").hidden = false;
  $("handoff-empty").textContent = "点击“生成交接摘要”，从 PowerContext 读取最新进展。";
}

function renderHandoffLoading() {
  $("handoff-empty").hidden = false;
  $("handoff-empty").textContent = "正在从 PowerContext 读取 Memory、Source 与准备上下文…";
  $("handoff-meta").replaceChildren(
    el("span", { class: "source-pill", text: "PowerContext HTTP API" }),
    el("span", { class: "result-meta", text: "生成中…" }),
  );
  $("handoff-warnings").replaceChildren();
  $("handoff-output-wrap").hidden = true;
}

function renderHandoff(data) {
  state.handoff = data;
  const preparedStatus = data.prepared?.status || "unknown";
  $("handoff-meta").replaceChildren(
    el("span", { class: "source-pill", text: data.engine || "PowerContext HTTP API" }),
    el("span", { class: "meta-chip", text: `生成于 ${formatDateTime(data.generatedAt)}` }),
    el("span", { class: "meta-chip", text: `准备上下文：${preparedStatus}` }),
    el("span", { class: "meta-chip", text: `记忆引用 ${data.citations?.memories?.length ?? 0}` }),
    el("span", { class: "meta-chip", text: `Source 证据 ${data.citations?.sources?.length ?? 0}` }),
  );

  const warnings = [...(data.warnings || [])];
  if (data.prepared?.status === "error" && data.prepared?.message && !warnings.includes(data.prepared.message)) {
    warnings.push(data.prepared.message);
  }
  $("handoff-warnings").replaceChildren(
    ...warnings.map((warning) => el("div", { class: "warning-item", text: warning })),
  );

  $("handoff-empty").hidden = true;
  $("handoff-output").textContent = data.markdown || "";
  $("handoff-output-wrap").hidden = false;
}

async function generateHandoff({ auto = false } = {}) {
  if (state.handoffLoading) return;
  if (!isOnline()) {
    toast("PowerContext 服务不可用，无法生成交接摘要。", "danger");
    return;
  }
  state.handoffLoading = true;
  setBusy($("handoff-generate"), true, "生成中…");
  renderHandoffLoading();
  try {
    const data = await api(`/api/tasks/${encodeURIComponent(state.activeId)}/handoff`);
    renderHandoff(data);
    if (!auto) toast("交接摘要已生成。", "success");
  } catch (error) {
    state.handoff = null;
    $("handoff-meta").replaceChildren();
    $("handoff-warnings").replaceChildren(
      el("div", { class: "warning-item", text: error.message }),
    );
    $("handoff-empty").hidden = false;
    $("handoff-empty").textContent = "交接摘要生成失败。";
    $("handoff-output-wrap").hidden = true;
    handleApiError(error);
  } finally {
    state.handoffLoading = false;
    setBusy($("handoff-generate"), false);
  }
}

function downloadHandoff() {
  if (!state.handoff?.markdown) return;
  const rawTitle = state.detail?.task?.title || "research-handoff";
  const safeTitle =
    rawTitle
      .replace(/[\\/:*?"<>|\s]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || "research-handoff";
  const filename = `${safeTitle}-handoff-${new Date().toISOString().slice(0, 10)}.md`;
  const blob = new Blob([state.handoff.markdown], {
    type: "text/markdown;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function activateTab(tab, { silent = false } = {}) {
  state.activeTab = tab;
  document.querySelectorAll(".tab").forEach((button) => {
    const active = button.dataset.tab === tab;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  for (const name of ["timeline", "search", "handoff"]) {
    const panel = $(`panel-${name}`);
    if (panel) panel.hidden = name !== tab;
  }

  if (tab === "search" && !silent) {
    window.setTimeout(() => $("search-query").focus(), 30);
  }
  if (
    tab === "handoff" &&
    !silent &&
    state.detail &&
    !state.handoff &&
    !state.handoffLoading
  ) {
    generateHandoff({ auto: true });
  }
}

function openCreateDialog() {
  if (!isOnline()) {
    toast("PowerContext 服务不可用，暂时无法创建研究任务。", "danger");
    return;
  }
  $("create-form").reset();
  showCreateError("");
  const dialog = $("create-dialog");
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
  window.setTimeout(() => $("create-title").focus(), 40);
}

function closeCreateDialog() {
  const dialog = $("create-dialog");
  if (typeof dialog.close === "function") dialog.close();
  else dialog.removeAttribute("open");
}

async function submitCreateTask(event) {
  event.preventDefault();
  if (state.creating) return;
  if (!isOnline()) {
    showCreateError("PowerContext 服务不可用，创建已禁用。");
    return;
  }
  const title = $("create-title").value.trim();
  const summary = $("create-summary").value.trim();
  if (!title) {
    showCreateError("请填写研究任务名称。");
    $("create-title").focus();
    return;
  }

  showCreateError("");
  state.creating = true;
  setBusy($("create-submit"), true, "创建中…");
  try {
    const result = await api("/api/tasks", {
      method: "POST",
      body: {
        title,
        summary,
        idempotencyKey: crypto.randomUUID(),
      },
    });
    closeCreateDialog();
    toast("研究任务已创建，Scope 已写入 PowerContext。", "success");
    await loadTasks({ selectId: result.task.id, replaceHash: true });
  } catch (error) {
    showCreateError(error.message);
    handleApiError(error);
  } finally {
    state.creating = false;
    setBusy($("create-submit"), false, null, "创建任务");
  }
}

function handleApiError(error) {
  if (!error) return;
  if (error.name === "AbortError") return;

  if (
    error.code === "powercontext_unavailable" ||
    error.code === "powercontext_auth_failed" ||
    error.code === "app_unreachable" ||
    error.status === 503
  ) {
    toast(error.message, "danger", 6500);
    refreshHealth({ silent: true });
  }

  if (error.status === 404 && error.code === "task_not_found") {
    toast("该研究任务不存在或不属于实验续航。", "warning");
    loadTasks();
  }
}

async function retryConnection() {
  const data = await refreshHealth({ silent: false });
  if (data?.powercontext?.online) {
    toast("PowerContext 已连接。", "success");
    await loadTasks({ keepSelection: true });
    if (state.activeId) await loadDetail(state.activeId, { quiet: true });
  } else {
    toast("仍无法连接 PowerContext，请检查服务是否已启动。", "danger", 6000);
  }
}

function bindEvents() {
  $("health-chip").addEventListener("click", retryConnection);
  $("banner-retry").addEventListener("click", retryConnection);
  $("service-retry").addEventListener("click", retryConnection);
  $("new-task-btn").addEventListener("click", openCreateDialog);
  $("empty-create").addEventListener("click", openCreateDialog);

  $("create-form").addEventListener("submit", submitCreateTask);
  $("create-cancel").addEventListener("click", closeCreateDialog);
  $("create-close").addEventListener("click", closeCreateDialog);
  $("create-dialog").addEventListener("click", (event) => {
    if (event.target === $("create-dialog")) closeCreateDialog();
  });

  document.querySelectorAll('input[name="entry-type"]').forEach((input) => {
    input.addEventListener("change", syncEntryForm);
  });
  for (const id of ["entry-text", "entry-note", "link-title", "link-url"]) {
    $(id).addEventListener("input", updateCharCount);
  }
  $("entry-form").addEventListener("submit", submitEntry);
  $("entry-form").addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      $("entry-form").requestSubmit();
    }
  });

  $("refresh-detail").addEventListener("click", () => {
    if (state.activeId) loadDetail(state.activeId);
  });

  $("search-form").addEventListener("submit", submitSearch);
  $("handoff-generate").addEventListener("click", () => generateHandoff());
  $("handoff-copy").addEventListener("click", () => {
    if (state.handoff?.markdown) copyText(state.handoff.markdown, "交接摘要已复制");
  });
  $("handoff-download").addEventListener("click", downloadHandoff);
  $("copy-scope").addEventListener("click", () => {
    if (state.detail?.task?.id) copyText(state.detail.task.id, "Scope ID 已复制");
  });

  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => activateTab(button.dataset.tab));
    button.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      const tabs = [...document.querySelectorAll(".tab")];
      const index = tabs.indexOf(button);
      const next = event.key === "ArrowRight"
        ? (index + 1) % tabs.length
        : (index - 1 + tabs.length) % tabs.length;
      tabs[next].focus();
      activateTab(tabs[next].dataset.tab);
    });
  });

  window.addEventListener("popstate", () => {
    const taskId = readHashTaskId();
    if (taskId && state.tasks.some((task) => task.id === taskId)) {
      if (taskId !== state.activeId) selectTask(taskId, { updateHash: false });
      return;
    }
    if (state.tasks.length > 0) {
      selectTask(state.tasks[0].id, { updateHash: false });
      writeHash(state.tasks[0].id, { replace: true });
    } else {
      showEmptyWorkspace();
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      refreshHealth({ silent: true });
    }
  });
}

async function init() {
  bindEvents();
  syncEntryForm();
  resetSearchPanel();
  resetHandoffPanel();
  updateAvailability();

  const health = await refreshHealth({ silent: true });
  if (health?.powercontext?.online) {
    await loadTasks();
  } else {
    showStatusError(
      "PowerContext 服务不可用",
      "无法从 PowerContext 读取研究任务。本应用不保存本地 JSON，也不提供模拟后端。",
      retryConnection,
    );
  }

  window.setInterval(() => {
    if (document.visibilityState === "visible") {
      refreshHealth({ silent: true });
    }
  }, 30000);
}

init();
