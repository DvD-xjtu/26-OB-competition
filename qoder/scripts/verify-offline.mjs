import assert from "node:assert/strict";
import net from "node:net";

import { createResearchRelayServer } from "../src/app.js";
import { loadConfig } from "../src/config.js";
import { PowerContextClient } from "../src/powercontext.js";

const quietLogger = { info() {}, warn() {}, error() {} };

function pass(message) {
  console.log(`PASS  ${message}`);
}

async function reserveClosedPort() {
  const server = net.createServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  await new Promise((resolve) => server.close(resolve));
  return port;
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

async function main() {
  const closedPort = await reserveClosedPort();
  const config = loadConfig({
    POWERCONTEXT_URL: `http://127.0.0.1:${closedPort}`,
    POWERCONTEXT_TIMEOUT_MS: "1000",
    HOST: "127.0.0.1",
    PORT: "4173",
  });

  const pc = new PowerContextClient({
    baseUrl: config.pcBaseUrl,
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
  const baseUrl = `http://127.0.0.1:${server.address().port}`;

  try {
    const health = await request(baseUrl, "/api/health");
    assert.equal(health.status, 200, "健康检查应返回 200 以便界面展示状态");
    assert.equal(health.data.powercontext.online, false);
    assert.equal(health.data.powercontext.status, "offline");
    assert.equal(health.data.storage.localFallback, false);
    assert.equal(health.data.storage.mode, "powercontext-http");
    pass("PowerContext 不可达时 /api/health 明确返回 offline");

    const list = await request(baseUrl, "/api/tasks");
    assert.equal(list.status, 503);
    assert.equal(list.data.error.code, "powercontext_unavailable");
    assert.equal(list.data.error.details.noLocalFallback, true);
    assert.match(list.data.error.message, /不会使用本地 JSON 或模拟数据替代/);
    pass("任务列表在服务不可用时返回 503，且声明不降级");

    const create = await request(baseUrl, "/api/tasks", {
      method: "POST",
      body: { title: "离线验证任务", summary: "不应写入任何本地存储。" },
    });
    assert.equal(create.status, 503);
    assert.equal(create.data.error.code, "powercontext_unavailable");
    assert.equal(create.data.error.details.noLocalFallback, true);
    pass("创建任务在服务不可用时返回 503，不产生本地数据");

    const detail = await request(baseUrl, "/api/tasks/offline-check");
    assert.equal(detail.status, 503);
    assert.equal(detail.data.error.code, "powercontext_unavailable");
    pass("读取任务详情在服务不可用时返回 503");

    const entry = await request(baseUrl, "/api/tasks/offline-check/entries", {
      method: "POST",
      body: { type: "observation", text: "不应保存" },
    });
    assert.equal(entry.status, 503);
    assert.equal(entry.data.error.details.noLocalFallback, true);
    pass("写入记录在服务不可用时返回 503");

    const search = await request(baseUrl, "/api/tasks/offline-check/search", {
      method: "POST",
      body: { query: "离线" },
    });
    assert.equal(search.status, 503);
    assert.equal(search.data.error.code, "powercontext_unavailable");
    pass("搜索完全依赖 PowerContext，不可用时返回 503");

    const handoff = await request(baseUrl, "/api/tasks/offline-check/handoff");
    assert.equal(handoff.status, 503);
    assert.equal(handoff.data.error.code, "powercontext_unavailable");
    pass("交接摘要在服务不可用时返回 503");

    const page = await fetch(`${baseUrl}/`);
    assert.equal(page.status, 200);
    assert.match(page.headers.get("content-security-policy") || "", /default-src 'self'/);
    const html = await page.text();
    assert.match(html, /实验续航/);
    assert.match(html, /PowerContext/);
    pass("静态界面可访问，并带 CSP 等安全响应头");

    const favicon = await fetch(`${baseUrl}/favicon.svg`);
    assert.equal(favicon.status, 200);
    assert.equal(favicon.headers.get("content-type"), "image/svg+xml");
    pass("favicon 静态资源正常");

    console.log("\n离线语义验证完成：未使用本地 JSON、模拟后端或任何本地研究数据副本。");
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

main().catch((error) => {
  console.error(`FAIL  ${error.message}`);
  if (error.stack) console.error(error.stack);
  process.exitCode = 1;
});
