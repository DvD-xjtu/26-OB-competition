# 倒走钟表旅店 · 时间账本（V2）

时间是旅店的货币。你可以典当一段自己命名的记忆、购买钥匙、探索房间，也可以花时间赎回记忆后离店。余额、怀表、物品、抵押状态和结局由 Dify 原生 Code 节点结算，原生 LLM 节点只依据结算结果描写场景。

时间账本已发布为原 Dify 应用的第 5 版。公开七轮账本、原生 LLM 与条件分支记录、以及 PowerContext 精确读回见 [时间账本云端运行记录](evidence/time-ledger-cloud/README.md)。[打开公开应用](https://udify.app/workflow/WQb80SuLOoL9dWU3)

## Dify 中的主流程

提交分支基于 `2026-competition-ecosystem`，资产入口为 `dify/`。[clockwork-inn.yml](clockwork-inn.yml) 是可导入工作流，[build_dsl.py](build_dsl.py) 将 [game_rules.py](game_rules.py) 的规则代码嵌入 Dify Code 节点。动作识别、价格和状态约束以该规则文件为准。

1. Start 收集玩家、存档名、存档码和行动；Code 为新游戏派发存档码，编码本轮读取请求。
2. HTTP 从真实 PowerContext 读取当前状态快照及与行动相关的历史。
3. Code 校验状态并结算时间收支、物品、记忆和房间条件，输出确定的账本及叙事提示。
4. IF/ELSE 将无需叙事的引导送到提示输出；可继续的回合进入原生 LLM 节点。该节点使用 OpenAI `gpt-4o-mini`，世界设定和已结算状态来自工作流内的规则节点。
5. Code 将规则状态和模型正文编码，HTTP 写入 PowerContext；确认保存成功和 citation 后才输出剧情、账本、存档码与引用。

V2 选择 **PowerContext 路线**。配套 `service.py` 在 V2 图中只承担 `/recall` 与 `/remember` 存储接口；模型调用和游戏结算不经过外部剧情接口。旧版兼容的 `/narrate`、`STORY_API_KEY` 和 `QODER_CLI` 不属于 V2 工作流，也不需要为 V2 配置模型网关。

## 配置与运行

以下命令均在本仓库根目录执行，需要 Git、Python 3.11+ 和 Dify 工作区。建议使用 Python 3.12 创建独立环境。Windows PowerShell 示例：

```powershell
python -m venv .runtime/dify-venv
.\.runtime\dify-venv\Scripts\python.exe -m pip install -r qoder/requirements-powercontext.txt -r dify/requirements.txt
.\.runtime\dify-venv\Scripts\python.exe tools/powercontext_server.py --workspace .runtime/clockwork-context --port 8000
```

`qoder/requirements-powercontext.txt` 是仓库共用的依赖锁定入口，安装比赛源码 `c92dc0fd986d42cbdebae14670755e04be2c4f8f` 的 `powercontext[server]`。只安装 `dify/requirements.txt` 不会安装 PowerContext。Linux/macOS 将 Python 可执行路径替换为 `.runtime/dify-venv/bin/python`。

**本演示使用真实 PowerContext 服务和其 SQLite 持久化适配器，未使用 seekdb 作为存储后端。** 启动器明确使用 `SQLiteConfig`，数据文件为 `.runtime/clockwork-context/context.db`，同目录另有调度器文件 `scheduler.db`。停止或重启服务时保留整个目录，才能继续已有存档；清空目录会丢失本地记忆。服务只监听 `127.0.0.1:8000`，此本地启动器未启用 PowerContext 鉴权。

保持终端运行，另开终端检查服务：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
```

按 [.env.example](.env.example) 设置启动桥接终端的进程环境变量，程序不自动读取 `.env`。PowerShell 使用 `$env:变量名 = '值'`，Linux/macOS 使用 `export 变量名='值'`。V2 需要以下配置：

| 变量 | 配置 |
|---|---|
| `POWERCONTEXT_URL` | 上述本地服务为 `http://127.0.0.1:8000` |
| `POWERCONTEXT_TOKEN` | 本地启动器留空；连接自行部署的鉴权服务时设置其令牌 |
| `BRIDGE_TOKEN` | 自行生成的随机访问令牌，必须与 Dify Secret 一致；不要写入仓库 |
| `BRIDGE_HOST`、`BRIDGE_PORT` | 默认 `127.0.0.1` 与 `8766` |

```powershell
.\.runtime\dify-venv\Scripts\python.exe dify/service.py
```

Dify Cloud 需要能访问此桥接的 HTTPS 地址。临时复现可使用已安装的 Cloudflare 客户端：

```powershell
cloudflared tunnel --url http://127.0.0.1:8766
```

保持 PowerContext、桥接和隧道进程运行。临时隧道没有长期可用性保证，重启后地址可能变化；持续公开体验应使用固定 HTTPS 地址和持久化部署。仅桥接端口对 Dify 开放，不把未鉴权的 PowerContext 端口直接暴露到公网。

在 Dify 导入及发布：

1. 在自己的工作区安装、授权 OpenAI 模型供应商，确保 `gpt-4o-mini` 可用。当前开发工作区已配置 Dify Cloud 托管免费额度；复现者需使用自己工作区的可用额度或已授权模型凭据，导入 DSL 不会转移额度或密钥。
2. 导入 `dify/clockwork-inn.yml`，检查原生“掌柜叙事”LLM 节点，供应商为 `langgenius/openai/openai`，模型为 `gpt-4o-mini`。模型凭据在 Dify 工作区配置，不放到桥接环境或 YAML 中。
3. 将工作流环境变量 `bridge_url` 设置为桥接 HTTPS 地址，将 Secret 类型 `bridge_token` 设置为相同的 `BRIDGE_TOKEN`。默认 `host.docker.internal` 仅适用于可访问主机端口的本地 Docker 环境，不能直接用于 Dify Cloud。
4. 按下方新存档样例调试正常回合和引导分支，检查 Code、IF/ELSE、LLM、存储写入及输出。保存草稿后再 Publish；导入草稿不会自动更新已发布版本。

调整规则后可安装 PyYAML 并运行 `python dify/build_dsl.py` 重新生成 DSL，再导入、验证与发布。模型额度或服务不可用时应修复依赖后重试，不用固定故事代替真实模型输出。

## 存档与动作

新游戏填写 `player`（玩家标识）、`chapter`（存档名）和 `action`（行动），**将 `save_code` 留空**。Dify 派发存档码；成功保存后在输出中保留它。续玩必须同时提供原来的 **玩家标识、存档名、存档码**，每轮只改变行动。再次留空会创建新游戏，不会按同名玩家自动恢复旧进度。

存档码是访问存档的凭据，持有码并知道对应名称的人可以续玩，应自行保管。不要公开私人存档码；公开证据只使用演示存档。本方式提供存档访问能力，不等同于实名账号认证。格式错误或无法匹配的续玩信息应返回错误或引导，不应读取其他存档或悄悄创建替代存档。

每次输入一个明确行动，以下规则摘要以 [game_rules.py](game_rules.py) 为准：

| 行动 | 规则 |
|---|---|
| `看怀表` | 初始余额 45 分钟、怀表 12:00；看表免费，钟面仅随实际消费倒走 |
| `典当：蓝色车站的汽笛` | 获得 20 分钟，该记忆抵押期间无法回忆；重复典当同一抵押记忆不重复支付 |
| `赎回：蓝色车站的汽笛` | 支付 25 分钟恢复记忆，余额不足时拒绝且不扣费 |
| `回忆：蓝色车站的汽笛` | 抵押时拒绝且免费；持有或已赎回时花 2 分钟回忆 |
| `买倒走钥匙` | 10 分钟，重复购买不扣费 |
| `进入雨声室` | 8 分钟，不需要钥匙；初次进入获得雨声玻璃珠 |
| `进入旧信室` / `进入回声室` | 分别 12 / 15 分钟，需要钥匙；初次进入分别获得未寄出的信 / 回声铃 |
| `结账离店` | 免费结束该存档，未赎回的记忆留在旅店，之后不能继续交易 |

房间重复赠物、余额不足和未持钥匙均由 Code 规则判定。模型负责描写，不能改变已经确定的数值或将被拒绝的行为写成交易成功；面板与叙事是否一致也属于待检验内容。

## 新例重放与预期检查

下表是公开第 5 版七轮实测的账本，也是复验的预期值。使用未使用过的玩家和存档名，例如 `ledger-review-日期-序号`、`steam-letter-日期-序号`。第一轮存档码留空，成功后将 Dify 输出的码用于其余各轮。

| 轮次 | 输入行动 | 预期余额 / 怀表 | 预期结果 |
|---|---|---|---|
| 1 | `典当：蓝色车站的汽笛` | 65 分钟 / 12:00 | 记忆变为抵押，显示存档码与保存引用 |
| 2 | `回忆：蓝色车站的汽笛` | 65 分钟 / 12:00 | 延续第一轮的抵押状态，拒绝回忆，不扣费 |
| 3 | `买倒走钥匙` | 55 分钟 / 11:50 | 获得钥匙 |
| 4 | `进入旧信室` | 43 分钟 / 11:38 | 进入旧信室，首次获得未寄出的信 |
| 5 | `赎回：蓝色车站的汽笛` | 18 分钟 / 11:13 | 记忆赎回 |
| 6 | `回忆：蓝色车站的汽笛` | 16 分钟 / 11:11 | 可回忆该记忆，收取 2 分钟 |
| 7 | `结账离店` | 16 分钟 / 11:11 | 存档结局关闭，物品与剩余时间保留 |

云端另验了错误存档码和结账后再进房两条路径。前者只走引导，跳过模型与保存。后者保留结局和余额并保存拒绝回执。独立复验也可检查无钥匙进房、重复交易、桥接与 PowerContext 重启恢复、保存失败，以及相同轮次并发。实际云端结果和覆盖范围以证据索引为准。

## 证据范围

- [time-ledger-cloud/README.md](evidence/time-ledger-cloud/README.md)：V2 公开七轮记录、原生 Code、IF/ELSE 和 LLM 追踪、PowerContext 精确读回、存档码隔离和离店保护。
- [dify-cloud-runs/README.md](evidence/dify-cloud-runs/README.md)：保留 V1 银雨七号两轮真实 Dify 执行证据。它证明旧版流程曾运行，不能证明 V2 规则或原生 LLM 已运行。
- [cloud-workflow-recovery.json](evidence/cloud-workflow-recovery.json)：V1 外部新 Python 进程读回及玩家隔离验证，不是 V2 引擎节点日志或存档码验证。
- [powercontext-integration.json](evidence/powercontext-integration.json)：使用 synthetic story text 的真实 PowerContext 存储测试，不是实际模型生成或 Dify 执行证据。
- [cloud-run-notes.md](evidence/cloud-run-notes.md)：2026-11-03 历史操作说明，包含当时的叙事措辞问题，按原样保留。
