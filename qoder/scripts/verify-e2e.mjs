import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";

import { createResearchRelayServer } from "../src/app.js";
import { loadConfig } from "../src/config.js";
import { PowerContextClient } from "../src/powercontext.js";

const quietLogger = { info() {}, warn() {}, error() {} };

function pass(message) {
  console.log(`PASS  ${message}`);
}

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

async function request(baseUrl, path, { method = "GET", body } = {}) {
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

async function main() {
  const config = loadConfig(process.env);
  const unique = `${Date.now()}-${randomUUID().slice(0, 8)}`;
  const markerA = makeMarker("relayalpha");
  const markerB = makeMarker("relaybeta");
  const createdScopes = [];

  let app = await startApp(config);
  let closed = false;

  try {
    console.log(`PowerContext 端点：${config.pcBaseUrl}`);
    const health = await request(app.baseUrl, "/api/health");
    assert.equal(health.status, 200);
    if (!health.data.powercontext.online) {
      throw new Error(
        `PowerContext 不在线（${health.data.powercontext.status}）：${health.data.powercontext.detail}\n` +
          "请先启动真实 PowerContext 服务，并确认 .env 中的 POWERCONTEXT_URL 正确。",
      );
    }
    assert.equal(health.data.storage.localFallback, false);
    assert.equal(health.data.storage.mode, "powercontext-http");
    pass("应用已连接真实 PowerContext，且未启用本地降级");

    const taskA = await request(app.baseUrl, "/api/tasks", {
      method: "POST",
      body: {
        title: `端到端验证 A ${unique}`,
        summary: "验证观察、决策、待办、资料、检索、交接与重启恢复。",
      },
    });
    assert.equal(taskA.status, 201, JSON.stringify(taskA.data));
    createdScopes.push(taskA.data.task.id);

    const taskB = await request(app.baseUrl, "/api/tasks", {
      method: "POST",
      body: {
        title: `端到端验证 B ${unique}`,
        summary: "第二个研究任务，用于验证 Scope 隔离。",
      },
    });
    assert.equal(taskB.status, 201, JSON.stringify(taskB.data));
    createdScopes.push(taskB.data.task.id);

    const scopeA = taskA.data.task.id;
    const scopeB = taskB.data.task.id;
    assert.notEqual(scopeA, scopeB);
    pass(`创建两个隔离研究任务：${scopeA} / ${scopeB}`);

    const entriesA = [
      {
        type: "observation",
        text: `实验观察 ${markerA}：第 3 组产率 68%，较上批提升 4 个百分点。`,
        note: "温度 37.2°C，反应 24h。",
      },
      {
        type: "decision",
        text: `研究决策 ${markerA}：先复现异常组，暂不扩大样本量。`,
        note: "三次重复实验后再评估。",
      },
      {
        type: "todo",
        text: `下一步待办 ${markerA}：补齐三次重复实验并完成统计分析。`,
        note: "周五前完成。",
      },
      {
        type: "link",
        title: `原始资料 ${markerA}`,
        url: `https://example.com/research-relay/${unique}`,
        note: "验证链接同时写入 Memory 与 Source。",
      },
    ];

    for (const entry of entriesA) {
      const created = await request(
        app.baseUrl,
        `/api/tasks/${encodeURIComponent(scopeA)}/entries`,
        { method: "POST", body: entry },
      );
      assert.equal(created.status, 201, JSON.stringify(created.data));
      assert.equal(created.data.saved, true);
    }
    pass("任务 A 写入实验观察、研究决策、下一步待办与原始资料");

    const createdB = await request(
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
    pass("任务 B 写入独立记录");

    const detailA = await waitFor(
      () => request(app.baseUrl, `/api/tasks/${encodeURIComponent(scopeA)}`),
      (result) =>
        result.status === 200 &&
        result.data.entries.length === 4 &&
        result.data.entries.some(
          (entry) => entry.type === "link" && entry.source !== null,
        ),
      "任务 A 的四条记录与资料 Source 证据",
    );

    assert.deepEqual(
      {
        observation: detailA.data.stats.observation,
        decision: detailA.data.stats.decision,
        todo: detailA.data.stats.todo,
        link: detailA.data.stats.link,
      },
      { observation: 1, decision: 1, todo: 1, link: 1 },
    );
    assert.equal(
      detailA.data.entries.some((entry) => entry.text.includes(markerB)),
      false,
    );
    assert.equal(
      detailA.data.sources.some((source) => source.content.includes(markerA)),
      true,
    );
    pass("任务 A 时间线与 Source 证据均从 PowerContext 读取");

    const detailB = await request(
      app.baseUrl,
      `/api/tasks/${encodeURIComponent(scopeB)}`,
    );
    assert.equal(detailB.status, 200);
    assert.equal(detailB.data.entries.length, 1);
    assert.equal(detailB.data.entries[0].text.includes(markerB), true);
    assert.equal(detailB.data.entries[0].text.includes(markerA), false);
    pass("两个任务的记录相互隔离");

    const searchA = await waitFor(
      () =>
        request(app.baseUrl, `/api/tasks/${encodeURIComponent(scopeA)}/search`, {
          method: "POST",
          body: { query: markerA },
        }),
      (result) => result.status === 200 && result.data.hits.length > 0,
      "PowerContext 搜索结果",
    );
    assert.equal(searchA.data.engine, "PowerContext /v1/memory/search");
    assert.equal(
      searchA.data.hits.some((hit) => hit.text.includes(markerA)),
      true,
    );
    assert.equal(
      searchA.data.hits.some((hit) => hit.text.includes(markerB)),
      false,
    );
    pass(`检索由 PowerContext 完成，返回 ${searchA.data.hits.length} 条命中`);

    const crossSearch = await request(
      app.baseUrl,
      `/api/tasks/${encodeURIComponent(scopeA)}/search`,
      { method: "POST", body: { query: markerB } },
    );
    assert.equal(crossSearch.status, 200);
    assert.equal(crossSearch.data.hits.length, 0);
    pass("任务 A 中搜索任务 B 的标记无结果");

    const handoff = await request(
      app.baseUrl,
      `/api/tasks/${encodeURIComponent(scopeA)}/handoff`,
    );
    assert.equal(handoff.status, 200);
    assert.equal(handoff.data.engine, "PowerContext HTTP API");
    assert.match(handoff.data.markdown, new RegExp(markerA));
    assert.match(handoff.data.markdown, /## 二、关键决策/);
    assert.match(handoff.data.markdown, /## 七、来源账本/);
    assert.match(handoff.data.markdown, /Memory `[^`]+@r\d+`/);
    assert.match(handoff.data.markdown, /Source `rr-link-/);
    assert.equal(
      handoff.data.warnings.some((warning) => /准备上下文请求失败/.test(warning)),
      false,
    );
    pass("交接摘要包含 Memory 引用、Source 证据与 PowerContext 准备上下文");

    const tasks = await request(app.baseUrl, "/api/tasks");
    assert.equal(tasks.status, 200);
    assert.equal(tasks.data.tasks.some((task) => task.id === scopeA), true);
    assert.equal(tasks.data.tasks.some((task) => task.id === scopeB), true);
    pass("任务列表由 PowerContext Scope 重建");

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

    const rejected = await request(
      app.baseUrl,
      `/api/tasks/${encodeURIComponent(foreignId)}`,
    );
    assert.equal(rejected.status, 404);
    assert.equal(rejected.data.error.code, "task_not_found");
    pass("应用拒绝访问非实验续航 Scope");

    await app.close();
    closed = true;
    app = await startApp(config);
    closed = false;

    const reloaded = await request(
      app.baseUrl,
      `/api/tasks/${encodeURIComponent(scopeA)}`,
    );
    assert.equal(reloaded.status, 200);
    assert.equal(reloaded.data.entries.length, 4);
    assert.equal(
      reloaded.data.entries.some((entry) => entry.text.includes(markerA)),
      true,
    );
    pass("重启应用后重新读取 PowerContext，研究进展仍然完整");

    console.log(
      `\n端到端验证完成。本次使用真实 PowerContext 创建 Scope：${createdScopes.join(", ")}`,
    );
    console.log("应用无本地研究数据副本；以上 Scope 可在 PowerContext 侧查看。");
  } finally {
    if (!closed) {
      await app.close().catch(() => {});
    }
  }
}

main().catch((error) => {
  console.error(`FAIL  ${error.message}`);
  if (error.stack) console.error(error.stack);
  process.exitCode = 1;
});
