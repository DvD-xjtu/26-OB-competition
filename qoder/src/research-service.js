import { randomUUID } from "node:crypto";
import { AppError } from "./errors.js";
import {
  buildEntryKind,
  buildPreparedQuery,
  buildScopePayload,
  computeStats,
  ENTRY_TYPES,
  EXTERNAL_REF_KIND,
  isResearchScope,
  normalizeEntry,
  parseEntryKind,
  sanitizeText,
  sortEntriesNewestFirst,
  sortTasks,
  stringLength,
  taskFromScope,
  validateEntryInput,
  validateScopeId,
  validateTaskInput,
  ValidationError,
} from "./domain.js";
import { composeHandoff } from "./handoff.js";

function oneLine(value) {
  return String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
}

function summarizeProbe(probe) {
  return {
    ok: probe.ok,
    httpStatus: probe.httpStatus,
    requestId: probe.requestId ?? null,
    message: probe.message ?? null,
  };
}

function extractVersion(data) {
  const candidates = [
    data?.version,
    data?.server_version,
    data?.server?.version,
    data?.runtime?.version,
  ];
  return (
    candidates.find(
      (value) => typeof value === "string" && value.trim().length > 0,
    ) ?? null
  );
}

function sourceContentText(content) {
  if (typeof content === "string") {
    try {
      const parsed = JSON.parse(content);
      if (typeof parsed === "string") return parsed;
      if (parsed && typeof parsed === "object") {
        return JSON.stringify(parsed, null, 2);
      }
    } catch {
      return content;
    }
    return content;
  }
  if (content && typeof content === "object") {
    return JSON.stringify(content, null, 2);
  }
  return "";
}

function normalizeSource(record) {
  const content = sourceContentText(record?.content);
  return {
    sourceId: record?.source_id ?? null,
    type: record?.source_type ?? "content",
    position: Number.isInteger(record?.position) ? record.position : null,
    digest: record?.content_digest ?? null,
    content,
    contentPreview: oneLine(content).slice(0, 240),
  };
}

export class ResearchService {
  constructor({ pc, logger = console }) {
    this.pc = pc;
    this.logger = logger;
  }

  async health() {
    const result = {
      status: "offline",
      online: false,
      endpoint: this.pc.baseUrl,
      tokenConfigured: this.pc.hasToken,
      checkedAt: new Date().toISOString(),
      live: null,
      ready: null,
      api: null,
      version: null,
      detail: "",
    };

    const live = await this.pc.probe("/health/live");
    result.live = summarizeProbe(live);
    if (!live.ok) {
      result.detail =
        live.message ||
        `PowerContext /health/live 返回 HTTP ${live.httpStatus}。`;
      return result;
    }

    const ready = await this.pc.probe("/health/ready");
    result.ready = summarizeProbe(ready);
    if (!ready.ok && ready.httpStatus !== 404) {
      result.status = "degraded";
      result.detail =
        ready.message ||
        `PowerContext /health/ready 返回 HTTP ${ready.httpStatus}。`;
      return result;
    }

    const api = await this.pc.probe("/v1/scopes?limit=1");
    result.api = summarizeProbe(api);

    if (api.httpStatus === 401 || api.httpStatus === 403) {
      result.status = "auth-error";
      result.detail = "PowerContext 拒绝访问，请检查服务端 Bearer 令牌配置。";
      return result;
    }
    if (!api.ok) {
      result.status = "degraded";
      result.detail =
        api.message || `PowerContext /v1/scopes 返回 HTTP ${api.httpStatus}。`;
      return result;
    }

    const capabilities = await this.pc.probe("/v1/capabilities");
    result.version = extractVersion(capabilities.data);
    result.status = "online";
    result.online = true;
    result.detail = "已连接 PowerContext HTTP API。";
    return result;
  }

  async listTasks() {
    const fetchScopes = async (query) => {
      const scopes = [];
      let cursor = null;
      let pages = 0;
      do {
        const response = await this.pc.listScopes({
          query,
          queryField: query ? "title" : undefined,
          limit: 100,
          cursor,
        });
        const items = Array.isArray(response.data?.items)
          ? response.data.items
          : [];
        scopes.push(...items);
        cursor = response.data?.next_cursor ?? null;
        pages += 1;
      } while (cursor && pages < 5);
      return scopes;
    };

    let scopes = await fetchScopes("实验续航");
    // 不同检索后端的分词行为可能不同；查不到本应用 Scope 时退回完整列表。
    if (!scopes.some(isResearchScope)) {
      scopes = await fetchScopes(null);
    }

    const seen = new Set();
    const tasks = sortTasks(
      scopes
        .filter(isResearchScope)
        .filter((scope) => {
          if (seen.has(scope.scope_id)) return false;
          seen.add(scope.scope_id);
          return true;
        })
        .map(taskFromScope),
    );

    return {
      tasks,
      engine: "PowerContext /v1/scopes",
      endpoint: this.pc.baseUrl,
    };
  }

  async createTask(input) {
    const { title, summary, idempotencyKey } = validateTaskInput(input);
    const payload = buildScopePayload({ title, summary, idempotencyKey });
    const response = await this.pc.createScope(payload);
    const scope = response.data?.scope ?? response.data;

    if (!scope?.scope_id) {
      throw new AppError(
        502,
        "powercontext_bad_response",
        "PowerContext 创建 Scope 的响应缺少 scope_id。",
      );
    }
    if (!isResearchScope(scope)) {
      throw new AppError(
        502,
        "powercontext_bad_response",
        "PowerContext 返回的 Scope 不属于实验续航。",
      );
    }

    return {
      task: taskFromScope(scope),
      requestId: response.requestId ?? null,
    };
  }

  async getScopeOrThrow(rawScopeId) {
    const scopeId = validateScopeId(rawScopeId);
    let response;
    try {
      response = await this.pc.getScope(scopeId);
    } catch (error) {
      if (error.status === 404) {
        throw new AppError(404, "task_not_found", "未找到该研究任务。");
      }
      throw error;
    }

    const scope = response.data?.scope ?? response.data;
    if (!isResearchScope(scope)) {
      throw new AppError(
        404,
        "task_not_found",
        "该 Scope 不属于实验续航，已拒绝访问。",
      );
    }

    return {
      scope,
      task: taskFromScope(scope),
      scopeId,
      requestId: response.requestId ?? null,
    };
  }

  async listAllSources(scopeId) {
    const items = [];
    const requestIds = [];
    let cursor = null;
    let pages = 0;

    do {
      const page = await this.pc.listSources(scopeId, { limit: 100, cursor });
      items.push(...page.items);
      if (page.requestId) requestIds.push(page.requestId);
      cursor = page.nextCursor;
      pages += 1;
    } while (cursor && pages < 5);

    return {
      sources: items.map(normalizeSource),
      requestIds,
    };
  }

  async getTaskDetail(rawScopeId) {
    const { scope, task, scopeId, requestId } =
      await this.getScopeOrThrow(rawScopeId);

    const [entryResult, sourceResult] = await Promise.all([
      this.pc.listEntries(scopeId),
      this.listAllSources(scopeId),
    ]);

    const sourceByEntryId = new Map();
    for (const source of sourceResult.sources) {
      const match = /^rr-link-(.+)$/.exec(source.sourceId || "");
      if (match) sourceByEntryId.set(match[1], source);
    }

    const entries = sortEntriesNewestFirst(
      entryResult.entries.map((entry) =>
        normalizeEntry(
          entry,
          sourceByEntryId.get(entry?.citation?.entry_id) ?? null,
        ),
      ),
    );

    return {
      scopeId,
      task,
      scope: {
        version: Number.isInteger(scope.version) ? scope.version : null,
        parentScopeId: scope.parent_scope_id ?? null,
      },
      entries,
      sources: sourceResult.sources,
      stats: computeStats(entries),
      fetchedAt: new Date().toISOString(),
      requestIds: [
        requestId,
        entryResult.requestId,
        ...sourceResult.requestIds,
      ].filter(Boolean),
    };
  }

  async addEntry(rawScopeId, input) {
    const { task, scopeId } = await this.getScopeOrThrow(rawScopeId);
    const validated = validateEntryInput(input);
    const kind = buildEntryKind(validated.type);
    const reason = `实验续航 · ${ENTRY_TYPES[validated.type].label} · ${task.title}`.slice(
      0,
      512,
    );

    const response = await this.pc.remember({
      scope_id: scopeId,
      kind,
      text: validated.text,
      reason,
    });

    const requestIds = [response.requestId].filter(Boolean);
    let rawEntry = response.data?.entry ?? null;

    if (!rawEntry) {
      const list = await this.pc.listEntries(scopeId);
      if (list.requestId) requestIds.push(list.requestId);
      rawEntry =
        [...list.entries]
          .filter((entry) => entry?.kind === kind)
          .sort((a, b) => (b.version ?? 0) - (a.version ?? 0))[0] ?? null;
    }

    let entry = rawEntry ? normalizeEntry(rawEntry) : null;
    let source = null;
    let warning = null;

    if (validated.type === "link") {
      const entryId = entry?.citation?.entryId ?? null;
      const sourceId = entryId
        ? `rr-link-${entryId}`
        : `rr-link-${randomUUID()}`;

      try {
        const captured = await this.pc.captureSource({
          scope_id: scopeId,
          source_id: sourceId,
          content: validated.text,
          metadata: {
            origin: EXTERNAL_REF_KIND,
            entry_id: entryId,
            title: validated.title,
            url: validated.url,
            captured_at: new Date().toISOString(),
          },
        });
        if (captured.requestId) requestIds.push(captured.requestId);
        source = {
          sourceId: captured.data?.source?.source_id ?? sourceId,
          position: captured.data?.position ?? null,
          digest: null,
          contentPreview: oneLine(validated.text).slice(0, 240),
        };
        if (entry) entry.source = source;
      } catch (error) {
        warning = `资料已写入 PowerContext Memory，但 Source 取证失败：${error.message}`;
        this.logger.warn?.(
          `[research-relay] source capture failed for scope ${scopeId}: ${error.code || error.name}`,
        );
      }
    }

    if (!entry) {
      const referenceWarning =
        "记录已写入 PowerContext，但未能取回条目引用；刷新时间线即可读取。";
      warning = warning
        ? `${warning} ${referenceWarning}`
        : referenceWarning;
    }

    return {
      entry,
      source,
      warning,
      kind,
      requestIds,
    };
  }

  async searchEntries(rawScopeId, input) {
    const { scopeId } = await this.getScopeOrThrow(rawScopeId);
    const query = sanitizeText(input?.query).trim();
    if (!query) throw new ValidationError("请输入搜索关键词。");
    if (stringLength(query) > 1000) {
      throw new ValidationError("搜索关键词不能超过 1000 个字符。");
    }

    const response = await this.pc.search({
      scope_id: scopeId,
      query,
      limit: 30,
      mode: "auto",
    });

    let entryMap = new Map();
    let warning = null;
    try {
      const listed = await this.pc.listEntries(scopeId);
      for (const entry of listed.entries) {
        const entryId = entry?.citation?.entry_id;
        if (!entryId) continue;
        const previous = entryMap.get(entryId);
        if (!previous || (entry.version ?? 0) > (previous.version ?? 0)) {
          entryMap.set(entryId, entry);
        }
      }
    } catch (error) {
      warning = `搜索已由 PowerContext 完成，但补充条目类型失败：${error.message}`;
    }

    const hits = (Array.isArray(response.data?.hits)
      ? response.data.hits
      : []
    ).map((hit) => {
      const rawEntry = entryMap.get(hit?.citation?.entry_id);
      const kindInfo = parseEntryKind(rawEntry?.kind);
      return {
        text: hit?.text ?? "",
        score: typeof hit?.score === "number" ? hit.score : null,
        matchedBy: Array.isArray(hit?.matched_by) ? hit.matched_by : [],
        citation: hit?.citation ?? null,
        type: kindInfo.type,
        typeLabel: kindInfo.label,
        createdAt: kindInfo.createdAt,
        entryVersion: rawEntry?.version ?? null,
      };
    });

    return {
      query,
      hits,
      mode: response.data?.mode ?? null,
      engine: "PowerContext /v1/memory/search",
      searchedAt: new Date().toISOString(),
      warning,
      requestId: response.requestId ?? null,
    };
  }

  async generateHandoff(rawScopeId) {
    const detail = await this.getTaskDetail(rawScopeId);
    const warnings = [];
    let prepared = {
      status: "error",
      content: null,
      contentBytes: 0,
      message: null,
      requestId: null,
    };

    try {
      const response = await this.pc.prepareContext({
        scope_id: detail.scopeId,
        query: buildPreparedQuery(detail.task),
        max_bytes: 8000,
      });
      const data = response.data ?? {};
      prepared = {
        status: data.status ?? "empty",
        content: data.content ?? null,
        contentBytes: Number.isInteger(data.content_bytes)
          ? data.content_bytes
          : 0,
        message: null,
        requestId: response.requestId ?? null,
      };
    } catch (error) {
      prepared = {
        status: "error",
        content: null,
        contentBytes: 0,
        message: error.message,
        requestId: error.requestId ?? null,
      };
      warnings.push(`PowerContext 准备上下文请求失败：${error.message}`);
    }

    const generatedAt = new Date().toISOString();
    const markdown = composeHandoff({
      task: detail.task,
      entries: detail.entries,
      sources: detail.sources,
      prepared,
      generatedAt,
      baseUrl: this.pc.baseUrl,
      warnings,
    });

    return {
      markdown,
      generatedAt,
      prepared,
      citations: {
        memories: detail.entries
          .map((entry) => entry.citation)
          .filter(Boolean),
        sources: detail.sources.map((source) => ({
          sourceId: source.sourceId,
          position: source.position,
          digest: source.digest,
          contentPreview: source.contentPreview,
        })),
      },
      warnings,
      task: detail.task,
      stats: detail.stats,
      scopeId: detail.scopeId,
      engine: "PowerContext HTTP API",
      requestIds: [
        ...detail.requestIds,
        prepared.requestId,
      ].filter(Boolean),
    };
  }
}
