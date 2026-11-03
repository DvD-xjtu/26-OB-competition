# 实验续航 / Research Relay

> 最新验证（2026-11-03）：21 项单元测试、离线语义、真实 PowerContext 集成、端到端测试全部通过；完整日志见 `evidence/validation.json`。桌面浏览器已验证任务读取和交接摘要。下文开发阶段记录保留历史状态，以本段及真实证据为准。

面向科研过程的中文研究记录与交接工具。每个研究任务对应一个真实的 **PowerContext Scope**，实验观察、研究决策、下一步待办和原始资料都通过 PowerContext HTTP API 保存。刷新页面、重启应用或开启新会话后，研究进展仍然从 PowerContext 重新读取。

> 本应用不包含本地 JSON 数据库、模拟后端或前端持久化。PowerContext 不可用时，界面会明确标记服务离线，写操作返回 `503 powercontext_unavailable`，并声明 `noLocalFallback: true`。

## 解决的问题

科研工作经常在“实验做完”和“下次继续”之间丢失上下文：现象散落在聊天记录里，决策没有依据，原始资料只有链接没有出处，交接摘要靠回忆补写。

实验续航把研究过程拆成四类可检索记录，并在交接时把 **Memory 引用、Source 证据和 PowerContext 准备的上下文** 一并写入摘要，让下一次实验可以从可核验的来源继续。

## 功能

- **研究任务**：创建多个相互隔离的研究任务，每个任务是一个独立 PowerContext Scope。
- **四类记录**：实验观察、研究决策、下一步待办、原始资料。
- **资料取证**：原始链接先写入 Memory，再以 `rr-link-<entryId>` 为 ID 写入 PowerContext Source，摘要中附 Source ID 与摘要值。
- **PowerContext 检索**：搜索直接调用 `POST /v1/memory/search`，结果带引用与命中方式。
- **交接摘要**：汇总 Memory 条目、Source 证据与 `POST /v1/context/prepare` 返回的有界历史上下文，输出带来源账本的 Markdown。
- **刷新即恢复**：任务列表、时间线和搜索全部从 PowerContext 读取，不使用 `localStorage` 保存研究数据。
- **服务状态**：展示 `/health/live`、`/health/ready`、Scope API 与鉴权状态；离线时禁用写入并保留重试。
- **响应式中文界面**：桌面三栏、平板双栏与移动端单栏布局，支持键盘操作、减少动效偏好。
- **安全默认值**：CSP、`nosniff`、`DENY` 框架策略；浏览器不接触 PowerContext Bearer 令牌；用户文本通过 DOM API 渲染，不使用 `innerHTML`。

## 数据映射

| 应用概念 | PowerContext 资源 | 关键约定 |
| --- | --- | --- |
| 研究任务 | Scope | 标题以 `[实验续航] ` 开头；`external_references` 记录创建时间与随机引用 |
| 实验观察 / 决策 / 待办 | Memory 条目 | `kind = research-relay/<type>/<ISO 时间>` |
| 原始资料 | Memory 条目 + Source | Memory 保存可检索文本；Source ID 为 `rr-link-<entryId>` |
| 任务列表 | `GET /v1/scopes?query=实验续航&query_field=title` | 只展示标题带前缀的 Scope |
| 搜索 | `POST /v1/memory/search` | `mode: auto`；类型由 `kind` 补齐 |
| 交接 | Memory 列表 + Sources + `POST /v1/context/prepare` | 不复制数据到本地，摘要标注 Memory 与 Source 引用 |

PowerContext 的 Memory 条目本身不暴露创建时间，搜索结果也不返回 `kind`，因此应用把类型和 ISO 时间编码进 Memory `kind`，再通过 `/v1/memory/entries/list` 补齐搜索结果类型。这是本项目的显式约定，不依赖未公开字段。

## 系统结构

```text
浏览器（无框架，原生 DOM）
   │  /api/*
   ▼
Node.js HTTP 服务（node:http，零第三方运行时依赖）
   │  校验、隔离、组装摘要
   ▼
PowerContext HTTP API（真实服务，默认 http://127.0.0.1:8000）
   ├── Scopes
   ├── Memory
   ├── Sources
   └── Context prepare
```

- 前端：`public/index.html`、`public/styles.css`、`public/app.js`
- HTTP 层：`src/app.js`（静态资源、API 路由、安全响应头、请求 ID）
- 领域层：`src/domain.js`（校验、Scope/Memory 映射、统计）
- PowerContext 客户端：`src/powercontext.js`（错误分类、超时、鉴权、探测）
- 业务层：`src/research-service.js`（双任务隔离、检索、取证、交接）
- 摘要：`src/handoff.js`（Markdown、引用、来源账本）

## 环境要求

- Node.js `>= 20.11.0`（开发环境为 `24.21.0`，`.nvmrc` 已固定）
- Python `3.11+` 与真实 PowerContext 服务
- `requirements-powercontext.txt` 固定 比赛源码 commit `c92dc0fd986d42cbdebae14670755e04be2c4f8f`
- 不需要安装任何 npm 运行时依赖

如果本机 Python 为 3.14 且部分依赖没有兼容 wheel，请改用 Python 3.12 或 3.13 创建虚拟环境。

## 快速开始

### 1. 安装 PowerContext（项目本地虚拟环境）

Windows Bash（本项目当前 shell）：

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-powercontext.txt
```

Linux / macOS：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-powercontext.txt
```

也可以使用 `uv` 创建指定 Python 版本的环境：

```bash
uv venv --python 3.12 .venv
source .venv/Scripts/activate
uv pip install -r requirements-powercontext.txt
```

### 2. 启动真实 PowerContext

```bash
python ../tools/powercontext_server.py --workspace .runtime/powercontext
```

默认端点为 `http://127.0.0.1:8000`，使用本地 SQLite。保持该进程运行。

另开一个终端确认服务：

```bash
curl --fail --silent --show-error http://127.0.0.1:8000/health/live
```

### 3. 配置实验续航

```bash
cp .env.example .env
```

`.env` 示例：

```dotenv
POWERCONTEXT_URL=http://127.0.0.1:8000
POWERCONTEXT_TOKEN=
POWERCONTEXT_TIMEOUT_MS=8000
HOST=127.0.0.1
PORT=4173
```

- `POWERCONTEXT_TOKEN` 只在 Node 服务端读取，不会发送给浏览器。启用鉴权时请从密钥存储注入，不要提交真实令牌。
- 应用不会覆盖进程中已显式设置的同名环境变量。
- `.env` 已加入 `.gitignore`。

### 4. 启动实验续航

```bash
npm ci
npm start
```

打开 `http://127.0.0.1:4173`。顶部服务状态应显示“PowerContext 在线”；若显示离线，页面会禁用写入并提示恢复服务。

开发模式（文件变更自动重启）：

```bash
npm run dev
```

## HTTP API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 应用与 PowerContext 状态；始终返回 200 以便界面展示 |
| `GET` | `/api/tasks` | 从 PowerContext Scope 列表重建研究任务 |
| `POST` | `/api/tasks` | 创建 Scope；请求体 `{ title, summary }` |
| `GET` | `/api/tasks/:scopeId` | 读取 Scope、Memory 条目与 Source 证据 |
| `POST` | `/api/tasks/:scopeId/entries` | 写入四类记录 |
| `POST` | `/api/tasks/:scopeId/search` | 调用 PowerContext 检索，请求体 `{ query }` |
| `GET` | `/api/tasks/:scopeId/handoff` | 生成带来源账本的交接摘要 |

所有写接口都要求 `Content-Type: application/json`，请求体上限 128KB，单条 Memory 文本上限 8192 字节。错误统一为：

```json
{
  "error": {
    "code": "powercontext_unavailable",
    "message": "无法连接 PowerContext（...）。本应用不会使用本地 JSON 或模拟数据替代。",
    "details": { "noLocalFallback": true },
    "requestId": "rr-..."
  }
}
```

### 实际调用的 PowerContext 接口

| 用途 | 接口 |
| --- | --- |
| 存活 / 就绪 | `GET /health/live`、`GET /health/ready` |
| 能力与版本 | `GET /v1/capabilities` |
| Scope 列表 / 创建 / 读取 | `GET /v1/scopes`、`POST /v1/scopes`、`GET /v1/scopes/{id}` |
| 写入 Memory | `POST /v1/memory/remember` |
| 列出 Memory | `POST /v1/memory/entries/list` |
| 检索 | `POST /v1/memory/search` |
| 准备上下文 | `POST /v1/context/prepare` |
| Source 写入 / 列表 | `POST /v1/sources/content`、`GET /v1/scopes/{id}/sources` |

应用不会把 PowerContext 返回的 `content` 当作当前指令；交接摘要明确标注其为不可信历史上下文。

## 测试与可复现验证

### 单元测试

```bash
npm test
```

覆盖：输入校验、URL 安全、8192 字节限制、Memory `kind` 编解码、Scope/任务映射、条目统计、引用标签、交接 Markdown、配置校验、PowerContext 网络错误与 401 映射。

### 离线语义验证

```bash
npm run verify:offline
```

启动一个指向不可达端口的应用，验证：

- `/api/health` 返回 `online: false` 与 `storage.localFallback: false`；
- 任务列表、创建、详情、写入、搜索、交接全部返回 `503 powercontext_unavailable`；
- 错误声明不使用本地 JSON 或模拟数据；
- 静态页面、CSP 与 favicon 正常。

该脚本不需要真实 PowerContext。

### 真实 PowerContext 集成测试

```bash
RUN_POWERCONTEXT_INTEGRATION=1 npm run test:integration
```

Windows PowerShell：

```powershell
$env:RUN_POWERCONTEXT_INTEGRATION="1"; npm run test:integration
```

未设置该变量时测试会明确跳过，不会伪造通过。测试要求真实服务在线，并会在 PowerContext 中创建带唯一后缀的 Scope（两个研究任务和一个隔离校验 Scope）。本应用没有实现 Scope 删除流程，演示环境请自行管理这些验证数据。

覆盖：两个任务隔离、四类记录、Source 取证、PowerContext 检索、跨任务搜索无结果、交接引用、非实验续航 Scope 拒访、重启应用后重新读取。

### 端到端验证脚本

```bash
npm run verify:e2e
```

与集成测试类似，但以人类可读的 `PASS` 输出逐步验证完整主流程，并在最后打印本次创建的 Scope ID。PowerContext 不在线时会失败并提示启动服务。

### 当前验证状态（2026-11-03）

| 项目 | 状态 |
| --- | --- |
| 源码、测试、文档完成 | 已完成 |
| `npm test` | **已执行，3 个失败后修正 fixture，重跑待执行** |
| `npm run verify:offline` | **未执行** |
| `npm run test:integration` | **已通过**（真实 PowerContext 运行于 `localhost:8000`） |
| `npm run verify:e2e` | **未执行**（需真实 PowerContext） |
| 浏览器手工走查 | **未执行** |
| 静态展示页 `site-dist/index.html` | **已创建，未发布** |

首次 `npm test` 的 3 个失败来自测试 fixture：它使用了扁平的 `artifact_id` / `revision`，而官方与真实 API 返回 `memory_ref: { family: "memory", artifact_id, revision }`。实现 `normalizeEntry` 本身正确；fixture 已按真实契约修正，断言未放宽，但重跑尚未执行，因此单元测试不标记为通过。离线语义、端到端脚本和浏览器走查仍无执行记录。开发过程与限制见 [DEVELOPMENT.md](DEVELOPMENT.md)。

## 安全与来源说明

- 研究数据只写入 PowerContext；应用目录内没有研究数据文件。
- Scope 是数据分区键，不是访问控制；应用在每次任务请求时校验标题前缀 `[实验续航]`，拒绝其他 Scope。
- 浏览器不会收到 PowerContext Bearer 令牌；所有请求由 Node 服务端代理。
- 资料链接仅允许 `http` / `https`，拒绝嵌入用户名或密码。
- 页面使用 `default-src 'self'`、`script-src 'self'`、`style-src 'self'`，无内联脚本或样式。
- 用户记录、搜索命中与摘要均通过 DOM API 安全渲染；链接在渲染前再次校验协议。
- 交接摘要中的 `/v1/context/prepare` 内容属于不可信历史上下文，当前实验状态与最新记录优先。

## 已知限制

- 任务暂无重命名、归档或删除入口；Scope 生命周期由 PowerContext 管理。
- 最小 PowerContext 服务使用全文检索；需要语义检索时请按 PowerContext 文档配置向量检索。
- 任务列表最多读取 5 页（每页 100 条），研究任务特别多时需要调整 `src/research-service.js` 的分页上限。
- 交接摘要限制各类记录展示条数，完整记录仍可在 PowerContext 中检索。
- 原始资料只保存链接与说明，不抓取网页正文。

## 目录

```text
.
├── public/                     # 中文界面（HTML / CSS / 原生 JS / SVG）
├── site-dist/                  # 静态项目展示页（已公开）
│   └── index.html
├── scripts/
│   ├── verify-offline.mjs      # 无 PowerContext 时的降级语义验证
│   └── verify-e2e.mjs          # 真实 PowerContext 端到端验证
├── src/
│   ├── app.js                  # HTTP 与静态资源
│   ├── config.js               # 环境变量校验
│   ├── domain.js               # 领域模型与校验
│   ├── env.js                  # 项目本地 .env 加载
│   ├── errors.js               # AppError
│   ├── handoff.js              # 交接 Markdown
│   ├── index.js                # 启动入口
│   ├── powercontext.js         # PowerContext HTTP 客户端
│   └── research-service.js     # 业务编排
├── test/
│   ├── unit.test.js
│   └── integration.powercontext.test.js
├── .env.example
├── .nvmrc
├── DEVELOPMENT.md
├── POWERCONTEXT_API_REFERENCE.md
├── package.json
├── package-lock.json
└── requirements-powercontext.txt
```

## 发布状态

Qoder Sites 已发布并设为公开：https://research-relay-82rwgyi06a8.qoder.website 。这是项目展示页；完整应用按上文在本地连接真实 PowerContext 运行。发布标识见 `evidence/publication.json`。

实际验证使用比赛 PowerContext 固定源码（安装后版本 `0.1.dev797+gc92dc0fd9`）。安装上述 requirements 后，可运行 `python ../tools/powercontext_server.py` 启动与本次验证相同的服务；数据目录通过 `--workspace` 配置。
