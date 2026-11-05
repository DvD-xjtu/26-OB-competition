# 倒走钟表旅店

玩家把一段时间换成一件物品，之后再来时，掌柜仍记得交易的后果。Dify 承担“读取记忆 → 生成剧情 → 保存后果 → 输出”的主流程，使用真实 PowerContext 持久化剧情记忆。模型服务仅负责叙事，不拥有数据库凭据。

[打开已发布应用](https://udify.app/workflow/WQb80SuLOoL9dWU3)，按下文“双轮体验”运行。评审证据入口为 [Dify 原生双轮运行记录](evidence/dify-cloud-runs/README.md)，包含对应运行的输入、输出和引擎执行证据。应用需要配套服务在线；从源码独立复现时按下文初始化依赖。

提交资产位于本分支根目录的 `dify/`，分支基于 `2026-competition-ecosystem`。可导入的完整工作流为 [clockwork-inn.yml](clockwork-inn.yml)。其中 Start、四个 Code、三个 HTTP 和 End 共九个节点由 Dify 引擎顺序执行。HTTP 节点分别调用配套服务的 `/recall`、`/narrate`、`/remember`；配套服务提供记忆和模型接口，节点调度、数据传递及完成输出仍在 Dify 内完成。本作品选择赛题允许的 PowerContext 集成路线。

## 配置与运行

以下命令均在本仓库根目录执行，需要 Git、Python 3.11+ 和可用的真实模型账号。建议使用 Python 3.12 创建独立环境。Windows PowerShell 示例：

```powershell
python -m venv .runtime/dify-venv
.\.runtime\dify-venv\Scripts\python.exe -m pip install -r qoder/requirements-powercontext.txt -r dify/requirements.txt
.\.runtime\dify-venv\Scripts\python.exe tools/powercontext_server.py --workspace .runtime/clockwork-context --port 8000
```

`qoder/requirements-powercontext.txt` 是本仓库共用的 PowerContext 依赖锁定入口，安装真实比赛源码 `c92dc0fd986d42cbdebae14670755e04be2c4f8f` 的 `powercontext[server]`。仅安装 `dify/requirements.txt` 不会安装 PowerContext。Linux/macOS 创建环境后将上述 Python 路径换成 `.runtime/dify-venv/bin/python`。

保持 PowerContext 终端运行。该命令只监听 `127.0.0.1:8000`，持久数据位于 `.runtime/clockwork-context/`。另开终端，在同一仓库根目录检查服务：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
```

按 [.env.example](.env.example) 设置**启动配套服务的终端**中的进程环境变量，程序不自动读取 `.env`。PowerShell 使用 `$env:变量名 = '值'`，Linux/macOS 使用 `export 变量名='值'`。

| 变量 | 配置 |
|---|---|
| `POWERCONTEXT_URL` | 上述本地服务为 `http://127.0.0.1:8000` |
| `POWERCONTEXT_TOKEN` | 配套本地启动脚本不启用鉴权，此值留空；连接自己的鉴权服务时填写对应令牌 |
| `BRIDGE_TOKEN` | 自行生成的随机访问令牌，与 Dify Secret 保持一致；不要写入提交文件 |
| `STORY_API_KEY` | 使用模型 API 时填写真实密钥，默认使用 MiniMax 的 OpenAI 兼容接口 |
| `STORY_BASE_URL`、`STORY_MODEL` | API 模式默认 `https://api.minimax.io/v1` 和 `MiniMax-M2.5`，可按账号可用模型设置 |
| `QODER_CLI` | 可选，已登录的官方 Qoder CLI 可执行文件绝对路径；设置后优先使用 CLI 调用 `MiniMax-M3.1-Flash`，无需 `STORY_API_KEY` |

API 和 Qoder CLI 两种模式任选其一，均调用真实模型；未配置时会报错，不会返回模拟故事。配置后启动配套服务：

```powershell
.\.runtime\dify-venv\Scripts\python.exe dify/service.py
```

服务默认监听 `127.0.0.1:8766`。为 Dify Cloud 配置能转发到此端口的 HTTPS 地址，例如启动已安装的 Cloudflare 客户端：

```powershell
cloudflared tunnel --url http://127.0.0.1:8766
```

保持服务和隧道进程运行，将隧道本次输出的 HTTPS 地址填入 Dify 工作流环境变量 `bridge_url`，将同一 `BRIDGE_TOKEN` 填入 Secret 类型的 `bridge_token`。隧道重启后地址可能变化，需更新工作流并重新发布。默认 DSL 中的 `host.docker.internal` 仅适合可访问主机端口的本地 Docker 环境，Dify Cloud 不能直接使用该地址；不应为连通而全局关闭 Dify SSRF 保护。

在 Dify 导入 `dify/clockwork-inn.yml`（DSL 0.3.0），配置上述两个工作流环境变量后发布。该工作流通过 HTTP 调用配套服务，无需安装模型插件。用下方双轮样例确认引擎内读取、生成、存档和输出依次成功。

## 双轮体验

1. 在发布应用填写 `player`、`chapter` 和 `action`。本次证据使用 `player=dify-review-20261105`、`chapter=silver-rain-07`；**复验请使用未使用过的玩家标识和存档名**，避免把已存历史当成首次进入结果。第一轮行动：

   ```text
   我把自己对星期二午后雨声的记忆交给掌柜，换一只刻着「银雨七号」的倒走怀表。请记下这笔交易，并给出下一步选择。
   ```

   等待本轮完成，查看 `story` 和 `citation`。预期故事回应这笔交易、给出后续选择，并在生成后保存到 PowerContext。

2. 再次运行工作流，保持**同一组 `player` 和 `chapter`**，只把 `action` 改为：

   ```text
   我把刚才换来的物品放在柜台上。请说出它的刻字，以及我为它交出的记忆。然后请掌柜查看它指向哪里。
   ```

   第二轮没有重述刻字与记忆内容，预期从第一轮历史中回忆出“银雨七号”和“星期二午后雨声”，并延续故事。检查 Dify 运行记录中读取节点的历史、生成节点输出及保存节点的 `citation`，不要仅凭最终故事推断存档成功。开放式故事措辞不固定，判断依据是两轮之间的交易事实和记忆传递。

3. 补充验证时可重启配套服务和 PowerContext，**保留同一 `.runtime/clockwork-context/` 目录**，再用同一玩家/存档继续提问，检查历史读回。换一个未使用的玩家或存档，首次读取应为空。停止 PowerContext 后运行应报错；模型或保存失败时不应输出“已保存”。这些是可复验步骤，各次实际结果以证据文件为准。

## 证据说明

- [Dify 原生双轮运行记录](evidence/dify-cloud-runs/README.md) 是本次评审的主要入口，按两轮对应查看真实 Dify 运行标识、输入输出和执行证据。具体运行值与结果以该目录的原始记录和索引为准。
- [cloud-workflow-recovery.json](evidence/cloud-workflow-recovery.json) 是历史样例的新 Python 进程读回及玩家隔离验证，证明 PowerContext 中的存档可从外部读回；它不是 Dify 引擎的节点执行日志。
- [powercontext-integration.json](evidence/powercontext-integration.json) 使用 synthetic story text 单独测试真实 PowerContext 的存储和隔离，不作为真实模型生成或 Dify 执行的证据。
- [cloud-run-notes.md](evidence/cloud-run-notes.md) 保留 2026-11-03 的历史操作说明与叙事措辞问题；其中的历史发布版本和样例不替代本次原生运行记录。

`build_dsl.py` 可重新生成DSL（需要PyYAML）。每个HTTP请求前用Code节点JSON编码，避免行动文本中的引号破坏请求。未启用写入自动重试，以免故障时重复保存。当前是单人本机演示，公开多用户部署前应将玩家身份绑定到可信鉴权主体，不能把可自行输入的player当作权限控制。

当前[已发布应用](https://udify.app/workflow/WQb80SuLOoL9dWU3)的桥接通过临时 HTTPS 隧道连接本机，依赖 PowerContext、配套服务和隧道持续运行。长期使用需自行部署桥接服务并更新 Dify 的 `bridge_url` / `bridge_token`，仓库 DSL 不包含演示密钥。
