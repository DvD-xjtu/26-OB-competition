import path from "node:path";
import { fileURLToPath } from "node:url";
import { createResearchRelayServer } from "./app.js";
import { loadConfig } from "./config.js";
import { loadDotEnv } from "./env.js";
import { PowerContextClient } from "./powercontext.js";

const projectRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const loadedKeys = loadDotEnv(path.join(projectRoot, ".env"));
const config = loadConfig(process.env);

const pc = new PowerContextClient({
  baseUrl: config.pcBaseUrl,
  token: config.pcToken,
  timeoutMs: config.pcTimeoutMs,
});

const { server } = createResearchRelayServer({ pc, config });

server.listen(config.port, config.host, () => {
  console.log("实验续航 / Research Relay");
  console.log(`本地界面: http://${config.host}:${config.port}`);
  console.log(`PowerContext: ${config.pcBaseUrl}`);
  console.log(
    `Bearer 令牌: ${config.pcToken ? "已配置（不会展示）" : "未配置"}`,
  );
  console.log("数据模式: 仅 PowerContext HTTP API（无本地 JSON / 模拟后端）");
  if (loadedKeys.length > 0) {
    console.log(`已从 .env 读取 ${loadedKeys.length} 个配置项。`);
  }
});

server.on("error", (error) => {
  console.error(`启动失败: ${error.message}`);
  process.exitCode = 1;
});

let closing = false;
function shutdown(signal) {
  if (closing) return;
  closing = true;
  console.log(`收到 ${signal}，正在关闭本地服务…`);
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 5000).unref();
}

process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));
