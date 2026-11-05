# 五道生态题提交说明

提交仓库：<https://github.com/DvD-xjtu/26-OB-competition>，分支 **ecosystem-six-solutions**。此分支基于原 `2026-competition-ecosystem` 的 `9ec947ede8ac5aa245db42ffcc4e51a4a85ffdc6`，保留原有高德目录，main 为空不用于提测。最终 commit 以此分支远端最新提交为准，提交时固定完整 SHA。

| 题目 | 源码/材料 | 已完成的真实验证 |
|---|---|---|
| MiniMax | `minimax/README.md`、`minimax/evidence/seekdb-conditional-run1/` | 实际 seekdb 模块；真实 MiniMax 修改；原12项及新增5项测试通过；PowerContext 新进程读回；重新导入更新验证 |
| Qoder | `qoder/README.md`、`qoder/DEVELOPMENT.md`、`qoder/evidence/` | 实际 Qoder CLI 开发记录；21单测、真实 PowerContext 集成、13项端到端与离线检查；公开展示页 |
| StepFun | `stepfun/README.md`、`stepfun/REPORT.md`、`stepfun/evidence/` | 浏览器真实本地模型；seekdb 数据库内混合检索；FP32/INT8、WebGPU/WASM、批量与逐条、缓存加载、质量与延迟原始记录 |
| Dify | [V2 完整 DSL](dify/clockwork-inn.yml)、[规则源码](dify/game_rules.py)、[初始化与重放](dify/README.md)、[V2 证据入口](dify/evidence/time-ledger-cloud/README.md) | 公开第 5 版七轮实跑。Dify Code 结算，IF/ELSE 分流，原生 gpt-4o-mini 叙事，PowerContext 按引用精确读回 7/7 |
| ModelScope | `modelscope/contest-evidence-check/`、ZIP、`modelscope/PUBLICATION.md` | Skill 校验、脚本实际执行；公开发布，手动同步后核验两个文件 |

## 演示链接

- Qoder 项目展示：<https://research-relay-82rwgyi06a8.qoder.website>
- Qoder 完整本机应用：<http://127.0.0.1:4173>
- StepFun 本机应用：<http://127.0.0.1:8787>
- Dify 第 5 版时间账本：<https://udify.app/workflow/WQb80SuLOoL9dWU3>
- ModelScope Skill：<https://modelscope.cn/skills/Z18891798080/contest-evidence-check>

## 手动提测

对于显示 Commit/Branch 的提测表单，填写本仓库、上述分支及远端完整 commit。**ModelScope 例外：不克隆仓库，不填 Commit/Branch，只填写公开作品页面链接；SKILL.md 正文末尾必须包含平台读取的本队完整验证行。** 按实际表单添加对应目录说明与链接。Qoder 账号 UID 属于账号信息：CLI 登录状态不返回 UID，不要把 session_id/projectId 当作 UID；如表单要求，使用账号个人资料中的实际 UID。开发过程采用真实脱敏记录，未上传原始私有思考或密钥。

Dify V2“时间账本”将时间交易、钥匙与房间条件、记忆抵押和结局置于原生 Dify Code 节点，IF/ELSE 处理引导分支，原生 OpenAI `gpt-4o-mini` 节点依据已结算状态叙事，再通过 HTTP 节点保存到真实 PowerContext。仅采用 PowerContext 路线：演示服务的实际后端是官方 SQLite 适配器及持久化 `context.db`，没有使用 seekdb 存储。当前开发工作区已有 Dify Cloud 托管免费模型额度；独立复现需在自己的 Dify 工作区配置可用额度或已授权的 OpenAI provider，无需部署模型网关。

[Dify README](dify/README.md) 给出初始化、DSL 导入发布和七轮复验步骤。新游戏由 Dify 发放存档码，续玩须保留同一组玩家标识、存档名和码。实际输入输出、原生节点记录、存储引用和隔离验证见 [第 5 版运行证据](dify/evidence/time-ledger-cloud/README.md)。V1 的 [银雨七号云端记录](dify/evidence/dify-cloud-runs/README.md) 和旧存储测试作为历史保留。

Dify 的 PowerContext 桥接当前位于本机，通过临时 HTTPS 隧道服务云端；本机关闭或隧道退出后需重新启动并更新桥接地址、重新发布工作流，持续公开体验需要固定部署和持久化数据目录。Qoder 在线链接是项目展示页，完整交互应用按 README 启动。StepFun 是本机应用，评审可按 README 重现。

各题成绩以平台实际评审为准。StepFun 仅6文档冒烟质量集且 INT8 WebGPU 排序有下降。Dify 的规则结算和实际存档在第 5 版证据中逐轮列出，叙事措辞会随模型生成变化。

AMD 按用户要求暂不继续；已有独立分支 `amd-cagra-v5-opt` 保留，不作为这五题的提交分支，也不声称已完成 GPU 性能验证。
