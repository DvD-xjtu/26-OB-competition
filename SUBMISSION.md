# 五道生态题提交说明

提交仓库：<https://github.com/DvD-xjtu/26-OB-competition>，分支 **ecosystem-six-solutions**。此分支基于原 `2026-competition-ecosystem` 的 `9ec947ede8ac5aa245db42ffcc4e51a4a85ffdc6`，保留原有高德目录，main 为空不用于提测。最终 commit 以此分支远端最新提交为准，提交时固定完整 SHA。

| 题目 | 源码/材料 | 已完成的真实验证 |
|---|---|---|
| MiniMax | `minimax/README.md`、`minimax/evidence/seekdb-conditional-run1/` | 实际 seekdb 模块；真实 MiniMax 修改；原12项及新增5项测试通过；PowerContext 新进程读回；重新导入更新验证 |
| Qoder | `qoder/README.md`、`qoder/DEVELOPMENT.md`、`qoder/evidence/` | 实际 Qoder CLI 开发记录；21单测、真实 PowerContext 集成、13项端到端与离线检查；公开展示页 |
| StepFun | `stepfun/README.md`、`stepfun/REPORT.md`、`stepfun/evidence/` | 浏览器真实本地模型；seekdb 数据库内混合检索；FP32/INT8、WebGPU/WASM、批量与逐条、缓存加载、质量与延迟原始记录 |
| Dify | [完整 DSL](dify/clockwork-inn.yml)、[规则](dify/game_rules.py)、[计划渲染器](dify/narrative.py)、[初始化与重放](dify/README.md)、[第 6 版证据](dify/evidence/consistent-narrative-cloud/README.md) | 第 6 版已发布；七轮真实 Dify 十节点运行，PowerContext 七次 HTTP 200 精确读回，148 项一致性检查及本地 24/24 回归通过；官方待提测 |
| ModelScope | `modelscope/contest-evidence-check/`、ZIP、`modelscope/PUBLICATION.md` | Skill 校验、脚本实际执行；公开发布，手动同步后核验两个文件 |

## 演示链接

- Qoder 项目展示：<https://research-relay-82rwgyi06a8.qoder.website>
- Qoder 完整本机应用：<http://127.0.0.1:4173>
- StepFun 本机应用：<http://127.0.0.1:8787>
- Dify 应用入口：<https://udify.app/workflow/WQb80SuLOoL9dWU3>（第 6 版，2026-11-06 10:35 Asia/Shanghai 发布；官方待提测）
- ModelScope Skill：<https://modelscope.cn/skills/Z18891798080/contest-evidence-check>

## 手动提测

对于显示 Commit/Branch 的提测表单，填写本仓库、上述分支及远端完整 commit。**ModelScope 例外：不克隆仓库，不填 Commit/Branch，只填写公开作品页面链接；SKILL.md 正文末尾必须包含平台读取的本队完整验证行。** 按实际表单添加对应目录说明与链接。Qoder 账号 UID 属于账号信息：CLI 登录状态不返回 UID，不要把 session_id/projectId 当作 UID；如表单要求，使用账号个人资料中的实际 UID。开发过程采用真实脱敏记录，未上传原始私有思考或密钥。

Dify“时间账本”的修订方案保持十节点正常主流程：原生 Code 结算时间、物品、记忆和结局，IF/ELSE 分流，原生 OpenAI `gpt-4o-mini` 真实生成 `scene/motif/callback_turn/next_choice` 四字段计划，再由 Code 严格校验并从当前事实渲染最终正文。模型负责受约束的场景导演，不是无限自由创作；自由模型正文不展示或保存，非法计划抛异常并阻止本轮写入。随后 HTTP 节点保存同一份已渲染正文到真实 PowerContext。

仅采用 PowerContext 路线：演示服务的实际后端是官方 SQLite 适配器及持久化 `context.db`，没有使用 seekdb 存储。当前开发工作区已有 Dify Cloud 托管免费模型额度；独立复现需在自己的 Dify 工作区配置可用额度或已授权的 OpenAI provider，无需部署模型网关。

[Dify README](dify/README.md) 给出初始化、DSL 导入发布、七轮重放及 `verify_cloud_evidence.py` 复验命令。新游戏由 Dify 发放存档码，续玩须保留同一组玩家标识、存档名和码。第 6 版 workflow ID 为 `29c1d125-27d3-49af-b353-24597a9b53ff`；[实际证据](dify/evidence/consistent-narrative-cloud/README.md)包含七轮完整输出、第五至第六轮真实运行 ID、原生 LLM 四字段计划、Code 审计和公开截图，源码与 DSL 对应关系记录在 `dify-native-runs.json`。此前提交 `a9432d1a07f30bf84d33066fab31c31d87abf8f9` 获 0 分：第六轮状态已赎回记忆，正文却说仍抵押。第 5 版原始输出、引用和失败说明保留在 [历史目录](dify/evidence/time-ledger-cloud/README.md)。V1 的 [银雨七号记录](dify/evidence/dify-cloud-runs/README.md) 和旧存储测试同样只作历史证据。

Dify 的 PowerContext 桥接当前位于本机，通过临时 HTTPS 隧道服务云端；本机关闭或隧道退出后需重新启动并更新桥接地址、重新发布工作流，持续公开体验需要固定部署和持久化数据目录。Qoder 在线链接是项目展示页，完整交互应用按 README 启动。StepFun 是本机应用，评审可按 README 重现。

各题成绩以平台实际评审为准。StepFun 仅6文档冒烟质量集且 INT8 WebGPU 排序有下降。Dify 第 6 版的 148 项由 35 项精确存储、77 项确定状态、36 项受约束渲染检查构成，不是 148 次云端运行或通用语义评审。错误存档码引导和离店后保护已云端验证；混合记忆、非法计划等边界属于本地 24 项测试，服务故障、重启及并发重试未在本轮云端验证。第 5 版的 7/7 读回仅证明当时错误正文被一致保存，不能证明剧情正确；第 6 版已发布和实测，也尚不代表官方得分。

AMD 按用户要求暂不继续；已有独立分支 `amd-cagra-v5-opt` 保留，不作为这五题的提交分支，也不声称已完成 GPU 性能验证。
