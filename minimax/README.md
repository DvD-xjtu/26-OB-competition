# MiniMax × seekdb × PowerContext：真实条件编译检查器修复

这是可运行的 SDD 上下文模块。使用本仓库 `seekdb-2026` 分支中的真实 `tools/module_check/unittest_module_check.py` 和原有 12 项测试；来源 commit 见 `seekdb-module/provenance.json`。新规格与 5 项目标测试单独提供。

实际通过 Qoder 官方 CLI 调用 **MiniMax-M3.1-Flash**，由模型生成完整修改后的源码。修复 `#if 0 / #elif 0 / #elif 1 / #else` 链处理，未修改测试获取通过结果。

## 已完成的真实验证

- 修改前：17 项测试，3 项因目标行为缺失失败，12 项原有回归测试通过。
- 修改后：同一套 17 项测试全部通过；测试文件 SHA-256 未变。
- 规格、源码、测试写入真实 seekdb SQL 表，按任务与角色查询，查询结果作为模型输入。
- 最新规格重导入后读取到新版本，再恢复原规格验证覆盖更新。
- PowerContext 写入完成事项、待办和验证摘要，新 Python 进程恢复状态。
- 模型回答、补丁、输入、前后快照、命令、退出码、哈希保存在 `evidence/seekdb-conditional-run1/`。

`acceptance.json` 是本地验证汇总，**不是平台评分**。原始 `restart.json` 保留了第一次完整测试日志被上下文预算截断的诊断记录；修正为精简状态后，成功记录为 `restart-compact-state.json`。详细日志保留在文件中，不塞入短上下文。

## 运行

Python 3.11+；安装 `pip install -r requirements.txt`。启动真实 seekdb（MySQL 端口默认 2881）及 PowerContext HTTP 服务（默认 8000）。本仓库 `../tools/` 提供本地启动示例。PowerContext 源码固定来自本仓库 `powercontext-2026` 的 `c92dc0fd986d42cbdebae14670755e04be2c4f8f`。

按 `.env.example` 设置环境变量（脚本读取进程环境，不自动读取 .env）。可选两种真实模型路径：

1. 配置 `MINIMAX_API_KEY`、`MINIMAX_BASE_URL` 和 `MINIMAX_MODEL`；
2. 安装并登录官方 `@qoder-ai/qodercli@1.1.81`，设置 `QODER_CLI` 为 CLI 可执行文件绝对路径。该路径显式选择 MiniMax-M3.1-Flash，禁用工具，只返回代码 JSON。

```sh
python context.py ingest --task seekdb-conditional-v1
python context.py context --task seekdb-conditional-v1
cd seekdb-module
python -m unittest -v unittest_module_check_test test_conditional
```

重新演示开发流程时，把 evidence 中 `before/` 复制到新的工作目录（不要覆盖已有证据），然后：

```sh
python context.py develop --task fresh-task --project path/to/baseline-copy --output evidence/new-run
```

输出目录必须不存在。测试失败、模型失败或恢复失败均退出非零，并保留真实失败记录。源码文本的数据库 digest 使用 UTF-8 规范化换行；测试报告 code_sha256 使用实际文件字节，因此 Windows CRLF 文件的两种摘要不同。

## 数据范围

示例仅处理显式指定的四个源码/规格/测试文件，不扫描个人目录。不会保存 API 密钥或模型私有推理内容。任务 ID 隔离上下文，数据库与 PowerContext 均实际参与主流程。
