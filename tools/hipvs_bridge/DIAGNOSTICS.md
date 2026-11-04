# AMD V5 诊断

在 AMD Jupyter 的独立源码目录执行。首次下载时，先在 `deps/init` 运行 `bash dep_create.sh`，恢复环境预装的依赖缓存。测试需要 `/dev/kfd`、MySQL 客户端、空闲端口 2982 和至少 24 GiB 可用磁盘。

```bash
python3 tools/hipvs_bridge/run_diagnostics.py
```

脚本编译 bridge 和 seekdb，启动独立实例，导入合成向量并验证离线 GPU 索引和 CPU VSAG。运行目录以 `Evidence:` 打印。结束后查看该目录的 `report.json`，其中记录当前阶段、已完成阶段和相关日志。日志原文保留在同一目录。脚本结束时停止自己启动的进程，成功后释放该实例的数据目录。

对已经存在的运行目录，可单独汇总日志。

```bash
python3 tools/hipvs_bridge/run_diagnostics.py --collect-only /workspace/seekdb-amd-diag-实际目录
```

bridge 和 CMake 的 `[AMD_DIAG]` 标记随正常构建和运行产生。比赛评测的日志可见性由平台决定，代码只能写入评测进程的输出。仓库拉取发生在任何标记之前。脚本的合成数据结果仅用于定位本地问题。
