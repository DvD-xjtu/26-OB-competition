# AMD V5 离线 DDL 诊断

诊断分支直接基于冻结 V5 `634888d9b037153fa143d2c913ba4b25503e1d62`。目标是确认构建计时主要花在哪里，再选择一个有可测收益的改动。已知参考 V5 在 AMD Notebook 的 `/workspace/seekdb-contest-v5` 完成了桥接库和 seekdb 编译。Notebook 的用户日志尚未提供 GPU 运行结果，本地 Mac 也没有 ROCm。

插桩复用 `OB_BUILD_CUVS_TRACE`，运行时用 `OB_VSAG_TRACE=1` 和 `OB_CUVS_TIMING=1` 开启。关闭编译开关的正式构建不启用计时。保留 V5 的建图和搜索参数、索引快照格式以及 VSAG 路径。

在诊断分支根目录运行以下命令。`deps/3rd` 应已通过仓库的依赖初始化脚本准备。

```bash
bash tools/hipvs_bridge/build.sh && \
  ./build.sh release -DOB_BUILD_CUVS=ON -DOB_BUILD_CUVS_TRACE=ON \
  -DCUVS_BRIDGE_LIB="$PWD/tools/hipvs_bridge/libseekdb_cuvs_bridge.so" --make -j8 && \
  python3 docs/gpu-vector-index-hipvs-cuvs/validation/profile_offline_ddl.py
```

脚本启动独立 seekdb 实例，默认端口 2981。它在建索引前导入 10,000 条可复现的 128 维合成向量，检查实际行数和 GPU 建图及首查标记，并验证 Top-100 返回数量、唯一性和 ID 范围，另用精确查询记录一条探针的 Recall。它只清理自己启动的进程，保留临时目录和证据。可使用 `--port` 选择空闲端口，使用 `--rows 250000 --dim 256` 检查大数据量。

`result.json` 保存 DDL、第一条查询和两者合计的耗时及各阶段样本。`trace.log` 保留事件原文，`seekdb.stdout.log` 和实例日志可定位失败。

- `ddl_build_call_us` 是 CAGRA 构建调用和其线程开销。
- `ddl_graph_write_us` 是图序列化到临时文件的调用耗时。
- `ddl_snapshot_out_us` 是原始向量、ID 和图数据写入数据库快照流的耗时。
- `load_vectors_us`、`load_graph_stage_us`、`load_graph_call_us` 分别对应向量与 ID 加载、图临时文件整理、库反序列化。
- `query_worker_us` 包含创建和等待线程以及内部工作，`query_bridge_us` 是其中桥接层的搜索调用。两者嵌套，不能相加。

这些阶段使用主机单调时钟，不额外强制 GPU 同步。一次 DDL 可能有多次图事件，也可能重叠。CPU 扫描、调度、I/O 等未单独覆盖的时间不能用阶段求和代替。数据为合成输入，插桩会产生额外日志开销，结果只用于定位，不是正式成绩或正式 Recall 门槛验证。

下一步在同一 AMD 实例采集阶段数据和无插桩 V5 的总耗时。只有验证热点占比后才修改对应机制，并按正式 SIFT250K/Hidden250K 配对、Recall、GPU 路径、CPU VSAG 回归和资源门槛检查。已有查询缓冲区候选 `c8969b38` 尚无真实 GPU 验证，不将其作为性能对照。
