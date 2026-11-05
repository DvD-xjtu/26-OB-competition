# 时间账本 · Dify Cloud 第 5 版实测

2026-11-05 北京时间，从[公开作品](https://udify.app/workflow/WQb80SuLOoL9dWU3)以新玩家 `ledger-review-20261105`、新存档 `station-whistle` 实跑。工作流版本 ID 为 `25855b9d-0b00-4f55-9b0e-be31344814a9`。复验时从新的玩家与存档开始，保留第一轮发放的存档码。[安装与重放步骤](../../README.md)

Dify Code 节点计算余额、倒走钟、物品、门锁、记忆抵押和离店状态。IF/ELSE 选择继续剧情或只显示引导。正常回合由 Dify 原生 `gpt-4o-mini` LLM 节点根据规则输出写剧情。两个 HTTP 节点只连接 PowerContext 的读取和保存接口。后端使用 PowerContext 的 SQLite 持久化适配器。

| 轮次 | 行动 | 实际余额 | 实际规则结果 |
|---|---|---:|---|
| 1 | 典当蓝色车站汽笛的记忆 | 65 | 获得 20 分钟，记忆抵押。 |
| 2 | 回忆蓝色车站汽笛 | 65 | 读取首轮状态，拒绝回忆已抵押的记忆，余额保持。 |
| 3 | 买倒走钥匙 | 55 | 扣 10 分钟，钥匙进入物品栏。 |
| 4 | 进入旧信室 | 43 | 钥匙满足门锁条件，扣 12 分钟。 |
| 5 | 赎回蓝色车站汽笛 | 18 | 扣 25 分钟，记忆恢复可用。 |
| 6 | 回忆蓝色车站汽笛 | 16 | 扣 2 分钟，恢复后的记忆可以回忆。 |
| 7 | 结账离店 | 16 | 游戏处于旅店外，结局持久化。 |

[公开七轮输入、输出和存档引用](public-runs.json)记录了每轮的完整成功节点、可见剧情和账本。PowerContext 的七条存档均按同一 scope 和各轮 citation 精确读回，HTTP 200。动作、引用、余额和剧情与公开结果一致。剧情比对忽略公开页面拆分段落产生的空白。余额逐条满足 `45 + earned - spent`。[PowerContext 精确读回记录](powercontext-exact-reads.json)

| 云端记录 | Dify `workflow_run_id` | 实际节点与模型用量 | 证据 |
|---|---|---|---|
| 17:45:08 首轮典当 | `010ae17a-ec71-40fa-b2ab-0a98d8f2d21d` | 10 节点成功，977 tokens | [详情](turn1-console-details.jpg) · [追踪](turn1-console-trace.jpg) · [公开结果](turn1-public.jpg) |
| 17:46:00 抵押后回忆 | `6ac8b805-fc92-4116-a06a-8a72a7c16f83` | 10 节点成功，1418 tokens | [追踪](turn2-console-trace.jpg) · [原生 LLM 输入与输出](turn2-llm-node.jpg) |
| 17:48:44 结账 | `c9f0df69-bf08-4a0b-b4c2-fe1dc0f1f867` | 10 节点成功，1910 tokens | [追踪](turn7-console-trace.jpg) |
| 17:49:39 错误存档码 | `b9b44996-50b2-4db9-b697-59cd678d9f9b` | 6 节点成功，0 tokens | [引导分支追踪](wrong-code-console-trace.jpg) · [公开引导](wrong-code-public.jpg) |

[原生运行字段和节点耗时](dify-native-runs.json)来自 Dify Cloud 日志详情与追踪。首轮读取为空，保存节点返回 revision 1。最后一轮保存节点返回 revision 7。两个引用都能在公开输出与精确读回中核对。

同一玩家与存档名填入错误存档码时，PowerContext 读取返回独立 scope、空历史和空快照。Dify 条件分支只返回引导，没有运行 LLM 或保存节点。结账后又尝试进入雨声室时，规则拒绝变更地点与余额，仍在旅店外并保留 16 分钟。该次运行写入了拒绝回执作为第 8 轮。[公开分支和结账保护结果](public-guard-branches.json)
