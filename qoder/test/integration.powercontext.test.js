import test from "node:test";
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";

import { createResearchRelayServer } from "../src/app.js";
import { loadConfig } from "../src/config.js";
import { PowerContextClient } from "../src/powercontext.js";

const RUN = process.env.RUN_POWERCONTEXT_INTEGRATION === "1";

const quietLogger = {
  info() {},
  warn() {},
  error() {},
};

function makeMarker(prefix) {
  const hex = randomUUID().replace(/-/g, "").slice(0, 16);
  const letters = [...hex]
    .map((char) => String.fromCharCode(97 + Number.parseInt(char, 16)))
    .join("");
  return `${prefix}${letters}`;
}

async function startApp(config) {
  const pc = new PowerContextClient({
    baseUrl: config.pcBaseUrl,
    token: config.pcToken,
    timeoutMs: config.pcTimeoutMs,
  });
  const { server } = createResearchRelayServer({
    pc,
    config,
    logger: quietLogger,
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  return {
    server,
    baseUrl: `http://127.0.0.1:${server.address().port}`,
    close: () =>
      new Promise((resolve, reject) =>
        server.close((error) => (error ? reject(error) : resolve())),
      ),
  };
}

async function call(baseUrl, path, { method = "GET", body } = {}) {
  const response = await fetch(`${baseUrl}${path}`, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  return { status: response.status, data, headers: response.headers };
}

async function waitFor(fn, predicate, label, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  let last = null;
  while (Date.now() < deadline) {
    last = await fn();
    if (predicate(last)) return last;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(
    `等待超时：${label}。最后一次响应：${JSON.stringify(last).slice(0, 1200)}`,
  );
}

test(
  "真实 PowerContext 主流程：双任务隔离、检索、交接与重连",
  {
    skip: RUN
      ? false
      : "未执行：设置 RUN_POWERCONTEXT_INTEGRATION=1 并启动真实 PowerContext 后运行 `npm run test:integration`。",
    timeout: 180000,
  },
  async (t) => {
    const config = loadConfig(process.env);
    const unique = `${Date.now()}-${randomUUID().slice(0, 8)}`;
    const markerA = makeMarker("relayalpha");
    const markerB = makeMarker("relaybeta");
    const baseUrlForLink = `https://example.com/research-relay/${unique}`;

    let app = await startApp(config);
    const createdScopes = [];

    t.after(async () => {
      await app.close().catch(() => {});
    });

    const health = await call(app.baseUrl, "/api/health");
    assert.equal(health.status, 200);
    assert.equal(
      health.data.powercontext.online,
      true,
      `PowerContext 不在线：${health.data.powercontext.detail}`,
    );
    assert.equal(health.data.storage.localFallback, false);
    assert.equal(health.data.powercontext.status, "online");

    const taskA = await call(app.baseUrl, "/api/tasks", {
      method: "POST",
      body: {
        title: `集成验证 A ${unique}`,
        summary: "验证实验观察、决策、待办、资料与交接摘要。",
      },
    });
    assert.equal(taskA.status, 201, JSON.stringify(taskA.data));
    createdScopes.push(taskA.data.task.id);

    const taskB = await call(app.baseUrl, "/api/tasks", {
      method: "POST",
      body: {
        title: `集成验证 B ${unique}`,
        summary: "验证第二个研究任务的 Scope 隔离。",
      },
    });
    assert.equal(taskB.status, 201, JSON.stringify(taskB.data));
    createdScopes.push(taskB.data.task.id);
    assert.notEqual(taskA.data.task.id, taskB.data.task.id);

    const scopeA = taskA.data.task.id;
    const scopeB = taskB.data.task.id;

    const entries = [
      {
        type: "observation",
        text: `实验观察 ${markerA}：第 3 组产率 68%，较上批提升 4 个百分点。`,
        note: "温度 37.2°C，反应 24h。",
      },
      {
        type: "decision",
        text: `研究决策 ${markerA}：先复现异常组，暂不扩大样本量。`,
        note: "连续三次重复实验后再评估。",
      },
      {
        type: "todo",
        text: `下一步待办 ${markerA}：补齐三次重复实验并完成统计分析。`,
        note: "周五前完成。",
      },
      {
        type: "link",
        title: `原始资料 ${markerA}`,
        url: baseUrlForLink,
        note: "本次验证生成的公开示例链接。",
      },
    ];

    for (const entry of entries) {
      const created = await call(
        app.baseUrl,
        `/api/tasks/${encodeURIComponent(scopeA)}/entries`,
        { method: "POST", body: entry },
      );
      assert.equal(created.status, 201, JSON.stringify(created.data));
      assert.equal(created.data.saved, true);
      assert.equal(created.data.localFallback, false);
    }

    const createdB = await call(
      app.baseUrl,
      `/api/tasks/${encodeURIComponent(scopeB)}/entries`,
      {
        method: "POST",
        body: {
          type: "observation",
          text: `实验观察 ${markerB}：对照组含水量下降 2.1%。`,
          note: "仅属于任务 B。",
        },
      },
    );
    assert.equal(createdB.status, 201, JSON.stringify(createdB.data));

    const detailA = await waitFor(
      () => call(app.baseUrl, `/api/tasks/${encodeURIComponent(scopeA)}`),
      (result) =>
        result.status === 200 &&
        result.data.entries.length === 4 &&
        result.data.entries.some(
          (entry) => entry.type === "link" && entry.source !== null,
        ),
      "任务 A 的四条记录与资料 Source 证据",
    );

    assert.equal(detailA.data.localFallback, false);
    assert.equal(detailA.data.stats.observation, 1);
    assert.equal(detailA.data.stats.decision, 1);
    assert.equal(detailA.data.stats.todo, 1);
    assert.equal(detailA.data.stats.link, 1);
    assert.equal(
      detailA.data.entries.some((entry) => entry.text.includes(markerB)),
      false,
      "任务 A 不应读到任务 B 的记录",
    );
    assert.equal(
      detailA.data.sources.some((source) => source.content.includes(markerA)),
      true,
      "资料链接应同时保存为 PowerContext Source 证据",
    );

    const detailB = await call(
      app.baseUrl,
      `/api/tasks/${encodeURIComponent(scopeB)}`,
    );
    assert.equal(detailB.status, 200);
    assert.equal(detailB.data.entries.length, 1);
    assert.equal(detailB.data.entries[0].text.includes(markerB), true);
    assert.equal(detailB.data.entries[0].text.includes(markerA), false);

    const searchA = await waitFor(
      () =>
        call(app.baseUrl, `/api/tasks/${encodeURIComponent(scopeA)}/search`, {
          method: "POST",
          body: { query: markerA },
        }),
      (result) => result.status === 200 && result.data.hits.length > 0,
      "PowerContext /v1/memory/search 返回任务 A 的命中",
    );
    assert.equal(searchA.data.engine, "PowerContext /v1/memory/search");
    assert.equal(
      searchA.data.hits.some((hit) => hit.text.includes(markerA)),
      true,
    );
    assert.equal(
      searchA.data.hits.some((hit) => hit.text.includes(markerB)),
      false,
      "任务 A 的搜索不应命中任务 B 的内容",
    );

    const searchIsolation = await call(
      app.baseUrl,
      `/api/tasks/${encodeURIComponent(scopeA)}/search`,
      { method: "POST", body: { query: markerB } },
    );
    assert.equal(searchIsolation.status, 200);
    assert.equal(
      searchIsolation.data.hits.length,
      0,
      "在任务 A 中搜索任务 B 的标记应无结果",
    );

    const handoff = await call(
      app.baseUrl,
      `/api/tasks/${encodeURIComponent(scopeA)}/handoff`,
    );
    assert.equal(handoff.status, 200);
    assert.equal(handoff.data.engine, "PowerContext HTTP API");
    assert.match(handoff.data.markdown, new RegExp(markerA));
    assert.match(handoff.data.markdown, /## 二、关键决策/);
    assert.match(handoff.data.markdown, /## 七、来源账本/);
    assert.match(handoff.data.markdown, /Source `rr-link-/);
    assert.match(handoff.data.markdown, /Memory `[^`]+@r\d+`/);
    assert.match(
      handoff.data.markdown,
      /状态：`(ready|empty|error)`/,
    );
    assert.equal(handoff.data.localFallback, false);
    assert.equal(
      handoff.data.warnings.some((warning) => /准备上下文请求失败/.test(warning)),
      false,
      `准备上下文不应失败：${handoff.data.warnings.join("; ")}`,
    );

    const tasks = await call(app.baseUrl, "/api/tasks");
    assert.equal(tasks.status, 200);
    assert.equal(
      tasks.data.tasks.some((task) => task.id === scopeA),
      true,
    );
    assert.equal(
      tasks.data.tasks.some((task) => task.id === scopeB),
      true,
    );

    // 非实验续航 Scope 必须被应用拒绝，不能仅靠前端隐藏。
    const pc = new PowerContextClient({
      baseUrl: config.pcBaseUrl,
      token: config.pcToken,
      timeoutMs: config.pcTimeoutMs,
    });
    const foreign = await pc.createScope({
      title: `隔离校验 ${unique}`,
      summary: "该 Scope 不属于实验续航，应被应用拒绝。",
      idempotency_key: `foreign-${unique}`,
    });
    const foreignId = foreign.data?.scope?.scope_id ?? foreign.data?.scope_id;
    assert.ok(foreignId, "创建隔离校验 Scope 失败");
    createdScopes.push(foreignId);

    const forbidden = await call(
      app.baseUrl,
      `/api/tasks/${encodeURIComponent(foreignId)}`,
    );
    assert.equal(forbidden.status, 404);
    assert.equal(forbidden.data.error.code, "task_not_found");

    // 关闭并重建应用，模拟新会话：数据必须仍然来自 PowerContext。
    await app.close();
    app = await startApp(config);

    const reloaded = await call(
      app.baseUrl,
      `/api/tasks/${encodeURIComponent(scopeA)}`,
    );
    assert.equal(reloaded.status, 200);
    assert.equal(reloaded.data.entries.length, 4);
    assert.equal(reloaded.data.stats.link, 1);
    assert.equal(
      reloaded.data.entries.some((entry) => entry.text.includes(markerA)),
      true,
    );

    t.diagnostic(
      `已创建并验证 Scope：${createdScopes.join(", ")}（真实 PowerContext 无本地副本）。`,
    );
  },
);
