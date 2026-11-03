import { randomUUID } from "node:crypto";

export const APP_NAME = "实验续航 / Research Relay";
export const APP_VERSION = "1.0.0";
export const TITLE_PREFIX = "[实验续航]";
export const EXTERNAL_REF_KIND = "research-relay";
export const KIND_ROOT = "research-relay";
export const MAX_ENTRY_BYTES = 8192;
export const SUMMARY_SUFFIX =
  "\n\n研究进展由「实验续航 / Research Relay」通过 PowerContext 保存。";

export const ENTRY_TYPES = Object.freeze({
  observation: {
    label: "实验观察",
    short: "观察",
    description: "测量、现象、异常与实验条件",
  },
  decision: {
    label: "研究决策",
    short: "决策",
    description: "取舍、依据与影响范围",
  },
  todo: {
    label: "下一步待办",
    short: "待办",
    description: "可执行的下一个研究动作",
  },
  link: {
    label: "原始资料",
    short: "资料",
    description: "外部链接、文档与来源说明",
  },
});

export const ENTRY_TYPE_KEYS = Object.freeze(Object.keys(ENTRY_TYPES));

export class ValidationError extends Error {
  constructor(message, details = null) {
    super(message);
    this.name = "ValidationError";
    this.status = 422;
    this.code = "invalid_request";
    this.details = details;
  }
}

export function sanitizeText(value) {
  if (typeof value !== "string") return "";
  return value
    .replace(/\r\n?/g, "\n")
    .replace(/\u0000/g, "")
    .replace(/[\u0001-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "");
}

export function stringLength(value) {
  return [...String(value ?? "")].length;
}

export function utf8Bytes(value) {
  return Buffer.byteLength(String(value ?? ""), "utf8");
}

function assertByteLimit(text) {
  const bytes = utf8Bytes(text);
  if (bytes > MAX_ENTRY_BYTES) {
    throw new ValidationError(
      `单条记录超过 PowerContext Memory 的 ${MAX_ENTRY_BYTES} 字节上限。`,
      { bytes, maxBytes: MAX_ENTRY_BYTES },
    );
  }
}

export function validateTaskInput(input) {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    throw new ValidationError("请求体必须是 JSON 对象。");
  }

  const title = sanitizeText(input.title).trim();
  if (!title) throw new ValidationError("请填写研究任务名称。");
  if (stringLength(title) > 120) {
    throw new ValidationError("研究任务名称不能超过 120 个字符。");
  }

  const summary =
    sanitizeText(input.summary).trim() || "尚未补充研究摘要。";
  if (stringLength(summary) > 1500) {
    throw new ValidationError("研究摘要不能超过 1500 个字符。");
  }

  let idempotencyKey = null;
  if (input.idempotencyKey !== undefined && input.idempotencyKey !== null) {
    if (typeof input.idempotencyKey !== "string") {
      throw new ValidationError("idempotencyKey 必须是字符串。");
    }
    idempotencyKey = sanitizeText(input.idempotencyKey).trim();
    if (!idempotencyKey || stringLength(idempotencyKey) > 256) {
      throw new ValidationError("idempotencyKey 长度必须在 1 到 256 之间。");
    }
  }

  return { title, summary, idempotencyKey };
}

export function validateScopeId(value) {
  if (typeof value !== "string") {
    throw new ValidationError("Scope ID 无效。");
  }
  const scopeId = value.trim();
  if (
    !scopeId ||
    stringLength(scopeId) > 256 ||
    scopeId.includes("/") ||
    /[\u0000-\u001F]/.test(scopeId)
  ) {
    throw new ValidationError("Scope ID 无效。");
  }
  return scopeId;
}

export function validateHttpUrl(raw) {
  const value = sanitizeText(raw).trim();
  if (!value) throw new ValidationError("请填写资料链接。");
  if (stringLength(value) > 2048) {
    throw new ValidationError("资料链接不能超过 2048 个字符。");
  }

  let url;
  try {
    url = new URL(value);
  } catch {
    throw new ValidationError("资料链接不是有效的 URL。");
  }

  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new ValidationError("资料链接只支持 http 或 https。");
  }
  if (url.username || url.password) {
    throw new ValidationError("资料链接不能包含用户名或密码。");
  }
  if (!url.hostname) {
    throw new ValidationError("资料链接缺少主机名。");
  }
  return url.toString();
}

export function buildLinkText({ title, url, note }) {
  const lines = [];
  if (title && title !== url) {
    lines.push(`资料标题：${title}`);
  }
  lines.push(`资料链接：${url}`);
  if (note) {
    lines.push("", `补充说明：${note}`);
  }
  return lines.join("\n");
}

export function validateEntryInput(input) {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    throw new ValidationError("请求体必须是 JSON 对象。");
  }

  const type = sanitizeText(input.type).trim();
  if (!ENTRY_TYPE_KEYS.includes(type)) {
    throw new ValidationError("记录类型必须是 observation、decision、todo 或 link。");
  }

  const note = sanitizeText(input.note).trim();
  if (stringLength(note) > 2000) {
    throw new ValidationError("补充说明不能超过 2000 个字符。");
  }

  if (type === "link") {
    const url = validateHttpUrl(input.url);
    const title = sanitizeText(input.title).trim() || url;
    if (stringLength(title) > 200) {
      throw new ValidationError("资料标题不能超过 200 个字符。");
    }
    const text = buildLinkText({ title, url, note });
    assertByteLimit(text);
    return { type, title, url, note, text };
  }

  const text = sanitizeText(input.text).trim();
  if (!text) throw new ValidationError("记录内容不能为空。");
  const body = note ? `${text}\n\n补充说明：${note}` : text;
  assertByteLimit(body);
  return { type, text: body, note };
}

export function buildEntryKind(type, at = new Date()) {
  if (!ENTRY_TYPE_KEYS.includes(type)) {
    throw new ValidationError("无法为未知类型生成 Memory kind。");
  }
  const kind = `${KIND_ROOT}/${type}/${at.toISOString()}`;
  if (kind.length > 128) {
    throw new ValidationError("生成的 Memory kind 超出 128 字符限制。");
  }
  return kind;
}

export function parseEntryKind(kind) {
  const match = /^research-relay\/(observation|decision|todo|link)\/(.+)$/.exec(
    String(kind || ""),
  );
  if (!match) {
    return {
      recognized: false,
      type: "other",
      label: "其他记录",
      createdAt: null,
    };
  }
  const parsed = new Date(match[2]);
  return {
    recognized: true,
    type: match[1],
    label: ENTRY_TYPES[match[1]].label,
    createdAt: Number.isNaN(parsed.getTime()) ? null : parsed.toISOString(),
  };
}

export function buildScopePayload({ title, summary, idempotencyKey, now = new Date() }) {
  const taskRef = {
    kind: EXTERNAL_REF_KIND,
    value: `${now.toISOString()}|${randomUUID()}`,
  };

  return {
    title: `${TITLE_PREFIX} ${title}`,
    summary: `${summary}${SUMMARY_SUFFIX}`,
    external_references: [taskRef],
    idempotency_key: idempotencyKey || `research-relay-${randomUUID()}`,
  };
}

function extractCreatedAt(scope) {
  const references = Array.isArray(scope?.external_references)
    ? scope.external_references
    : [];
  const ref = references.find((item) => item?.kind === EXTERNAL_REF_KIND);
  if (!ref || typeof ref.value !== "string") {
    return { createdAt: null, externalRef: null };
  }
  const timestamp = ref.value.split("|")[0];
  const parsed = new Date(timestamp);
  return {
    createdAt: Number.isNaN(parsed.getTime()) ? null : parsed.toISOString(),
    externalRef: ref.value,
  };
}

export function isResearchScope(scope) {
  return Boolean(
    scope &&
      typeof scope.scope_id === "string" &&
      scope.scope_id.length > 0 &&
      typeof scope.title === "string" &&
      scope.title.startsWith(TITLE_PREFIX),
  );
}

export function taskFromScope(scope) {
  const fullTitle = typeof scope?.title === "string" ? scope.title : "";
  let title = fullTitle.startsWith(TITLE_PREFIX)
    ? fullTitle.slice(TITLE_PREFIX.length).trim()
    : fullTitle.trim();

  let summary = typeof scope?.summary === "string" ? scope.summary : "";
  if (summary.endsWith(SUMMARY_SUFFIX)) {
    summary = summary.slice(0, -SUMMARY_SUFFIX.length).trim();
  }

  const { createdAt, externalRef } = extractCreatedAt(scope);

  return {
    id: scope?.scope_id,
    title: title || "未命名研究任务",
    fullTitle,
    summary: summary || "尚未补充研究摘要。",
    version: Number.isInteger(scope?.version) ? scope.version : null,
    parentScopeId: scope?.parent_scope_id ?? null,
    createdAt,
    externalRef,
  };
}

export function sortTasks(tasks) {
  return [...tasks].sort((a, b) => {
    if (a.createdAt && b.createdAt) {
      return b.createdAt.localeCompare(a.createdAt);
    }
    if (a.createdAt) return -1;
    if (b.createdAt) return 1;
    return String(a.title).localeCompare(String(b.title), "zh-CN");
  });
}

export function normalizeEntry(entry, source = null) {
  const citation = entry?.citation ?? null;
  const memoryRef = citation?.memory_ref ?? null;
  const kindInfo = parseEntryKind(entry?.kind);
  const sourceRefs = Array.isArray(entry?.source_refs) ? entry.source_refs : [];

  return {
    id: citation?.entry_id ?? null,
    version: Number.isInteger(entry?.version) ? entry.version : null,
    kind: entry?.kind ?? "",
    type: kindInfo.type,
    typeLabel: kindInfo.label,
    createdAt: kindInfo.createdAt,
    text: typeof entry?.text === "string" ? entry.text : "",
    state: entry?.state ?? "active",
    citation: citation
      ? {
          artifactId: memoryRef?.artifact_id ?? null,
          artifactRevision: memoryRef?.revision ?? null,
          entryId: citation.entry_id ?? null,
          entryVersionId: citation.entry_version_id ?? null,
        }
      : null,
    sourceRefs,
    source: source
      ? {
          sourceId: source.sourceId,
          position: source.position ?? null,
          digest: source.digest ?? null,
          contentPreview: source.contentPreview ?? "",
        }
      : null,
  };
}

export function sortEntriesNewestFirst(entries) {
  return [...entries].sort((a, b) => {
    if (a.createdAt && b.createdAt) {
      return b.createdAt.localeCompare(a.createdAt);
    }
    if (a.createdAt) return -1;
    if (b.createdAt) return 1;
    return (b.version ?? 0) - (a.version ?? 0);
  });
}

export function computeStats(entries) {
  const stats = {
    total: 0,
    observation: 0,
    decision: 0,
    todo: 0,
    link: 0,
    other: 0,
    latestAt: null,
  };

  for (const entry of entries) {
    stats.total += 1;
    if (Object.hasOwn(stats, entry.type)) {
      stats[entry.type] += 1;
    } else {
      stats.other += 1;
    }
    if (
      entry.createdAt &&
      (!stats.latestAt || entry.createdAt > stats.latestAt)
    ) {
      stats.latestAt = entry.createdAt;
    }
  }
  return stats;
}

export function buildPreparedQuery(task) {
  return [
    task?.title,
    "研究交接 当前进展 关键决策 实验观察 待办 原始资料 下一步",
  ]
    .filter(Boolean)
    .join(" ");
}
