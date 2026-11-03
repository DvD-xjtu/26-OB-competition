# 倒走钟表旅店

玩家把一段时间换成一件物品，之后再来时，掌柜仍记得交易的后果。Dify 编排“读取记忆 → 生成剧情 → 保存后果 → 输出”，PowerContext 是持久化的剧情记忆。模型服务仅负责叙事，不拥有数据库凭据。

## 配置与运行

1. Python 3.11+ 安装 `requirements.txt`。启动真实 PowerContext，接口合同参考仓库 `powercontext-2026` 的 `c92dc0fd9`。本机可用 `../tools/powercontext_server.py`。
2. 按 `.env.example` 设置进程环境变量。`STORY_API_KEY` 为真实模型服务密钥，默认支持MiniMax的OpenAI兼容接口。程序不自动读取 `.env`。
3. 运行 `python service.py`，本机监听 `127.0.0.1:8766`。
4. 在 Dify 导入 `clockwork-inn.yml`（DSL 0.3.0格式；实际目标Dify版本的导入尚待验证）。不需要模型插件，HTTP节点调用配套服务。
5. 设置工作流环境变量 `bridge_url` 为Dify容器能够访问的服务地址，`bridge_token` 与后端 `BRIDGE_TOKEN` 一致。默认 `host.docker.internal` 仅适合能访问主机该端口的Docker环境；远程Dify需可达的HTTPS服务及鉴权，不能直接使用本机地址。不要为了连通全局关闭Dify SSRF保护。
6. 发布工作流，从Dify输入玩家标识、存档名、行动。相同玩家/存档恢复同一PowerContext Scope；新存档名开始独立故事。

## 验证样例

- 初始状态：玩家 `demo-player`、新存档 `first-visit-001`。
- 行动1：`我把今天下午的一小时换成一只会说谎的怀表。` 预期首次进入、回应交易并给出下一步选择。
- 行动2：保持玩家和存档，`我拿出刚才换来的怀表，问掌柜为什么它只说谎。` 预期检索历史交易并体现后果。
- 重启配套服务，保持PowerContext数据，继续第二步：仍应能读到历史。
- 换成 `another-player` 或新存档：不可泄漏上一玩家历史。
- 停止PowerContext：工作流报错，不能伪称存档成功。模型或保存失败时不输出“已保存”。

验收需导出Dify各节点真实执行记录、PowerContext返回的citation以及重启读回证据。当前只完成源码、DSL生成和Python语法检查，尚未完成Dify导入和端到端真实运行。开放式故事措辞不固定，验证关系与记忆隔离。

`build_dsl.py` 可重新生成DSL（需要PyYAML）。每个HTTP请求前用Code节点JSON编码，避免行动文本中的引号破坏请求。未启用写入自动重试，以免故障时重复保存。当前是单人本机演示，公开多用户部署前应将玩家身份绑定到可信鉴权主体，不能把可自行输入的player当作权限控制。
