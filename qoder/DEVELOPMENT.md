# 开发记录 / DEVELOPMENT

> 最新验证（2026-11-03）：21 项单元测试、离线语义、真实 PowerContext 集成、端到端测试全部通过；完整日志见 `evidence/validation.json`。桌面浏览器已验证任务读取和交接摘要。下文开发阶段记录保留历史状态，以本段及真实证据为准。

- 项目：实验续航 / Research Relay
- 主要开发：Qoder
- 开发日期：2026-11-03
- 约束：仅修改 `C:/Users/ZZZ/Desktop/数据库/ecosystem/qoder`；不读取用户凭据文件；不发送消息、不创建账号、不购买服务、不修改全局配置、不访问其他工作目录、不提交/推送 Git；不发布 Qoder Sites；未开启子代理。

> 重要：本文区分“已完成的代码工作”和“已记录的验证结果”。截至 2026-11-03，真实 PowerContext 集成测试已在 `localhost:8000` 通过；单元测试因测试 fixture 与官方 API 契约不一致出现 3 个失败，fixture 已修正但尚未重跑。其余脚本与浏览器走查尚无执行记录，文末状态表中的“未执行”不是通过。

## 一、需求与完成范围

目标是把研究任务、实验观察、研究决策、待办和原始资料通过真实 PowerContext HTTP API 保存，并在刷新或新会话后恢复；同时提供带来源的交接摘要、PowerContext 检索、至少两个隔离任务、明确的服务不可用提示，以及响应式中文界面。

本阶段交付：

- 可运行的 Node.js 应用与原生前端；
- 真实 PowerContext HTTP 客户端与业务编排；
- 单元测试、真实 PowerContext 集成测试（默认跳过）；
- 离线语义验证脚本与真实端到端验证脚本；
- 固定版本的 Python 依赖文件、零第三方 npm 运行时依赖；
- 无真实密钥的 `.env.example`；
- Qoder Sites 静态项目展示页 `site-dist/index.html`（已创建，未发布）；
- 本开发记录与 README。

本阶段不包含：

- 真实 PowerContext 的产品截图或托管演示；
- 单元测试重跑结果（fixture 已修正，重跑待执行）；
- 离线语义脚本、端到端脚本与浏览器走查的执行结论；
- Qoder Sites 发布。

## 二、参考资料（只读）

从 `C:/Users/ZZZ/Desktop/数据库/26-OB-competition` 的 `origin/powercontext-2026` 分支读取（未修改该仓库）：

- `docs/en/docs/develop/api-quickstart.md`
- `openapi/powercontext.yaml`
- `docs/en/docs/develop/http-api.md`
- `docs/en/docs/workflows/sources.md`
- `docs/en/docs/workflows/scopes-and-access.md`
- `docs/en/docs/workflows/memory-and-handoff.md`
- `docs/en/docs/workflows/use-handoff-report.md`

另将 API Quick Start 作为只读参考保存在本项目的 `POWERCONTEXT_API_REFERENCE.md`，便于离线查阅。

确认到的关键行为：

- 一个 Scope 通过 `POST /v1/scopes` 创建，返回 `scope_id`；
- Scope 可通过 `GET /v1/scopes?query=&query_field=title&limit=&cursor=` 查询；
- Memory 通过 `POST /v1/memory/remember` 写入，文本上限 8192 UTF-8 字节；
- 检索使用 `POST /v1/memory/search`，命中包含 `citation`、`text`、`score`、`matched_by`，不包含 `kind`；
- 列出条目使用 `POST /v1/memory/entries/list`；无 Memory 时可能返回 404；
- 准备上下文使用 `POST /v1/context/prepare`，返回 `ready` 或 `empty`；
- 原始内容使用 `POST /v1/sources/content`（202），Source 可通过 `GET /v1/scopes/{id}/sources` 列出；
- 错误信封为 `{ "error": { "code", "message", "details" } }`，并带 `X-PowerContext-Request-ID`。

## 三、实际开发步骤

### 1. 需求拆解与数据建模

先确定“研究任务必须真正落在 PowerContext，而不是本地注册表”。最终映射：

| 应用概念 | PowerContext 资源 |
| --- | --- |
| 研究任务 | 一个 Scope |
| 实验观察 / 决策 / 待办 / 资料 | Memory 条目 |
| 资料证据 | Source（ID 为 `rr-link-<entryId>`） |
| 任务列表 | Scope 查询 + 标题前缀过滤 |
| 搜索 | `/v1/memory/search` |
| 交接 | Memory 列表 + Sources + `/v1/context/prepare` |

### 2. 解决 PowerContext 数据模型的三个空缺

1. **Memory 没有创建时间**：把 ISO 时间写入 `kind`，格式为 `research-relay/<type>/<ISO>`。
2. **搜索命中没有 `kind`**：搜索后调用 `/v1/memory/entries/list`，按 `entry_id` 补齐类型与时间；补齐失败只产生警告，不伪造类型。
3. **原始链接需要可核验证据**：先写 Memory，再写 Source；Source ID 用 `rr-link-<entryId>`，详情读取时按 ID 关联回条目。

### 3. 后端实现

- `src/domain.js`：输入清理、URL 安全、字节上限、Scope/Memory 映射、统计、排序。
- `src/powercontext.js`：请求封装、超时、Request ID、错误分类。
  - 网络不可达 / 超时 / 上游 503 → `503 powercontext_unavailable`，`details.noLocalFallback = true`；
  - 401/403 → `502 powercontext_auth_failed`；
  - 404/409/413/422 保留语义，其余映射到 502。
- `src/research-service.js`：
  - 每个任务请求都读取 Scope 并校验标题前缀 `[实验续航]`，拒绝访问其他 Scope；
  - 创建 Scope 后再次校验返回值归属；
  - 写入资料时若 Memory 成功但 Source 失败，返回警告而不是伪造成功；
  - 搜索、交接均调用真实 PowerContext 接口。
- `src/app.js`：`node:http` 路由、128KB 请求体限制、JSON Content-Type 校验、CSP 与安全头、静态资源路径穿越防护、请求 ID。
- `src/index.js`：加载项目本地 `.env`，启动与优雅关闭；日志不输出令牌值。

### 4. 前端实现

- `public/index.html` + `public/styles.css` + `public/app.js`。
- 三栏桌面布局、平板双栏、移动端单栏；无框架、无内联脚本/样式。
- 四种记录类型切换；资料类型单独校验链接；8192 字节计数提示。
- `#/task/<scopeId>` 哈希路由，刷新后重新从 API 读取任务。
- 搜索高亮使用 DOM 节点构造，不使用 `innerHTML`。
- 交接摘要支持复制与下载；页面同时展示 Memory 引用与 Source 证据。
- 服务状态卡片与离线横幅；离线时禁用写入并提供重试。

### 5. 编写测试与验证脚本

- `test/unit.test.js`：不依赖网络和 PowerContext，覆盖领域逻辑、摘要、配置与客户端错误映射。
- `test/integration.powercontext.test.js`：默认跳过；设置 `RUN_POWERCONTEXT_INTEGRATION=1` 后连接真实服务，验证双任务隔离、四类记录、Source、检索、交接、非实验 Scope 拒访和重启恢复。
- `scripts/verify-offline.mjs`：使用不可达端口验证 503 语义与“无本地降级”声明。
- `scripts/verify-e2e.mjs`：真实服务端到端验证，逐步输出 `PASS`。

### 6. 代码复查与修正

开发过程中发现并修正了两处前端问题：

1. 搜索结果徽标使用了 `.type-badge` 的颜色变量，但 `.result-card` 未定义 `--entry-color` / `--entry-soft`，导致颜色可能缺失。已在 `public/styles.css` 为 `.result-card` 添加默认值与四类修饰类，并在 `public/app.js` 为结果卡片添加 `type-*` 类。
2. `submitEntry` 中存在无效判断 `updateCharCount() === undefined`，该函数永远返回 `undefined`，判断实际只检查请求体字节数。已改为先刷新计数，再明确检查请求体是否超过 20000 字节。

### 7. 真实验证与单元测试 fixture 修正

根据 2026-11-03 的评审反馈：

- 真实 PowerContext 服务已在本机 `localhost:8000` 运行。
- `RUN_POWERCONTEXT_INTEGRATION=1 npm run test:integration` **已通过**。集成测试覆盖双任务隔离、四类记录、Source 取证、PowerContext 检索、跨任务搜索无结果、交接引用、非实验续航 Scope 拒访，以及重启应用后重新从 PowerContext 读取。
- `npm test` 首次运行出现 3 个失败。原因不在实现：`test/unit.test.js` 的 `citation()` fixture 使用了扁平的 `artifact_id` / `revision`，而官方与真实 API 返回 `memory_ref: { family: "memory", artifact_id, revision }`。`normalizeEntry` 本身读取 `citation.memory_ref`，实现正确。
- 已把 fixture 改为真实契约，保留原有断言，没有放宽测试。重跑 `npm test` **尚未执行**，因此单元测试仍不标记为通过。
- 本轮仍只使用 Read/Write/Edit，没有运行 shell、安装、发布或 Git 操作；集成测试结果来自评审反馈。

## 四、本机环境事实

- 平台：Windows `10.0.26200`，x64。
- Shell：项目内 `bash`。
- Node.js：`v24.21.0`。
- Python：观察到 `3.14.6`。
- 已创建项目本地 `.venv`，并把 pip 升级到 `26.3`。
- 真实 PowerContext 服务由外部安装在 `localhost:8000` 运行。
- 真实服务集成测试已通过（评审反馈）。
- 单元测试已实际运行过一次，出现 3 个 fixture 契约失败；fixture 已修正，重跑尚未执行。
- 离线语义脚本、端到端脚本和浏览器手工走查尚无执行记录。
- 未截图，未提交或推送 Git，未发布 Qoder Sites。

## 五、验证状态（截至 2026-11-03）

| 验证项 | 命令 | 状态 | 说明 |
| --- | --- | --- | --- |
| 单元测试 | `npm test` | **失败后修正，待重跑** | 3 个失败均为 fixture 使用扁平 `artifact_id` / `revision`；真实 API 为 `memory_ref`。fixture 已修正，断言未放宽 |
| 离线语义 | `npm run verify:offline` | 未执行 | 不需要真实 PowerContext |
| 集成测试 | `RUN_POWERCONTEXT_INTEGRATION=1 npm run test:integration` | **已通过** | 真实 PowerContext 运行于 `localhost:8000` |
| 端到端脚本 | `npm run verify:e2e` | 未执行 | 需要真实服务在线 |
| 浏览器走查 | 手工 | 未执行 | 需要启动应用与服务 |
| 静态展示页 | `site-dist/index.html` | 已创建，未发布 | Qoder Sites 发布仍未执行 |

### 运行顺序（用于复现与补跑）

```bash
# 1. 重跑单元测试
npm test

# 2. 离线语义（无需 PowerContext）
npm run verify:offline

# 3. 真实 PowerContext 已在 localhost:8000 运行；
#    如需重新启动，在另一个终端执行：
powercontext server run

# 4. 连接真实服务的集成测试（本次已通过）
RUN_POWERCONTEXT_INTEGRATION=1 npm run test:integration

# 5. 端到端验证
npm run verify:e2e

# 6. 启动界面并手工走查
npm start
```

只有在上述命令实际执行并通过后，才能把状态改为“通过”。如果失败，应保留真实错误信息并修复，而不是修改测试预期来规避。

## 六、设计取舍

- **不引入本地缓存**：刷新体验依赖 PowerContext 的响应速度，但换来了“不会把本地副本误当持久化”的确定性。离线时的正确行为是明确报错。
- **不使用 npm 框架**：避免安装失败影响可复现性；代价是需要自己实现路由、静态服务与安全头。当前实现已覆盖路径穿越、CSP、请求体限制和 JSON 校验。
- **类型与时间写入 `kind`**：PowerContext Memory 不提供应用自定义字段；`kind` 是可检索的字符串字段，适合承载约定，但需要严格校验长度与格式。
- **Source 失败不阻断 Memory**：资料文本已经进入 PowerContext，Source 只是证据；返回警告可以让用户知道证据缺失，而不是重复写入。
- **健康检查返回 200**：界面需要展示“PowerContext 离线”状态；如果 `/api/health` 本身返回 503，前端只能显示通用错误，无法区分应用与上游。
- **任务隔离靠 Scope + 标题前缀**：Scope 本身不是访问控制；标题前缀校验只能防止误访问本应用之外或不属于研究任务的 Scope，不能替代多租户鉴权。

## 七、已知风险与待验证点

1. **单元测试 fixture 契约（已修正，待验证）**：真实 API 的引用结构是 `citation.memory_ref: { family: "memory", artifact_id, revision }`，不是扁平的 `artifact_id` / `revision`。fixture 已按真实契约修改，需要重跑 `npm test` 确认。
2. **Source 最终一致性**：写入返回 202，Source 列表可能短暂不可见。验证脚本使用轮询等待，应用详情页不轮询；若真实服务延迟明显，界面可能需要刷新或增加重试。
3. **中文全文检索**：集成测试使用唯一的纯字母标记验证检索；中文查询在真实全文索引中的分词效果仍需在浏览器手工走查中确认。
4. **Python 3.14 兼容性**：部分 PowerContext 依赖可能没有 3.14 wheel，已文档化回退到 3.12/3.13。
5. **UI 未实测**：响应式布局、移动端交互、剪贴板降级路径均未经浏览器验证。
6. **Scope 清理**：验证会创建带唯一后缀的 Scope；应用未实现删除入口，演示环境需要自行管理。

## 八、后续步骤

1. 重跑 `npm test`，确认 fixture 修正后 3 个失败消失，并记录实际输出。
2. 运行 `npm run verify:offline`，验证无服务时的 503 与无本地降级语义。
3. 在已运行的 `localhost:8000` 上运行 `npm run verify:e2e`，记录实际输出。
4. 启动 `npm start`，在桌面、平板、移动端宽度下手工走查创建任务、四类记录、刷新恢复、搜索、交接、离线提示。
5. 将真实执行结果补充到本文与 README 的状态表。
6. 静态展示页 `site-dist/index.html` 已创建但未发布；在用户明确要求后再执行 Qoder Sites 发布。

## 九、文件清单

```text
public/index.html
public/styles.css
public/app.js
public/favicon.svg
src/app.js
src/config.js
src/domain.js
src/env.js
src/errors.js
src/handoff.js
src/index.js
src/powercontext.js
src/research-service.js
test/unit.test.js
test/integration.powercontext.test.js
scripts/verify-offline.mjs
scripts/verify-e2e.mjs
package.json
package-lock.json
.nvmrc
.env.example
.gitignore
requirements-powercontext.txt
README.md
DEVELOPMENT.md
POWERCONTEXT_API_REFERENCE.md
site-dist/index.html
```
