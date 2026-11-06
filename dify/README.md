# 倒走钟表旅店 · 时间账本与受约束叙事

时间是旅店的货币。你可以典当一段自己命名的记忆、购买钥匙、探索房间，也可以花时间赎回记忆后离店。余额、怀表、物品、抵押状态和结局由 Dify 原生 Code 节点结算。修订方案保留原生 LLM 的真实调用，让模型选择受约束的场景计划，再由 Code 校验并渲染最终剧情。

**第 6 版已于 2026-11-06 10:35（Asia/Shanghai）发布，官方待提测。** [公开应用入口](https://udify.app/workflow/WQb80SuLOoL9dWU3)的七轮新存档实测均完成正常十节点主流程；七次 PowerContext 精确读回均返回 HTTP 200，35 项存储、77 项确定状态和 36 项渲染检查共 148 项通过。本地边界回归另有 24/24 通过，不能与云端运行次数混计。[实际证据与复验入口](evidence/consistent-narrative-cloud/README.md)记录原生 LLM 输出、第五至第六轮运行 ID、渲染审计及覆盖范围。

此前第 5 版提交 `a9432d1a07f30bf84d33066fab31c31d87abf8f9` 获 0 分：第六轮账本已确认记忆赎回并成功回忆，模型正文却说仍在抵押柜中。[第 5 版历史证据](evidence/time-ledger-cloud/README.md)原样保留。第 6 版改为严格校验模型场景计划，再由 Code 渲染事实；本轮源码、可移植 DSL 与实际导入图的对应关系见新证据，工作区后续修改仍需重新导入、发布和核验。

## Dify 中的主流程

提交分支基于 `2026-competition-ecosystem`，资产入口为 `dify/`。[clockwork-inn.yml](clockwork-inn.yml) 是可导入工作流，[build_dsl.py](build_dsl.py) 将 [game_rules.py](game_rules.py) 和 [narrative.py](narrative.py) 嵌入 Dify Code 节点。动作识别、价格和状态约束以规则文件为准；计划校验与正文渲染以 `narrative.py` 为准。修订版保持原有正常回合的十节点主流程。

1. Start 收集玩家、存档名、存档码和行动；Code 为新游戏派发存档码，编码本轮读取请求。
2. HTTP 从真实 PowerContext 读取当前状态快照及与行动相关的历史。
3. Code 校验状态并结算时间收支、物品、记忆和房间条件，输出确定的账本、可用行动与当前事实。
4. IF/ELSE 将无需叙事的引导送到提示输出；可继续的回合进入原生 OpenAI `gpt-4o-mini` LLM 节点，真实生成四字段 JSON 场景计划。
5. 后续 Code 严格检查计划，从当前结算渲染正文，再将同一份正文和状态编码交给 HTTP 保存。确认 PowerContext 保存成功及 citation 后才输出剧情、账本、存档码与引用。非法计划在 HTTP 保存前抛出异常，本轮不写入存档。

模型仅能选择以下内容：`scene` 为 `brass/ink/rain/shadow`，`motif` 为 `hands/sand/steam/chime`；`callback_turn` 为 0 或当前事件列表中真实存在的过去轮次；`next_choice` 为本轮可用行动数组的有效整数下标。额外字段、任意正文、未知枚举、错误类型和越界引用均不作为有效计划接受。

这是**受约束的场景导演**：模型依据行动与前情选择氛围、历史呼应和下一步建议，影响最终场景组合，但不自由创作或更改事实句。历史引用明确标为过去记录，当前记忆归属、地点、余额和费用由 Code 渲染。模型任意自然语言正文不展示、不存档；该能力边界不是无限自由创作。计划校验结果与最终正文哈希可在渲染 Code 节点的 `audit` 输出中核查。

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
2. 导入 `dify/clockwork-inn.yml`，检查原生“掌柜选择场景与前情”LLM 节点，供应商为 `langgenius/openai/openai`，模型为 `gpt-4o-mini`。模型凭据在 Dify 工作区配置，不放到桥接环境或 YAML 中。
3. 将工作流环境变量 `bridge_url` 设置为桥接 HTTPS 地址，将 Secret 类型 `bridge_token` 设置为相同的 `BRIDGE_TOKEN`。默认 `host.docker.internal` 仅适用于可访问主机端口的本地 Docker 环境，不能直接用于 Dify Cloud。
4. 按下方新存档样例调试正常回合和引导分支，检查原生 LLM 的实际 JSON 输出、Code 校验和正文、HTTP 保存及公开结果。另验非法计划被拒绝且保存节点不执行。保存草稿后再 Publish，并核验实际发布编号；导入草稿不会自动更新已发布版本。

调整规则或渲染器后运行 `python dify/build_dsl.py` 重新生成 DSL，再导入、验证与发布；`dify/requirements.txt` 已固定 `PyYAML==6.0.3`。本地一致性检查入口为 `python -m unittest discover -s dify -p test_narrative_consistency.py -v`；本地检查和云端实际运行分别记录。模型额度不足、服务不可用或计划不合法时，本轮应明确失败，不把本地默认计划伪装为真实模型输出。

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
| `进入旧信室` / `进入回声室` | 从别处进入分别 12 / 15 分钟，需要钥匙；初次进入分别获得未寄出的信 / 回声铃。已在同一房间时继续查看免费，下一步提示也须显示免费 |
| `结账离店` | 免费结束该存档，未赎回的记忆留在旅店，之后不能继续交易 |

房间重复赠物、余额不足和未持钥匙均由 Code 规则判定。修订方案中模型只选择已限定的场景计划，事实正文由 Code 生成；验收仍需分别核查规则、最终正文、下一步建议和实际存档，不能只检查节点成功或保存成功。

## 新例重放与实测检查

第 6 版已使用新玩家 `ledger-guard-20261106`、存档名 `station-whistle-v3` 完成下表七轮，账本与预期相符；第六轮正文明确记忆归玩家持有、无需再次赎回。独立重放请使用未使用过的玩家和存档名，例如 `consistent-review-日期-序号`、`steam-letter-日期-序号`。第一轮存档码留空，成功后将 Dify 输出的码用于其余各轮。原始逐字行动见新证据的 `public-runs.json`。

| 轮次 | 输入行动 | 预期余额 / 怀表 | 预期结果 |
|---|---|---|---|
| 1 | `典当：蓝色车站的汽笛` | 65 分钟 / 12:00 | 记忆变为抵押，显示存档码与保存引用 |
| 2 | `回忆：蓝色车站的汽笛` | 65 分钟 / 12:00 | 延续第一轮的抵押状态，拒绝回忆，不扣费 |
| 3 | `买倒走钥匙` | 55 分钟 / 11:50 | 获得钥匙 |
| 4 | `进入旧信室` | 43 分钟 / 11:38 | 进入旧信室，首次获得未寄出的信 |
| 5 | `赎回：蓝色车站的汽笛` | 18 分钟 / 11:13 | 记忆赎回 |
| 6 | `回忆：蓝色车站的汽笛` | 16 分钟 / 11:11 | 可回忆该记忆，收取 2 分钟 |
| 7 | `结账离店` | 16 分钟 / 11:11 | 存档结局关闭，物品与剩余时间保留 |

云端另验证了错误存档码走六节点引导分支，跳过 LLM 与保存；第八轮离店后再进入雨声室仍保留旅店外、16 分钟和 11:11。混合记忆状态、陈旧错误正文、非法计划、重复交易、房间条件、同室免费及长名安全拒绝由本地 24 项回归覆盖。模型或存储服务故障、重启续玩及并发重试未在本轮云端验证，不能据此声明通过。

保留原始 PowerContext 数据并启动本地服务后，可在仓库根目录复验实际七轮记录。输出另存临时目录，避免覆盖提交证据：

```powershell
New-Item -ItemType Directory -Force .runtime | Out-Null
.\.runtime\dify-venv\Scripts\python.exe dify/verify_cloud_evidence.py scp_52fvt62vccv5xrg11ejjgt39b0 dify/evidence/consistent-narrative-cloud/public-runs.json --output .runtime/dify-cloud-evidence-recheck.json
```

该命令需要包含本次 scope 与 citation 的原始数据库；全新空库无法读回这些记录。独立复现须先跑自己的七轮并记录对应 scope 与引用。脚本比较实际存储、重放确定规则并复现受约束渲染，不独立证明云端模型调用；原生调用与 token 用量由 Dify 日志和截图佐证。

## 证据范围

- [consistent-narrative-cloud/README.md](evidence/consistent-narrative-cloud/README.md)：第 6 版真实七轮运行、原生 LLM 与渲染证据、148 项一致性检查和本地 24 项回归；已发布，官方待提测。
- [time-ledger-cloud/README.md](evidence/time-ledger-cloud/README.md)：已被否决的第 5 版历史记录，保留第六轮错误正文、账本及原始存储比对，不能证明新版本通过。
- [dify-cloud-runs/README.md](evidence/dify-cloud-runs/README.md)：保留 V1 银雨七号两轮真实 Dify 执行证据。它证明旧版流程曾运行，不能证明 V2 规则或原生 LLM 已运行。
- [cloud-workflow-recovery.json](evidence/cloud-workflow-recovery.json)：V1 外部新 Python 进程读回及玩家隔离验证，不是 V2 引擎节点日志或存档码验证。
- [powercontext-integration.json](evidence/powercontext-integration.json)：使用 synthetic story text 的真实 PowerContext 存储测试，不是实际模型生成或 Dify 执行证据。
- [cloud-run-notes.md](evidence/cloud-run-notes.md)：2026-11-03 历史操作说明，包含当时的叙事措辞问题，按原样保留。
