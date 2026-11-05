# Dify Cloud 双轮实测 · 银雨七号

2026-11-05 北京时间，在[已发布的倒走钟表旅店](https://udify.app/workflow/WQb80SuLOoL9dWU3)使用全新玩家 `dify-review-20261105` 和存档 `silver-rain-07` 实跑两轮。Dify 负责从输入到输出的九个节点，PowerContext 保存第一轮交易并在第二轮提供历史。

| 轮次 | 开始时间 | Dify 原生 `workflow_run_id` | 实际结果 |
|---|---|---|---|
| 1 | 15:08:10 | `549ab8f0-0f87-4ca4-8a41-7ebeeac0ea4f` | 33.987 s，9/9 节点成功。读取空历史，换得刻有“银雨七号”的倒走怀表，保存 revision 1。 |
| 2 | 15:09:32 | `b78d768e-da0f-41bd-80b3-d07343af95c7` | 37.725 s，9/9 节点成功。输入只提“刚才换来的物品”，召回首轮引用，复述刻字和“星期二午后雨声”，保存 revision 2。 |

| 轮次 | Dify 控制台 | 公开作品结果 | 数据与模型验证 |
|---|---|---|---|
| 1 | [运行 ID 和输入截图](silver-rain-turn1-console-details.jpg) · [九节点追踪截图](silver-rain-turn1-console-trace.jpg) · [控制台字段 JSON](silver-rain-turn1-dify.json) | [首轮交易与存档截图](silver-rain-turn1-public.jpg) | [PowerContext 精确读回与 Qoder 会话核验](silver-rain-turn1-storage-model.json) |
| 2 | [运行 ID 和输入截图](silver-rain-turn2-console-details.jpg) · [九节点追踪截图](silver-rain-turn2-console-trace.jpg) · [控制台字段 JSON](silver-rain-turn2-dify.json) | [次轮回忆与存档截图](silver-rain-turn2-public.jpg) | [PowerContext 精确读回、模型输入和隔离核验](silver-rain-turn2-storage-model.json) |

两个运行 ID 来自 Dify Cloud 日志详情的 `sys.workflow_run_id`，两轮属于同一已发布工作流 `a823f515-9e26-42db-8cc9-7cd12182efab`。截图记录了详情页和追踪页。JSON 整理了详情和追踪里实际可见的字段，包含节点耗时、三个 HTTP 节点的状态及选定输出。公开页面返回的 citation、Dify 保存节点的 citation 和 PowerContext 按引用读回的 citation 在各轮内完全相同。

第二轮的 Dify 读取节点返回首轮存档条目，模型收到的历史含同一条完整引用。两轮生成节点返回的 `response_id` 分别与真实 Qoder CLI 会话一致。配套服务选择 MiniMax-M3.1-Flash，推理通过 HTTP 节点外接，Dify 控制台在这两轮记录的内置 token 计数为 0。通过 PowerContext `POST /v1/memory/entries/get` 分别读回两轮有效存档，核对动作和模型输出，剧情与对应 Qoder 输出逐字节相同。相同玩家另开新存档的读取返回独立 scope 和空历史。

按[初始化与双轮体验](../../README.md)可使用新玩家和存档复验。核对第二轮输出是否回忆起刻字与代价，再核对第二轮的读取、生成和保存三个节点，以及与第一轮相同的 scope。原始 HTTP 请求头、鉴权值与完整模型历史均已省略，记录保留实际测试输入、输出与调用引用。
