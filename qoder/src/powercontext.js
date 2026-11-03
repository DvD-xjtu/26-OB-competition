import { AppError } from "./errors.js";

const PROBE_STATUSES = [200, 204, 400, 401, 403, 404, 405, 409, 410, 413, 422, 500, 503];

export class PowerContextError extends AppError {
  constructor(message, { status = 502, code = "powercontext_error", details = null, requestId = null } = {}) {
    super(status, code, message, details);
    this.requestId = requestId;
  }
}

export class PowerContextUnavailableError extends PowerContextError {
  constructor(message, options = {}) {
    super(message, {
      ...options,
      status: 503,
      code: "powercontext_unavailable",
      details: {
        noLocalFallback: true,
        ...(options.details || {}),
      },
    });
  }
}

export class PowerContextAuthError extends PowerContextError {
  constructor(message, options = {}) {
    super(message, {
      ...options,
      status: 502,
      code: "powercontext_auth_failed",
    });
  }
}

export class PowerContextHttpError extends PowerContextError {
  constructor(message, options = {}) {
    super(message, options);
    this.pcStatus = options.pcStatus ?? null;
  }
}

function parseBody(text) {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function extractEnvelope(data) {
  if (
    data &&
    typeof data === "object" &&
    data.error &&
    typeof data.error === "object"
  ) {
    return data.error;
  }
  return null;
}

function mapHttpStatus(pcStatus) {
  if (pcStatus === 404) return 404;
  if (pcStatus === 409) return 409;
  if (pcStatus === 413) return 413;
  if (pcStatus === 422) return 422;
  return 502;
}

export class PowerContextClient {
  constructor({ baseUrl, token = null, timeoutMs = 8000, fetchImpl = globalThis.fetch }) {
    if (!baseUrl) throw new Error("PowerContext baseUrl is required.");
    if (typeof fetchImpl !== "function") {
      throw new Error("A fetch implementation is required.");
    }
    this.baseUrl = String(baseUrl).replace(/\/+$/, "");
    this.token = token || null;
    this.timeoutMs = timeoutMs;
    this.fetchImpl = fetchImpl;
  }

  get hasToken() {
    return Boolean(this.token);
  }

  buildUrl(path, query) {
    const suffix = path.startsWith("/") ? path : `/${path}`;
    const url = new URL(`${this.baseUrl}${suffix}`);
    if (query) {
      for (const [key, value] of Object.entries(query)) {
        if (value !== undefined && value !== null && value !== "") {
          url.searchParams.set(key, String(value));
        }
      }
    }
    return url;
  }

  async request(path, { method = "GET", body, query, allowStatuses = [], timeoutMs } = {}) {
    const url = this.buildUrl(path, query);
    const headers = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (this.token) headers.Authorization = `Bearer ${this.token}`;

    let response;
    try {
      response = await this.fetchImpl(url, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        redirect: "error",
        signal: AbortSignal.timeout(timeoutMs ?? this.timeoutMs),
      });
    } catch (error) {
      const isTimeout =
        error?.name === "TimeoutError" || error?.name === "AbortError";
      const cause = error?.cause?.code || error?.code || error?.name || "network_error";
      const message = isTimeout
        ? `连接 PowerContext 超时（${this.baseUrl}）。本应用不会使用本地 JSON 或模拟数据替代。`
        : `无法连接 PowerContext（${this.baseUrl}）。本应用不会使用本地 JSON 或模拟数据替代。`;
      throw new PowerContextUnavailableError(message, {
        details: {
          endpoint: this.baseUrl,
          cause,
          noLocalFallback: true,
        },
      });
    }

    const requestId =
      response.headers.get("x-powercontext-request-id") || null;
    let data = null;
    try {
      data = parseBody(await response.text());
    } catch (error) {
      throw new PowerContextHttpError("读取 PowerContext 响应失败。", {
        status: 502,
        code: "powercontext_bad_response",
        requestId,
        details: { endpoint: this.baseUrl, cause: error.name },
      });
    }

    if (!response.ok && !allowStatuses.includes(response.status)) {
      const envelope = extractEnvelope(data);
      const pcMessage =
        envelope?.message || `PowerContext 返回 HTTP ${response.status}。`;
      const details = {
        endpoint: this.baseUrl,
        httpStatus: response.status,
        pcRequestId: requestId,
        pcError: envelope ?? (typeof data === "string" ? data.slice(0, 2000) : data),
      };

      if (response.status === 401 || response.status === 403) {
        throw new PowerContextAuthError(
          "PowerContext 拒绝访问，请检查服务端 Bearer 令牌配置。",
          { details, requestId },
        );
      }
      if (response.status === 503) {
        throw new PowerContextUnavailableError(
          "PowerContext 服务暂不可用（HTTP 503）。本应用不会使用本地 JSON 或模拟数据替代。",
          { details, requestId },
        );
      }

      throw new PowerContextHttpError(pcMessage, {
        status: mapHttpStatus(response.status),
        code:
          envelope?.details?.code ||
          envelope?.code ||
          `powercontext_http_${response.status}`,
        details,
        requestId,
        pcStatus: response.status,
      });
    }

    return {
      status: response.status,
      ok: response.ok,
      data,
      requestId,
    };
  }

  async probe(path) {
    try {
      const result = await this.request(path, { allowStatuses: PROBE_STATUSES });
      return {
        ok: result.status >= 200 && result.status < 300,
        httpStatus: result.status,
        data: result.data,
        requestId: result.requestId,
      };
    } catch (error) {
      return {
        ok: false,
        httpStatus: error.status ?? 0,
        data: error.details ?? null,
        requestId: error.requestId ?? null,
        message: error.message,
        code: error.code,
      };
    }
  }

  async listScopes({ query, queryField = "title", limit = 100, cursor } = {}) {
    return this.request("/v1/scopes", {
      query: { query, query_field: queryField, limit, cursor },
    });
  }

  async createScope(payload) {
    return this.request("/v1/scopes", { method: "POST", body: payload });
  }

  async getScope(scopeId) {
    return this.request(`/v1/scopes/${encodeURIComponent(scopeId)}`);
  }

  async remember(payload) {
    return this.request("/v1/memory/remember", {
      method: "POST",
      body: payload,
    });
  }

  async listEntries(scopeId) {
    const result = await this.request("/v1/memory/entries/list", {
      method: "POST",
      body: { scope_id: scopeId, include_inactive: false },
      allowStatuses: [404],
    });
    if (result.status === 404) {
      return { entries: [], memory: null, requestId: result.requestId };
    }
    return {
      entries: Array.isArray(result.data?.entries) ? result.data.entries : [],
      memory: result.data?.memory ?? null,
      requestId: result.requestId,
    };
  }

  async search(payload) {
    return this.request("/v1/memory/search", {
      method: "POST",
      body: payload,
    });
  }

  async prepareContext(payload) {
    return this.request("/v1/context/prepare", {
      method: "POST",
      body: payload,
    });
  }

  async captureSource(payload) {
    return this.request("/v1/sources/content", {
      method: "POST",
      body: payload,
    });
  }

  async listSources(scopeId, { limit = 100, cursor } = {}) {
    const result = await this.request(
      `/v1/scopes/${encodeURIComponent(scopeId)}/sources`,
      { query: { limit, cursor }, allowStatuses: [404] },
    );
    if (result.status === 404) {
      return { items: [], nextCursor: null, requestId: result.requestId };
    }
    return {
      items: Array.isArray(result.data?.items) ? result.data.items : [],
      nextCursor: result.data?.next_cursor ?? null,
      requestId: result.requestId,
    };
  }
}
