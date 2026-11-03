# 五道生态题提交说明

提交仓库：<https://github.com/DvD-xjtu/26-OB-competition>，分支 **ecosystem-six-solutions**。此分支基于原 `2026-competition-ecosystem` 的 `9ec947ede8ac5aa245db42ffcc4e51a4a85ffdc6`，保留原有高德目录，main 为空不用于提测。最终 commit 以此分支远端最新提交为准，提交时固定完整 SHA。

| 题目 | 源码/材料 | 已完成的真实验证 |
|---|---|---|
| MiniMax | `minimax/README.md`、`minimax/evidence/seekdb-conditional-run1/` | 实际 seekdb 模块；真实 MiniMax 修改；原12项及新增5项测试通过；PowerContext 新进程读回；重新导入更新验证 |
| Qoder | `qoder/README.md`、`qoder/DEVELOPMENT.md`、`qoder/evidence/` | 实际 Qoder CLI 开发记录；21单测、真实 PowerContext 集成、13项端到端与离线检查；公开展示页 |
| StepFun | `stepfun/README.md`、`stepfun/REPORT.md`、`stepfun/evidence/` | 浏览器真实本地模型；seekdb 数据库内混合检索；FP32/INT8、WebGPU/WASM、批量与逐条、缓存加载、质量与延迟原始记录 |
| Dify | `dify/clockwork-inn.yml`、`dify/README.md`、`dify/evidence/` | Dify Cloud 导入，两轮真实模型剧情和记忆存档；新进程读回、玩家隔离；已发布版本1 |
| ModelScope | `modelscope/contest-evidence-check/`、ZIP、`modelscope/PUBLICATION.md` | Skill 校验、脚本实际执行；公开发布，手动同步后核验两个文件 |

## 演示链接

- Qoder 项目展示：<https://research-relay-82rwgyi06a8.qoder.website>
- Qoder 完整本机应用：<http://127.0.0.1:4173>
- StepFun 本机应用：<http://127.0.0.1:8787>
- Dify 发布应用：<https://udify.app/workflow/WQb80SuLOoL9dWU3>
- ModelScope Skill：<https://modelscope.cn/skills/Z18891798080/contest-evidence-check>

## 手动提测

在对应生态题的“立即提测”中填写本仓库、上述分支及远端完整 commit，按表单添加对应目录说明与链接。Qoder 账号 UID 属于账号信息：CLI 登录状态不返回 UID，不要把 session_id/projectId 当作 UID；如表单要求，使用账号个人资料中的实际 UID。开发过程采用真实脱敏记录，未上传原始私有思考或密钥。

Dify 演示后端当前位于本机，通过临时 HTTPS 隧道服务云端；本机关闭或隧道退出后需重新启动并更新桥接地址。Qoder 在线链接是项目展示页，完整交互应用按 README 启动。StepFun 是本机应用，评审可按 README 重现。

尚未获得平台评分，不能承诺满分。StepFun 仅6文档冒烟质量集且 INT8 WebGPU 排序有下降；Dify 开放式叙事样例存在措辞矛盾，均在材料中如实记录。截图/录屏及账号 UID 可在手动提测时从实际运行页面补充。

AMD 按用户要求暂不继续；已有独立分支 `amd-cagra-v5-opt` 保留，不作为这五题的提交分支，也不声称已完成 GPU 性能验证。
