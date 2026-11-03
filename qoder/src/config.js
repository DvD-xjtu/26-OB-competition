function integerInRange(raw, fallback, min, max, name) {
  if (raw === undefined || raw === null || String(raw).trim() === "") return fallback;
  const value = Number.parseInt(String(raw), 10);
  if (!Number.isInteger(value) || value < min || value > max) {
    throw new Error(`${name} 必须是 ${min} 到 ${max} 之间的整数。`);
  }
  return value;
}

function normalizeBaseUrl(raw) {
  const value = String(raw || "http://127.0.0.1:8000").trim().replace(/\/+$/, "");
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new Error("POWERCONTEXT_URL 不是有效的 URL。");
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("POWERCONTEXT_URL 只支持 http 或 https。");
  }
  if (url.username || url.password) {
    throw new Error("POWERCONTEXT_URL 不能包含用户名或密码。");
  }
  return url.toString().replace(/\/+$/, "");
}

export function loadConfig(env = process.env) {
  const host = String(env.HOST || "127.0.0.1").trim();
  if (!host || /[\u0000-\u001F]/.test(host)) {
    throw new Error("HOST 配置无效。");
  }

  return {
    pcBaseUrl: normalizeBaseUrl(env.POWERCONTEXT_URL),
    pcToken: env.POWERCONTEXT_TOKEN?.trim() || null,
    pcTimeoutMs: integerInRange(
      env.POWERCONTEXT_TIMEOUT_MS,
      8000,
      1000,
      60000,
      "POWERCONTEXT_TIMEOUT_MS",
    ),
    host,
    port: integerInRange(env.PORT, 4173, 1, 65535, "PORT"),
    nodeEnv: env.NODE_ENV || "development",
  };
}
