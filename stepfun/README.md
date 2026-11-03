# 本地书房：浏览器 embedding 与 seekdb 混合检索

## 启动

需要 Node.js 22+、Chrome/Edge 和 seekdb 1.3+ server，数据库 `test` 已创建。数据库监听地址仅供本机使用。

```sh
npm ci
cp .env.example .env
# 编辑 .env 中的数据库连接设置
npm run build
npm start
```

访问 `http://127.0.0.1:8787`。开发时另开终端执行 `npm run dev`。`npm test` 检查文本切分、非法向量和评测指标。仓库 `.npmrc` 跳过服务端自动 embedding 的可选 peer 依赖；服务端 schema 显式设为 `embeddingFunction: null`。

Linux/macOS 可使用 SDK 支持的嵌入式方式：设置 `SEEKDB_PATH`，安装与 seekdb 1.3.0 对应的 `@seekdb/js-bindings@1.3.0`。以实际平台支持为准。server 方式可按官方文档部署：<https://www.oceanbase.ai/docs/deploy-seekdb-by-using-docker>。不使用其他数据库替代 seekdb。

## 操作

1. 创建 `research` 知识库，加载 INT8 模型。状态栏显示实际 WebGPU/WASM 后端。
2. 导入 `.txt` 或 `.md` 文档；内容在 Worker 内切换到本地 embedding 流程，服务端仅接收向量、原文和来源。
3. 等待索引可检索的确认后输入问题，结果附带原文和文件名。
4. 追加文档，再次查询；切换知识库会清除旧结果。重复导入相同片段使用内容 ID 幂等 upsert。
5. 使用同一语料、查询和设备分别测 FP32 与 INT8、批大小1与8，以及强制WASM。点击“运行当前配置评测”，导出记录。

## 一页技术说明

- 模型：公开 `Xenova/all-MiniLM-L6-v2`，384维，Transformers.js 3.8.1；模型文件来自 Hugging Face。INT8 `q8` 使用已有量化 ONNX 权重，FP32 作为基线。固定 revision `751bff37182d3f1213fa05d7196b954e230abad9`。下载进度记录各模型资产真实字节数。ONNX WASM 运行时随 Vite 构建打包，同源加载。
- 本地推理：文档和查询均在浏览器 Worker 调用 feature-extraction，mean pooling + normalize。支持 WebGPU 时优先选用；初始化失败自动回退 WASM，界面记录实际后端和回退原因。不调用云推理。
- 数据库：seekdb-js 1.3.0 创建 cosine HNSW 和 IK 全文索引；混合检索调用 `collection.hybridSearch`，由数据库 RRF 合并。应用没有客户端排序或两路结果拼接。
- 写入与状态：批次 upsert 后刷新索引，再通过真实混合查询确认新 ID 可见。知识库名独立，模型加载或导入期间禁止切换以防结果写入错误集合。
- 性能：支持批量推理、浏览器模型缓存、分阶段计时。记录加载、embedding、写入、刷新、数据库检索和端到端耗时；评测保留3轮原始查询数据及Recall@3/nDCG@3。内置6文档仅为冒烟样例，正式质量评测应扩展领域语料与标注。

## 当前验证状态

核心单元测试及生产构建通过，真实 seekdb 写入、索引可见性、库内混合检索、集合隔离通过（`evidence/database-integration.json`）。浏览器模型完整链路、量化体积与质量报告尚待完成；未宣称满足全部验收项或获得满分。实验报告必须由本应用实际运行生成，不提供占位性能数字。
