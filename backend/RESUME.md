# RAG Agent — 基于检索增强生成的智能问答系统

## 技术栈

React 18、TypeScript、Tailwind CSS、Vite、FastAPI、SQLAlchemy（异步）、Milvus、Ollama（Qwen2.5:7B-Instruct + 14B + nomic-embed-text + minicpm-v:8B）、LangChain Agent、SSE 流式通信、MySQL / SQLite、JWT、DuckDuckGo、bge-reranker-v2-m3、Unstructured（PDF/表格解析）

## 项目亮点

**多级检索管线**：自研 BM25 稀疏检索 + 稠密向量检索双路召回，通过 RRF（倒数排名融合）算法合并排序，叠加 bge-reranker-v2-m3 交叉编码器精排，形成召回 → 粗排 → 精排三级管线。相比单一向量检索，引入关键词级别匹配能力，专有名词和缩写召回率提升显著。

**LLM-as-Reranker + 专用模型**：初期用 LLM 当裁判对候选文档逐条打分实现重排序，后引入 BAAI bge-reranker-v2-m3 专用交叉编码器（568M 参数），重排速度从 3 秒降至 100ms，精度显著提升。同时解决 embedding 向量 L2 归一化与 Milvus IP 度量的对齐问题。

**智能查询改写**：在检索前通过 LLM 将口语化问题（"高血压怎么治"）改写为检索友好的关键词短句（"高血压 治疗方案 降压药物 生活方式干预"），显著提升检索命中率。few-shot prompt 工程确保改写一致性。

**大-小模型协同架构**：Agent 决策层使用 qwen2.5:14B 保证推理质量（工具选择、检索策略），日常对话生成使用 qwen2.5:7B-Instruct 保证响应速度。两模型共存于 Ollama，非 Agent 场景不加载大模型，显存和速度兼顾。

**LangChain ReAct Agent**：基于 LangGraph 实现 ReAct 模式的智能 Agent，自动判断知识库检索 vs 联网搜索，支持多轮工具调用与结果反思。集成 DuckDuckGo 免费搜索 API 实现零 API Key 联网搜索能力。

**多跳查询规划**：针对对比类、多步推理类复杂问题，LLM 自动拆解为 2-3 个子问题并行检索，通过 asyncio.gather 并发 + 结果合并去重，总延迟约等于单次检索而不累加。

**对话记忆与上下文管理**：基于 tiktoken 实现精确的 token 预算分配（历史 25% + 检索上下文 70% + 输出 5%），对话历史自动注入 LLM 上下文，支持多轮追问和指代消解。同时实现 Lost in the Middle 规避策略——最相关文档放 prompt 头部和尾部。

**多模态文档处理**：集成 Unstructured 引擎解析 PDF 表格和图片位置标注，结合多模态视觉模型（minicpm-v:8B）自动描述 PDF 中嵌入的图表照片，将视觉信息转化为可检索的文本描述，实现图文跨模态 RAG。支持对话中直接上传图片进行 OCR + 视觉问答。

**SSE 流式架构**：全链路从查询改写 → 检索 → 精排 → LLM 生成，每一步通过 SSE 事件流实时推送到前端，用户可观察 Agent 的完整思考过程（推理步骤、检索来源、重排分数）。前端实现流式 token 渲染、推理步骤折叠展示、检索详情评分面板。

**结构化日志系统**：基于 Python 原生 logging + JSON Formatter 实现零依赖结构化日志，检索耗时、生成 token 数、错误率均以键值对形式输出，支持 grep / ELK / Grafana 检索与监控。

**LLM-as-Judge 评估体系**：用 LLM 当裁判实现 faithfulness / answer relevancy / context precision / context recall 四项 RAG 指标自动评分，零人工标注成本，支持 A/B 测试量化优化效果。

**工程实践**：FastAPI 依赖注入 + 四层架构分离、SQLAlchemy 异步 ORM（多对多关系 + JSON 字段）、JWT 认证 + bcrypt 密码哈希 + 用户数据隔离、SSE 流式会话生命周期管理、前端 ProtectedRoute 路由守卫 + localStorage token 持久化、Milvus HNSW 索引调优（M/efConstruction/ef 参数）。

## 项目描述

独立设计并实现了一个完整的 RAG Agent 智能问答系统，涵盖前后端全栈开发、多级检索管线、Agent 自主决策和文档处理全链路。

**前端**：基于 React 18 + TypeScript + Tailwind CSS 构建 SPA 应用，包含 JWT 认证登录/注册、对话管理（新建/切换/删除）、知识库管理（拖拽上传/文档列表/状态追踪）、对话记忆、图片上传解析、流式对话展示等模块。实现了 ProtectedRoute 路由守卫、SSE 流式 token 渲染、推理步骤折叠展示、检索详情评分面板、错误信息人性化翻译等交互优化。

**检索系统**：BM25 内存倒排索引 + 稠密向量双路召回 → RRF 融合粗排 → bge-reranker-v2-m3 精排三级管线。Milvus 向量数据库 HNSW 索引、IP 度量。文档上传后经 Unstructured 解析（PDF/Word/Markdown）、句子边界分块（512 字符 + 64 重叠）、bert 维度对齐、L2 归一化入库，支持 PDF 表格识别和图片视觉描述生成。

**Agent 推理**：基于 LangGraph ReAct Agent 实现智能工具调用，自动决策知识库检索与联网搜索切换。多跳查询 Agent 自动拆解复杂问题为子任务并行检索。查询改写 + 上下文窗口管理 + 对话记忆，形成完整的检索增强生成闭环。

**后端架构**：FastAPI 异步框架，分层设计（api → services → core → models），依赖注入 + 模块解耦。SSE 流式推送推理全链路。JWT + bcrypt 认证，用户数据隔离（对话/文档按 user_id 过滤）。结构化日志 + 环境变量类型安全 + 异常分层捕获。
