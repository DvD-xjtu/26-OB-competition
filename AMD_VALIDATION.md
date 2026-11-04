# AMD CAGRA 建图验证

本分支基于冻结 V5 `634888d9b037153fa143d2c913ba4b25503e1d62`，将 CAGRA NN-Descent 最大迭代次数从 100 改为 40。正式代码改动只有这一行。搜索参数、图度数、快照格式和 CPU VSAG 路径沿用 V5。

2026-11-04 在 AMD Notebook 上跑了诊断版。V5 的 10,000 条、128 维构建与首查总耗时为 8.1435 秒，其中 CAGRA 建图调用占 6.9099 秒（84.85%）。据此优先比较建图迭代次数。

## GPU 对照结果

同一诊断版 seekdb 二进制在新实例中分别加载 V5 和候选桥接库。两版使用相同种子的 FP32 合成数据、L2 索引和 32 条独立探针。各维度只有一次配对。

- **250,000 × 128**：构建加首查 51.722652 → 28.757699 秒（1.80×，耗时减少 44.4%）；建图调用 45.155851 → 21.814286 秒。平均 Recall@10 为 0.993750 → 0.993750，Recall@100 为 0.960000 → 0.9628125。
- **250,000 × 256**：构建加首查 56.266897 → 36.554825 秒（1.54×，耗时减少 35.0%）；建图调用 42.510049 → 21.005782 秒。平均 Recall@10 为 0.928125 → 0.931250，Recall@100 为 0.8640625 → 0.865000。首条自向量探针 Recall@100 为 0.95 → 0.94，该探针单独下降 0.01。

四个测试实例均通过返回 ID 数量、唯一性、范围及脚本的 GPU 查询路径检查。独立探针平均 Recall 在这两组中均未下降。256 维首条探针的变化保留为风险记录。

## 复现

在 AMD Notebook 上初始化 V5 依赖并构建 [诊断提交 f02330f6](https://github.com/DvD-xjtu/26-OB-competition/blob/f02330f60b74c8f6059fec3489a3c33622609a4e/AMD_PROFILE.md)，保留 V5 的桥接库。然后在同一工作目录检出 [对照提交 40474afb](https://github.com/DvD-xjtu/26-OB-competition/commit/40474afb7203d6f4c0dbaaed3ff29a1685d3fcca)，执行：

```bash
TMPDIR=/workspace bash docs/gpu-vector-index-hipvs-cuvs/validation/compare_iter40.sh --rows 250000
```

原始 JSON、阶段记录和实例日志位于 Notebook 的 `/workspace/seekdb-cagra-profile-m_5wg32f`、`/workspace/seekdb-cagra-profile-ls41tv5z`、`/workspace/seekdb-cagra-profile-f5rq8vkq`、`/workspace/seekdb-cagra-profile-sap1_qm0`，分别对应 128 维基线、128 维候选、256 维基线及 256 维候选。

## 提测边界

以上数据为合成 GPU 对照，不是 SIFT250K 或 Hidden250K 的正式成绩。尚未实测 CPU VSAG 性能、正式 4096 条查询吞吐或峰值显存。正式评分以平台从本分支源码编译后的配对结果为准；若 Recall、吞吐、显存或其他硬门槛未过，按失败项回查。提交分支移除了诊断插桩，桥接库源文件和构建脚本与已运行的候选一致。
