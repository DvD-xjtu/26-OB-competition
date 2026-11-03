import test from "node:test";
import assert from "node:assert/strict";

import {
  buildEntryKind,
  buildLinkText,
  buildPreparedQuery,
  buildScopePayload,
  computeStats,
  isResearchScope,
  normalizeEntry,
  parseEntryKind,
  sanitizeText,
  sortEntriesNewestFirst,
  sortTasks,
  SUMMARY_SUFFIX,
  taskFromScope,
  TITLE_PREFIX,
  validateEntryInput,
  validateHttpUrl,
  validateScopeId,
  validateTaskInput,
  ValidationError,
} from "../src/domain.js";
import {
  composeHandoff,
  formatChinaTime,
  memoryCitationLabel,
  sourceCitationLabel,
} from "../src/handoff.js";
import { loadConfig } from "../src/config.js";
import {
  PowerContextAuthError,
  PowerContextClient,
  PowerContextUnavailableError,
} from "../src/powercontext.js";

function citation(entryId, version = "v1") {
  return {
    memory_ref: {
      family: "memory",
      artifact_id: "memory-artifact",
      revision: 3,
    },
    entry_id: entryId,
    entry_version_id: version,
  };
}

function makeEntry(overrides = {}) {
  return {
    version: 1,
    kind: "research-relay/observation/2026-01-02T03:04:05.000Z",
    text: "温度 37.2°C，产率 68%。",
    state: "active",
    citation: citation("entry-1"),
    source_refs: [],
    ...overrides,
  };
}

test("sanitizeText 归一化换行并移除控制字符", () => {
  assert.equal(sanitizeText("a\r\nb\rc\u0000d\u0001e"), "a\nb\ncde");
  assert.equal(sanitizeText(undefined), "");
});

test("validateTaskInput 提供默认摘要并保留幂等键", () => {
  const result = validateTaskInput({
    title: "  催化剂筛选  ",
    idempotencyKey: "  task-key  ",
  });
  assert.deepEqual(result, {
    title: "催化剂筛选",
    summary: "尚未补充研究摘要。",
    idempotencyKey: "task-key",
  });
});

test("validateTaskInput 拒绝空标题与超长标题", () => {
  assert.throws(() => validateTaskInput({}), ValidationError);
  assert.throws(
    () => validateTaskInput({ title: "研".repeat(121) }),
    ValidationError,
  );
});

test("validateScopeId 拒绝路径分隔符与控制字符", () => {
  assert.equal(validateScopeId(" scope-1 "), "scope-1");
  assert.throws(() => validateScopeId("a/b"), ValidationError);
  assert.throws(() => validateScopeId("a\u0001b"), ValidationError);
  assert.throws(() => validateScopeId(""), ValidationError);
});

test("validateHttpUrl 只接受无凭据的 http/https 地址", () => {
  assert.equal(
    validateHttpUrl("https://example.com/paper?q=1#part"),
    "https://example.com/paper?q=1#part",
  );
  assert.throws(() => validateHttpUrl("javascript:alert(1)"), ValidationError);
  assert.throws(
    () => validateHttpUrl("https://user:secret@example.com/"),
    ValidationError,
  );
  assert.throws(() => validateHttpUrl("ftp://example.com/"), ValidationError);
});

test("link 记录同时保留标题、链接与说明", () => {
  assert.equal(
    buildLinkText({
      title: "公开数据集",
      url: "https://example.com/data",
      note: "2026-10 快照",
    }),
    "资料标题：公开数据集\n资料链接：https://example.com/data\n\n补充说明：2026-10 快照",
  );

  const validated = validateEntryInput({
    type: "link",
    url: "https://example.com/data",
    note: "说明",
  });
  assert.equal(validated.title, "https://example.com/data");
  assert.match(validated.text, /资料链接：https:\/\/example\.com\/data/);
  assert.match(validated.text, /补充说明：说明/);
});

test("普通记录拼接补充说明并执行 8192 字节上限", () => {
  const validated = validateEntryInput({
    type: "todo",
    text: "补齐重复实验",
    note: "周五前完成",
  });
  assert.equal(validated.text, "补齐重复实验\n\n补充说明：周五前完成");

  assert.throws(
    () => validateEntryInput({ type: "observation", text: "实".repeat(3000) }),
    (error) => error instanceof ValidationError && error.details.bytes > 8192,
  );
});

test("Memory kind 编码类型与 ISO 时间并可往返解析", () => {
  const at = new Date("2026-02-03T04:05:06.000Z");
  const kind = buildEntryKind("decision", at);
  assert.equal(kind, "research-relay/decision/2026-02-03T04:05:06.000Z");
  assert.deepEqual(parseEntryKind(kind), {
    recognized: true,
    type: "decision",
    label: "研究决策",
    createdAt: "2026-02-03T04:05:06.000Z",
  });
  assert.deepEqual(parseEntryKind("other-kind"), {
    recognized: false,
    type: "other",
    label: "其他记录",
    createdAt: null,
  });
});

test("buildScopePayload 带上标题前缀、摘要标记与外部引用", () => {
  const payload = buildScopePayload({
    title: "酶活性复现",
    summary: "验证第三批样本。",
    idempotencyKey: "idem-1",
    now: new Date("2026-03-04T05:06:07.000Z"),
  });

  assert.equal(payload.title, `${TITLE_PREFIX} 酶活性复现`);
  assert.equal(payload.summary, `验证第三批样本。${SUMMARY_SUFFIX}`);
  assert.equal(payload.idempotency_key, "idem-1");
  assert.equal(payload.external_references.length, 1);
  assert.equal(payload.external_references[0].kind, "research-relay");
  assert.match(
    payload.external_references[0].value,
    /^2026-03-04T05:06:07\.000Z\|[0-9a-f-]{36}$/,
  );
});

test("scope 与任务双向映射并恢复创建时间", () => {
  const scope = {
    scope_id: "scope-a",
    title: `${TITLE_PREFIX} 酶活性复现`,
    summary: `验证第三批样本。${SUMMARY_SUFFIX}`,
    version: 4,
    parent_scope_id: null,
    external_references: [
      {
        kind: "research-relay",
        value: "2026-03-04T05:06:07.000Z|ref",
      },
    ],
  };

  assert.equal(isResearchScope(scope), true);
  assert.equal(
    isResearchScope({ scope_id: "x", title: "其他项目" }),
    false,
  );
  const task = taskFromScope(scope);
  assert.equal(task.id, "scope-a");
  assert.equal(task.title, "酶活性复现");
  assert.equal(task.summary, "验证第三批样本。");
  assert.equal(task.createdAt, "2026-03-04T05:06:07.000Z");
  assert.equal(task.version, 4);
});

test("任务按创建时间倒序排列", () => {
  const sorted = sortTasks([
    { id: "b", title: "B", createdAt: "2026-01-02T00:00:00.000Z" },
    { id: "a", title: "A", createdAt: "2026-02-02T00:00:00.000Z" },
    { id: "c", title: "C", createdAt: null },
  ]);
  assert.deepEqual(
    sorted.map((task) => task.id),
    ["a", "b", "c"],
  );
});

test("normalizeEntry 提取引用、类型与 Source 证据", () => {
  const normalized = normalizeEntry(makeEntry(), {
    sourceId: "rr-link-entry-1",
    position: 2,
    digest: "sha256:abc",
    contentPreview: "预览",
  });

  assert.equal(normalized.id, "entry-1");
  assert.equal(normalized.type, "observation");
  assert.equal(normalized.createdAt, "2026-01-02T03:04:05.000Z");
  assert.deepEqual(normalized.citation, {
    artifactId: "memory-artifact",
    artifactRevision: 3,
    entryId: "entry-1",
    entryVersionId: "v1",
  });
  assert.equal(normalized.source.sourceId, "rr-link-entry-1");
  assert.equal(normalized.source.digest, "sha256:abc");
});

test("条目倒序与统计按类型计数", () => {
  const entries = [
    normalizeEntry(
      makeEntry({
        kind: "research-relay/observation/2026-01-01T00:00:00.000Z",
        citation: citation("e1"),
      }),
    ),
    normalizeEntry(
      makeEntry({
        kind: "research-relay/link/2026-01-03T00:00:00.000Z",
        citation: citation("e2"),
      }),
    ),
    normalizeEntry(
      makeEntry({
        kind: "unknown-kind",
        version: 7,
        citation: citation("e3"),
      }),
    ),
  ];

  assert.deepEqual(
    sortEntriesNewestFirst(entries).map((entry) => entry.type),
    ["link", "observation", "other"],
  );

  const stats = computeStats(entries);
  assert.equal(stats.total, 3);
  assert.equal(stats.observation, 1);
  assert.equal(stats.link, 1);
  assert.equal(stats.other, 1);
  assert.equal(stats.latestAt, "2026-01-03T00:00:00.000Z");
});

test("citation 标签包含记忆与 Source 标识", () => {
  const entry = normalizeEntry(makeEntry());
  assert.equal(
    memoryCitationLabel(entry),
    "Memory `memory-artifact@r3` · entry `entry-1` · version `v1`",
  );
  assert.equal(
    sourceCitationLabel({
      sourceId: "rr-link-entry-1",
      position: 2,
      digest: "sha256:abc",
    }),
    "Source `rr-link-entry-1` · position 2 · `sha256:abc`",
  );
});

test("formatChinaTime 输出 UTC+8 时间", () => {
  assert.equal(
    formatChinaTime("2026-01-02T03:04:05.000Z"),
    "2026-01-02 11:04（UTC+8）",
  );
  assert.equal(formatChinaTime(null), "时间未知");
});

test("交接摘要包含决策、引用、Source 与准备上下文", () => {
  const observation = normalizeEntry(
    makeEntry({
      kind: "research-relay/observation/2026-01-02T03:04:05.000Z",
      text: "产率 68%。",
      citation: citation("obs-1"),
    }),
  );
  const decision = normalizeEntry(
    makeEntry({
      kind: "research-relay/decision/2026-01-03T03:04:05.000Z",
      text: "暂停扩大样本量。",
      citation: citation("dec-1"),
    }),
  );
  const link = normalizeEntry(
    makeEntry({
      kind: "research-relay/link/2026-01-04T03:04:05.000Z",
      text: "资料链接：https://example.com/data",
      citation: citation("link-1"),
    }),
    {
      sourceId: "rr-link-link-1",
      position: 1,
      digest: "sha256:feed",
      contentPreview: "资料预览",
    },
  );

  const markdown = composeHandoff({
    task: {
      id: "scope-a",
      title: "酶活性复现",
      summary: "验证第三批样本。",
    },
    entries: [observation, decision, link],
    sources: [
      {
        sourceId: "rr-link-link-1",
        position: 1,
        digest: "sha256:feed",
        contentPreview: "资料预览",
      },
    ],
    prepared: {
      status: "ready",
      content: "历史上下文示例",
    },
    generatedAt: "2026-01-05T00:00:00.000Z",
    baseUrl: "http://127.0.0.1:8000",
    warnings: ["示例提示"],
  });

  assert.match(markdown, /# 实验续航 · 交接摘要/);
  assert.match(markdown, /研究摘要：验证第三批样本。/);
  assert.match(markdown, /记录总数：3 条/);
  assert.match(markdown, /暂停扩大样本量。/);
  assert.match(markdown, /Memory `memory-artifact@r3`/);
  assert.match(markdown, /Source `rr-link-link-1`/);
  assert.match(markdown, /历史上下文示例/);
  assert.match(markdown, /## 生成提示/);
  assert.match(markdown, /本地副本：无/);
  assert.match(markdown, /不可信历史上下文/);
});

test("空任务的交接摘要不会伪造来源", () => {
  const markdown = composeHandoff({
    task: { id: "scope-empty", title: "空任务", summary: "" },
    entries: [],
    sources: [],
    prepared: { status: "empty", content: null },
    generatedAt: "2026-01-05T00:00:00.000Z",
    baseUrl: "http://127.0.0.1:8000",
  });

  assert.match(markdown, /记录总数：0 条/);
  assert.match(markdown, /尚未写入 Memory 记录/);
  assert.match(markdown, /尚未保存 Source 证据/);
  assert.match(markdown, /状态：`empty`/);
});

test("buildPreparedQuery 包含任务标题与交接关键词", () => {
  const query = buildPreparedQuery({ title: "酶活性复现" });
  assert.match(query, /^酶活性复现 /);
  assert.match(query, /研究交接/);
});

test("loadConfig 校验地址、凭据与端口范围", () => {
  const config = loadConfig({});
  assert.equal(config.pcBaseUrl, "http://127.0.0.1:8000");
  assert.equal(config.pcToken, null);
  assert.equal(config.host, "127.0.0.1");
  assert.equal(config.port, 4173);
  assert.equal(config.pcTimeoutMs, 8000);

  assert.throws(
    () => loadConfig({ POWERCONTEXT_URL: "https://user:pass@example.com" }),
    /不能包含用户名或密码/,
  );
  assert.throws(() => loadConfig({ PORT: "70000" }), /PORT/);
});

test("PowerContext 网络失败映射为 503 且声明不降级", async () => {
  const pc = new PowerContextClient({
    baseUrl: "http://127.0.0.1:1",
    timeoutMs: 1000,
    fetchImpl: async () => {
      throw new TypeError("fetch failed");
    },
  });

  await assert.rejects(
    () => pc.listScopes(),
    (error) =>
      error instanceof PowerContextUnavailableError &&
      error.status === 503 &&
      error.code === "powercontext_unavailable" &&
      error.details.noLocalFallback === true &&
      /不会使用本地 JSON 或模拟数据替代/.test(error.message),
  );
});

test("PowerContext 401 映射为鉴权错误", async () => {
  const pc = new PowerContextClient({
    baseUrl: "http://127.0.0.1:8000",
    timeoutMs: 1000,
    fetchImpl: async () =>
      new Response(
        JSON.stringify({
          error: { code: "unauthorized", message: "missing token" },
        }),
        { status: 401, headers: { "Content-Type": "application/json" } },
      ),
  });

  await assert.rejects(
    () => pc.listScopes(),
    (error) =>
      error instanceof PowerContextAuthError &&
      error.status === 502 &&
      error.code === "powercontext_auth_failed",
  );
});
