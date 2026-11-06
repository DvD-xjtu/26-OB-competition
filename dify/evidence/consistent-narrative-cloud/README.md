# 第 6 版 · 受约束叙事的实际云端证据

**2026-11-06 10:35（Asia/Shanghai）已发布第 6 版，官方待提测。** 本目录记录真实 Dify Cloud 执行、PowerContext 精确读回和本地边界回归，不代表已获官方分数。[安装与重放步骤](../../README.md)

- 公开应用：<https://udify.app/workflow/WQb80SuLOoL9dWU3>
- Workflow ID：`29c1d125-27d3-49af-b353-24597a9b53ff`。
- 演示玩家：`ledger-guard-20261106`；存档名：`station-whistle-v3`；scope：`scp_52fvt62vccv5xrg11ejjgt39b0`。公开材料不包含存档码、桥接令牌或模型凭据。
- [发布截图](published-version6.jpg)和 [原生运行索引](dify-native-runs.json)记录版本与运行 ID。索引包含规则、渲染器、DSL 生成器和 `clockwork-inn.yml` 的源码哈希，并记录导入图与仓库可移植 DSL 图结构相同；云端环境使用实际桥接及 Secret，可移植文件使用占位地址和空 Secret。

第 5 版提交 `a9432d1a07f30bf84d33066fab31c31d87abf8f9` 因第六轮记忆状态与剧情相反获 0 分。[旧证据](../time-ledger-cloud/README.md)原样保留，其 7/7 精确读回不能证明剧情正确。以下均为第 6 版重新执行的记录。

## 架构与模型作用

正常回合为十节点：Start → 准备 Code → PowerContext 读取 HTTP → 规则 Code → IF/ELSE → 原生 LLM → 校验与渲染 Code → PowerContext 保存 HTTP → 确认 Code → End。引导分支跳过 LLM 和保存。

原生 OpenAI `gpt-4o-mini` 真实选择 `scene/motif/callback_turn/next_choice` 四字段 JSON 计划。[narrative.py](../../narrative.py)严格检查枚举、类型及引用范围，再从已结算状态生成场景、明确标为过去的回顾、当前事实、记忆归属与尚未执行的建议。LLM 作为受约束场景导演选择氛围和前情组合，不提供无限自由创作；自由模型正文不展示或存储。非法计划在 HTTP 保存前失败，不以默认计划冒充模型成功。

## 七轮云端运行与精确复验

[public-runs.json](public-runs.json)记录七轮行动、公开正文、账本、citation 和观察到的十个节点状态，七轮均为 10/10 成功。

| 轮次 | 实际输入 | 余额 / 怀表 | 当前结果 |
|---|---|---|---|
| 1 | 典当蓝色车站汽笛的记忆 | 65 分钟 / 12:00 | 记忆抵押 |
| 2 | 回忆蓝色车站汽笛 | 65 分钟 / 12:00 | 拒绝回忆，不扣费 |
| 3 | 买倒走钥匙 | 55 分钟 / 11:50 | 获得钥匙 |
| 4 | 进入旧信室 | 43 分钟 / 11:38 | 进入房间，获得未寄出的信 |
| 5 | 赎回蓝色车站汽笛 | 18 分钟 / 11:13 | 记忆已赎回 |
| 6 | 回忆蓝色车站汽笛 | 16 分钟 / 11:11 | 回忆成功，扣 2 分钟；记忆归玩家持有，无需再赎回 |
| 7 | 结账离店 | 16 分钟 / 11:11 | 位于旅店外，结局关闭，无记忆留在抵押柜 |

[cloud-evidence-verification.json](cloud-evidence-verification.json)按精确 citation 从真实 PowerContext 读回七轮，七次均 HTTP 200，引用 revision 严格增加。

| 检查类别 | 通过数 | 含义 |
|---|---:|---|
| 精确存储 | 35 | UTF-8 行动、最终正文、公开正文与对应存储记录一致 |
| 确定状态 | 77 | 生产规则重放、完整状态与七轮显式余额及归属预期一致 |
| 受约束渲染 | 36 | 精确复现规定渲染器输出，当前归属与正文模板一致 |
| 合计 | 148 | 三类逐项检查全部通过，不是 148 次云端运行 |

脚本没有调用另一个模型进行语义打分，也不独立证明云端模型调用或 token 用量。其 `recorded_*` 状态来自观察记录，`inferred_plan` 是从最终输出重建的计划；原生调用由下面的日志与截图佐证，第六轮另有直接捕获的实际模型输出。

## 第五至第六轮原生证据

时间均为 2026-11-06、Asia/Shanghai。

| 轮次 | 原生 workflow run ID | 开始时间 | 耗时 | token / 节点 |
|---|---|---|---:|---|
| 5 | `29b251aa-8898-4378-8739-2f943606ed83` | 10:40:42 | 2.987 秒 | 2199 / 10 个成功 |
| 6 | `ea7d8870-3e41-46f2-a6c4-00c3bfddc310` | 10:41:02 | 3.568 秒 | 2119 / 10 个成功 |

第五轮见 [详情](turn5-console-details.txt)、[追踪文本](turn5-console-trace.txt)和 [追踪截图](turn5-console-trace.jpg)。第六轮见 [详情](turn6-console-details.txt)、[控制台追踪](turn6-console-trace.jpg)、[公开正文](turn6-public-story.jpg)和 [公开节点](turn6-public-nodes.jpg)。

第六轮“掌柜选择场景与前情”原生 LLM 的直接输出记录在 [turn6-native-llm.txt](turn6-native-llm.txt)：

```json
{"scene":"ink","motif":"hands","callback_turn":5,"next_choice":1}
```

[渲染节点](turn6-render-node.txt)和 [审计输出](turn6-render-audit.txt)确认 `renderer=bounded-plan-v1`、`validated=true`、`model_prose_used=false`、`state_turn=6`、`balance=16`，该记忆状态为 `redeemed`。最终正文 SHA-256 为 `29fb250c8f76b6d7254d3301665fe745d7598ac29073113ea173b71c574fa50b`。正文将第五轮赎回标为过去记录，并另列本轮回忆成功、费用 2 分钟、当前记忆归玩家持有且无需再次赎回，修复旧版否决点。

## 额外保护与覆盖边界

- 错误存档码：[文本](wrong-code.txt)、[截图](wrong-code.jpg)显示六个引导分支节点成功，提示核对三项续玩信息，LLM 与保存节点未执行。
- 离店后再进房：[post-checkout.json](post-checkout.json)记录第八轮“进入雨声室”；十节点成功，但规则拒绝新行动，仍在旅店外、16 分钟、11:11，既有结局保留。该轮有新的保存引用，不声称完全不写记录。
- 本地边界：[local-regression.json](local-regression.json)记录 24/24 通过，覆盖混合记忆归属、陈旧错误正文、非法计划类型与索引、无钥匙、余额不足、重复购买/典当、已赎回记忆不可再扣赎回费、同室免费且不重赠、过长记忆名安全拒绝等。本地使用合成输入，不是 24 次原生云端运行。

本轮未在云端做模型/存储服务故障注入、非法计划注入、数据目录重启续玩或并发重试，也未将全部本地多记忆和边界案例逐一搬到云端。不将这些未覆盖项目写成已通过。演示依赖持续运行的本机 PowerContext、桥接和临时 HTTPS 隧道，持续公开体验仍需固定部署。

## 可复验命令

按 [安装说明](../../README.md)安装依赖，在仓库根目录执行本地回归：

```powershell
.\.runtime\dify-venv\Scripts\python.exe -m unittest discover -s dify -p test_narrative_consistency.py -v
```

保留原始 PowerContext 数据并在 `127.0.0.1:8000` 启动服务后，复验本目录七轮记录；指定临时输出，避免覆盖已提交证据：

```powershell
New-Item -ItemType Directory -Force .runtime | Out-Null
.\.runtime\dify-venv\Scripts\python.exe dify/verify_cloud_evidence.py scp_52fvt62vccv5xrg11ejjgt39b0 dify/evidence/consistent-narrative-cloud/public-runs.json --output .runtime/dify-cloud-evidence-recheck.json
```

[verify_cloud_evidence.py](../../verify_cloud_evidence.py)需要原始数据库中存在对应 scope 与 citation。全新空库不能读回旧引用；独立复现请用未使用的玩家/存档名完成相同七轮，并记录自己的 scope、正文和 citation。此脚本仅访问本地 PowerContext，核验存储、确定规则和受约束渲染，不替代 Dify 原生节点日志。源码哈希、执行方式与范围分别保存在相应 JSON 中。
