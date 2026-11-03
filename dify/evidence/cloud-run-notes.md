# Dify Cloud 真实运行

2026-11-03 在实际 Dify Cloud 工作流编辑器导入 DSL 并执行两轮，随后发布版本1。

- 编辑器：https://cloud.dify.ai/app/e379a3f6-d769-46e5-84c5-ffe21fe53d36/workflow
- 发布应用：https://udify.app/workflow/WQb80SuLOoL9dWU3
- player=`contest-demo`，chapter=`clock-20261103`。
- 第一轮：`我把今天下午的一小时换成一只会说谎的怀表。`
- 第二轮：`我拿出刚才换来的怀表，问掌柜为什么它只说谎。我选择第一张房卡。`

第一轮输出银壳怀表、逆行表针、失语钟室和迟到阁楼选项，保存引用 revision=1，entry_id=`mem_ent_180861a5987c44d58d06aa1fb53c8d23`。

第二轮读回先前交易，输出所选第一张房卡为“失语钟室”，保存引用 revision=2，entry_id=`mem_ent_beaa6a201e444e3e9a8f5ac259d6e300`。完整历史由另一个新 Python 进程从真实 PowerContext 读回，见 `cloud-workflow-recovery.json`；另一个玩家读不到该历史。

模型真实调用经已登录 Qoder CLI 的 MiniMax-M3.1-Flash，未使用模拟故事。第二轮中“不能说谎”与选项“不能说出真相”存在叙事措辞矛盾；这不影响已验证的记忆读写，但不能将此样例表述为剧情一致性完美。

桥接 HTTPS 使用临时 Cloudflare 隧道，必须保持本机 PowerContext、service.py 和隧道运行。发布 URL 本身不是永久托管的后端；换环境应按 README 配置自己的可达桥接地址。演示令牌仅存于 Dify Secret 和本机忽略目录，未写入仓库。
