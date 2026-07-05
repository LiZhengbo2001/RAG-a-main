# RAG_OS → 官网智能客服 改造方案

## 一、项目现状

RAG_OS 是一个面向中文的全栈 RAG 智能问答系统，当前架构为"用户上传文档 → 分块向量化 → 提问时双路检索 → RRF 融合 → reranker 重排序 → LLM 流式生成"。核心模块包括：

| 模块 | 文件 | 职责 |
|------|------|------|
| 分块 | `core/chunker.py` | 固定窗口分词（512字符 + 64重叠），无层级结构 |
| 向量库 | `core/vectordb.py` | Milvus standalone，HNSW 索引，IP 度量，单 collection |
| 关键词 | `core/bm25.py` | jieba 分词 + BM25 内存倒排索引 |
| 重排序 | `core/reranker.py` | bge-reranker-v2-m3 交叉编码器，本地 D 盘加载 |
| 查询改写 | `core/query_rewriter.py` | LLM 将口语改写为检索关键词 |
| 检索流水线 | `services/retriever.py` | 双路召回 + RRF 融合 + reranker + Lost-in-the-Middle |
| LLM 生成 | `core/llm.py` | OpenAI 兼容客户端调用 Ollama，支持流式/非流式 |
| 编排层 | `services/rag_pipeline.py` | 串联改写→检索→Agent→生成，产 SSE 事件流 |
| 多跳 Agent | `core/multi_hop_agent.py` | 复杂问题拆解子问题并行检索 |
| 联网 Agent | `core/langchain_agent.py` | LangGraph ReAct，检索无结果时 fallback DuckDuckGo |
| 聊天 API | `api/chat.py` | SSE 流式聊天端点（需 JWT 认证） |
| 数据模型 | `models/conversation.py` | Conversation / Message / Document / User |

外部依赖：MySQL (3306) / Milvus (19530) / Ollama (11434) / bge-reranker-v2-m3 (本地 D 盘)。

---

## 二、改造总览

从"检索-生成"升级为 **"意图路由 + 多级混合检索 + 结构化 Prompt 控制"** 的复合架构。七个改造方向：

```
用户提问
   │
   ├── ① 意图路由（business / chitchat）
   │      ├─ chitchat → 模板回复（跳过检索）
   │      └─ business ↓
   ├── ② 查询改写（现有，不改）
   ├── ③ 双路径检索
   │      ├─ 浅层：Milvus dense + BM25 → RRF → reranker（现有，修改）
   │      └─ 深层：NER 实体提取 + 图谱扩展 → 二次召回（新建）
   ├── ④ 父-子分块：子块检索 + 父块上下文扩展（新建分块器）
   ├── ⑤ 结构化 Prompt 控制生成行为（改写 Prompt 模板）
   ├── ⑥ 5 秒超时检测 → 留资引导（新建）
   └── ⑦ 匿名 Widget API + 前端聊天挂件（新建）
```

---

## 三、分项改造方案

### 改造一：父-子文档分块结构

**问题**：`core/chunker.py` 只产出等长孤立的 chunk，LLM 拿到的片段没有上下文，回答容易断章取义。

**方案**：构建两层结构——父块 1024-2048 字符保证上下文完整，子块 256-512 字符用于检索匹配。检索用子块，生成时补上对应父块的完整上下文。

#### 新建文件

**`core/chunker_v2.py`**

```
输入：完整文档文本
输出：[{parent_id, parent_text, children: [{child_id, child_text, chunk_index}]}]

算法：
1. 按语义边界（段落 \n\n、标题 ##、列表项）切分父块，目标长度 1024-2048
2. 每个父块内部按句子边界切分子块，目标长度 256-512，同父块内子块重叠 64 字符
3. child_id = f"{parent_id}_{child_index}"
4. 对每个子块调用 NER 模块提取实体标签（供改造二的深层检索使用）
```

#### 修改文件

**`core/vectordb.py`**

- Milvus collection schema 新增字段：`parent_id VARCHAR(64)`、`entity_tags VARCHAR(512)`
- 修改 `init_collection()`：若 collection 已存在但缺少新字段，需要删除重建（或手动 ALTER）
- 新增 `insert_vectors_v2()` 函数，接收 chunker_v2 的输出结构
- 新增 `get_parent_texts(parent_ids)` 函数，返回父块原文（从 MySQL 或本地缓存读取）

**`services/document_service.py`** — `process_and_index()`

- `chunk_text(text)` → `chunk_text_v2(text)`
- 父块原文存入 MySQL（新建 `document_parent_chunks` 表），子块向量存入 Milvus

**`services/retriever.py`** — `retrieve()`

- 子块检索完成后，根据 `parent_id` 去重，拉取父块原文
- 返回结果中每个 chunk 附带 `parent_text` 字段

#### 新增数据表

```sql
CREATE TABLE document_parent_chunks (
    id VARCHAR(64) PRIMARY KEY,
    doc_id VARCHAR(36) NOT NULL,
    parent_index INT NOT NULL,
    parent_text TEXT NOT NULL,
    entity_tags VARCHAR(512) DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_doc_id (doc_id)
);
```

---

### 改造二：双路径召回（浅层 + 深层）

**问题**：当前只有浅层检索（向量 + BM25），对"iPhone 15 和 14 的电池有什么不同"这类需要精确实体匹配的问题，召回精度不足。

**方案**：保留浅层路径不变，新增深层路径——NER 提取查询中的实体 → 图谱 1-hop 扩展关联实体 → 用扩展实体做 Milvus 标量过滤 + 额外 BM25 搜索 → 两路结果加权融合。

#### 新建文件

**`core/ner.py`** — 实体提取

```
async def extract_entities(text: str) -> dict:
    用 Ollama + qwen2.5 做 few-shot NER
    
    实体类型（客服场景定制）：
    - product: 产品名称、型号
    - feature: 功能特性、技术参数
    - price: 价格、费用
    - policy: 政策条款（退换货、保修）
    - operation: 操作步骤、使用方法
    - error: 故障现象、错误码
    - contact: 联系方式
    
    Prompt 示例：
    提取以下文本中的关键实体，按类型分组以 JSON 返回。
    实体类型：product, feature, price, policy, operation, error, contact
    文本：{query}
    
    返回：{"product": [...], "feature": [...], ...}
```

**`core/graph_store.py`** — 实体关系图谱

```
class EntityGraphStore:
    轻量级内存实现，JSON 文件持久化
    
    数据结构：
    {
        entity_id: {
            "name": str,
            "type": str,
            "relations": {related_entity_id: relation_type, count: int}
        }
    }
    
    构建逻辑：
    - 文档上传时分块 NER 提取实体
    - 同一父块内共现的实体建立关联边
    - 边权重随共现次数累加（每次 +1）
    
    核心方法：
    - add_entity(name, type, doc_id)
    - add_cooccurrence(entity_a, entity_b, relation_type)
    - expand(entity_names, max_hops=1) → 扩展后的实体列表
    - save(path) / load(path) → JSON 持久化
    
    持久化路径：storage/entity_graph.json
```

#### 修改文件

**`services/retriever.py`** — 双路径融合

```
async def retrieve_dual_path(query, rewritten=None):
    # === 浅层路径（保持不变）===
    shallow_hits = await _shallow_retrieve(query, rewritten)
    #   search_vectors() + BM25.search() → RRF → reranker
    
    # === 深层路径（新增）===
    entities = await extract_entities(query)
    expanded = graph_store.expand(entities, max_hops=1)
    
    deep_hits = await _deep_retrieve(expanded)
    #   1. Milvus 标量过滤: filter='entity_tags like "%entity_name%"'
    #   2. 扩展词做额外 BM25 搜索
    #   3. 独立 RRF 融合
    
    # === 加权融合 ===
    final_hits = _weighted_merge(
        shallow_hits, 0.7,
        deep_hits, 0.3
    )
    
    # 去重 → reranker → Lost-in-the-Middle → 返回
    return _post_process(final_hits)
```

**`core/vectordb.py`** — 标量过滤检索

```
新增函数：
def search_with_tag_filter(query_vec, tags, top_k=10):
    """在 entity_tags 字段中匹配指定标签的向量检索"""
    filter_expr = " or ".join(
        [f'entity_tags like "%{t}%"' for t in tags]
    )
    return client.search(..., filter=filter_expr)
```

**`core/chunker_v2.py`** — 分块时打实体标签

```
子块分完后，调用 NER 模块提取实体，存入 entity_tags 字段
同时将实体和共现关系写入 graph_store
```

**`services/document_service.py`** — `process_and_index()`

```
新增调用：
entities = await extract_entities(parent_text)
graph_store.add_document_entities(doc_id, parent_id, entities)
```

---

### 改造三：前置二分类意图路由

**问题**：所有请求包括"你好""谢谢""测试一下"都走完整的检索流水线，浪费资源且回复体验差。

**方案**：检索前用一次轻量 LLM 调用（<100 tokens）判断意图，闲聊直接模板回复跳过检索，业务问题走正常 RAG 流水线。

#### 新建文件

**`core/intent_router.py`**

```
async def classify(query: str) -> str:
    返回 "business" / "chitchat"
    
    快速过滤（不调 LLM）：
    - 含"你好/谢谢/再见/测试/在吗/hello/hi"且长度 < 10 字 → chitchat
    
    LLM 分类（快速过滤未命中时）：
    Prompt：
    判断以下用户消息的意图类型。
    - business：询问产品、服务、价格、政策、技术问题、使用帮助等
    - chitchat：打招呼、感谢、告别、闲聊、测试等
    只回复一个词：business 或 chitchat
    
    用户消息：{query}
    意图：
    
    兜底：LLM 返回无法解析时默认按 business 处理
```

#### 修改文件

**`services/rag_pipeline.py`** — `run()` 和 `run_stream()`

```
入口处插入：

intent = await classify(query)

if intent == "chitchat":
    # 直接返回模板回复（不检索、不消耗 Milvus/reranker）
    answer = CHITCHAT_TEMPLATES.get_response(query)
    yield {"event": "token", "data": answer}
    yield {"event": "done", ...}
    return

# business 路径：继续现有流水线
rewritten = await rewrite_query(search_query)
chunks = await retrieve(search_query, rewritten)
...
```

**`core/llm.py`** — 拆分 Prompt 模板

```python
# 原有 SYSTEM_PROMPT 改名为 BUSINESS_PROMPT，内容详见改造四

# 新增闲聊 Prompt
CHITCHAT_PROMPT = """你是一个友好的客服机器人。请用热情、简洁、口语化的语言回复用户。
规则：
1. 回复不超过 3 句话
2. 如果用户打招呼，主动询问需要什么帮助
3. 在回复末尾推荐 2 个常见问题让用户选择
4. 你是官方客服，不要承认自己是 AI 或机器人"""

# 新增无结果 Prompt
NO_RESULT_PROMPT = """你是客服助手。知识库中没有找到相关信息。
请使用以下固定话术回复：
"很抱歉，您咨询的这个问题暂时未收录在我们的知识库中。建议您换个方式描述问题，或者联系人工客服获取帮助。"
不要编造任何信息。"""
```

---

### 改造四：结构化 Prompt 控制生成行为

**问题**：当前 SYSTEM_PROMPT 约束力不够——只说"基于文档、不要编造"，没有格式要求、没有防幻觉硬约束、没有禁止使用的表述列表。

**方案**：为业务场景定制严格的多层 Prompt 模板，强制 LLM 遵守固定的回答结构和输出约束。

#### 修改文件

**`core/llm.py`** — 重写 BUSINESS_PROMPT

```python
BUSINESS_PROMPT = """你是{company}的官方智能客服助手。请严格遵守以下规则：

【核心规则】
1. 你只能依据下方「参考文档」中的内容回答，绝对不允许编造、猜测或使用外部知识
2. 如果参考文档不足以回答，你必须明确说：
   "该问题暂未收录在我们的知识库中，建议您联系人工客服（{phone}）获取更准确的解答。"
3. 禁止使用以下表述：
   - "根据我的了解""我认为""一般来说""可能""也许"（这些词暗示不确定性，禁止）
   - "我是一个AI""作为语言模型""根据我的训练数据"（禁止暴露AI身份）
4. 你是{company}的官方客服人员，你的名字是{agent_name}

【回答格式】
- 开头：用一句话直接回答用户的核心问题
- 正文：如有多个要点，分点说明（每条信息末尾标注来源，如 [来源1]）
- 结尾：一句友好的收尾（如"还有其他问题吗？"），不超过 10 个字

【来源引用格式】
- 每条来自参考文档的信息末尾标注：[来源{编号}]
- 禁止凭空编造编号

【价格/联系信息特别规则】
- 价格、电话、地址等信息必须与参考文档原文一致，不得添加或修改
- 如果参考文档中的价格信息标注了有效期，必须在回答中注明

【禁止事项总览】
- 编造不存在的数据、价格、日期、联系方式
- 对产品做出主观评价（如"非常好""强烈推荐"）
- 使用第一人称谈论知识边界（不要说"我不知道""我不会"）
- 承认自己是 AI 或机器人
"""

# 模板变量从 config.py 读取
# {company} → COMPANY_NAME
# {phone} → CUSTOMER_SERVICE_PHONE
# {agent_name} → AGENT_NAME
```

#### 修改文件

**`config.py`** — 新增客服配置

```python
# 客服系统配置
COMPANY_NAME = os.getenv("COMPANY_NAME", "公司")
CUSTOMER_SERVICE_PHONE = os.getenv("CUSTOMER_SERVICE_PHONE", "400-000-0000")
CUSTOMER_SERVICE_WECHAT = os.getenv("CUSTOMER_SERVICE_WECHAT", "")
AGENT_NAME = os.getenv("AGENT_NAME", "小助手")
LEAD_TIMEOUT_SECONDS = int(os.getenv("LEAD_TIMEOUT_SECONDS", "5"))
SUGGESTED_QUESTIONS = os.getenv("SUGGESTED_QUESTIONS", "").split(",")
# 示例: "产品价格怎么算,如何退换货,售后服务电话是多少"
```

**`backend/.env`** — 新增配置项

```
COMPANY_NAME=您的公司名称
CUSTOMER_SERVICE_PHONE=400-xxx-xxxx
CUSTOMER_SERVICE_WECHAT=company_wechat
AGENT_NAME=小助手
LEAD_TIMEOUT_SECONDS=5
SUGGESTED_QUESTIONS=产品价格怎么算,如何退换货,售后服务电话是多少
```

---

### 改造五：5 秒超时检测 + 留资引导

**问题**：LLM 生成第一个 token 可能需 3-10 秒，用户干等没有反馈。没有留资机制，无法在 AI 卡顿时捕获商机。

**方案**：LLM 流式生成用 asyncio.wait_for 包裹，5 秒内无 token 则主动推送系统消息 + 留资引导。留资数据存 MySQL。

#### 新建文件

**`core/timeout_guard.py`**

```python
async def stream_with_timeout(generator, timeout_seconds=5):
    """
    包装 LLM 流式生成器，超时触发交互引导。
    
    事件产出顺序：
    - 正常: token × N → done
    - 超时: system_message → lead_prompt → (继续 token × N 或 fallback)
    """
    try:
        first_token = await asyncio.wait_for(
            generator.__anext__(), timeout=timeout_seconds
        )
        # 第一个 token 在超时内到达，正常流式输出
        yield first_token
        async for token in generator:
            yield token
    except asyncio.TimeoutError:
        # 超时：推送系统消息 + 留资引导
        yield {
            "event": "system_message",
            "data": json.dumps({
                "text": "我正在为您查找相关信息，这可能需要一点时间。"
                        "如果您希望我们的客服人员稍后主动联系您，"
                        "可以留下您的手机号或微信号，我们会在 1 个工作日内回复。"
            })
        }
        yield {
            "event": "lead_prompt",
            "data": json.dumps({"show": True})
        }
        # 继续等待模型输出（不中断生成）
        try:
            async for token in generator:
                yield token
        except Exception:
            yield {
                "event": "fallback",
                "data": json.dumps({"text": "信息查询超时，请稍后再试。"})
            }
```

**`models/lead.py`**

```python
class Lead(Base):
    __tablename__ = "lead"
    
    id: str           # UUID
    visitor_id: str   # 匿名访客标识，索引
    conversation_id: str  # 关联对话
    contact_type: str     # "phone" / "wechat" / "email"
    contact_value: str    # 手机号或微信号
    question: str         # 触发留资的用户问题
    status: str           # "pending" / "contacted" / "closed"
    created_at: datetime
```

**`api/lead.py`**

```python
router = APIRouter(prefix="/widget", tags=["lead"])

@router.post("/lead")
async def submit_lead(req: LeadRequest, db: AsyncSession):
    """提交留资信息（免认证），做基本格式校验"""
    # 手机号校验：11 位数字
    # 微信号校验：非空字符串
    lead = Lead(
        visitor_id=req.visitor_id,
        conversation_id=req.conversation_id,
        contact_type=req.contact_type,
        contact_value=req.contact_value,
        question=req.question,
        status="pending",
    )
    db.add(lead)
    await db.commit()
    return {"status": "ok", "message": "信息已提交，客服将在 1 个工作日内联系您。"}
```

#### 修改文件

**`services/rag_pipeline.py`** — `run_stream()`

```
# 原代码:
async for token in chat_stream(gen_query, chunks, history):
    full_answer += token
    yield {"event": "token", ...}

# 改为:
async for event in stream_with_timeout(
    chat_stream(gen_query, chunks, history),
    timeout_seconds=LEAD_TIMEOUT_SECONDS
):
    if event["event"] == "token":
        full_answer += json.loads(event["data"])["text"]
    yield event
```

**`models/__init__.py`** — 注册 Lead 模型

```python
from models.lead import Lead  # 新增
```

**`main.py`** — 注册路由

```python
from api.lead import router as lead_router
app.include_router(lead_router, prefix="/api")
```

---

### 改造六：匿名 Widget API（访客聊天入口）

**问题**：当前所有聊天接口都要求 JWT 认证（`get_current_user` 依赖）。智能客服场景下访客不应注册登录。

**方案**：新增 `/api/widget/*` 路由组，免认证，用前端生成的 visitor_id（UUID 存 localStorage）追踪匿名会话。

#### 新建文件

**`api/widget_chat.py`**

```python
router = APIRouter(prefix="/widget", tags=["widget"])

@router.post("/chat/stream")
async def widget_chat_stream(req: WidgetChatRequest, db):
    """匿名流式聊天，visitor_id 代替 user_id"""
    async def generator():
        async for ev in run_stream(
            db, req.query, req.conversation_id,
            user_id=None,           # 匿名，无认证用户
            visitor_id=req.visitor_id,  # 前端生成的访客 ID
        ):
            yield ev
    return EventSourceResponse(generator())

@router.get("/suggestions")
async def widget_suggestions():
    """返回推荐问题列表"""
    questions = SUGGESTED_QUESTIONS or [
        "我想了解产品价格",
        "如何申请退款？",
        "售后服务电话是多少？",
        "支持哪些支付方式？",
    ]
    return {"questions": questions}

@router.post("/feedback")
async def widget_feedback(req: FeedbackRequest, db):
    """用户对回答的反馈（👍/👎）"""
    # 存储到 message 表的 feedback 字段
    ...
```

**`schemas/widget.py`**

```python
class WidgetChatRequest(BaseModel):
    query: str
    visitor_id: str
    conversation_id: str | None = None

class FeedbackRequest(BaseModel):
    message_id: str
    rating: str      # "positive" / "negative"
    visitor_id: str

class LeadRequest(BaseModel):
    visitor_id: str
    conversation_id: str | None = None
    contact_type: str      # "phone" / "wechat"
    contact_value: str
    question: str | None = None
```

#### 修改文件

**`main.py`**

```python
from api.widget_chat import router as widget_chat_router
from api.lead import router as lead_router

# CORS 改为允许所有域名（聊天挂件需嵌入任意官网）
app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)

app.include_router(widget_chat_router, prefix="/api")
app.include_router(lead_router, prefix="/api")
```

**`services/rag_pipeline.py`** — `_ensure_conversation()`

```python
async def _ensure_conversation(db, cid, user_id=None, visitor_id=None):
    """支持匿名访客：按 visitor_id 查找最近的未过期会话"""
    if cid:
        conv = await db.execute(
            select(Conversation).where(Conversation.id == cid)
        ).scalar_one_or_none()
        if conv:
            return conv
    # 匿名访客：查找 24 小时内最近的会话复用
    if visitor_id:
        recent = await db.execute(
            select(Conversation)
            .where(Conversation.visitor_id == visitor_id)
            .where(Conversation.updated_at > datetime.now() - timedelta(hours=24))
            .order_by(desc(Conversation.updated_at))
            .limit(1)
        )
        conv = recent.scalar_one_or_none()
        if conv:
            return conv
    conv = Conversation(title="新对话", user_id=user_id, visitor_id=visitor_id)
    db.add(conv)
    await db.commit()
    return conv
```

**`models/conversation.py`** — Conversation 表增加字段

```python
visitor_id: Mapped[str | None] = mapped_column(
    String(64), index=True, nullable=True
)
```

---

### 改造七：前端聊天挂件 — 借鉴 myblog 的 ChatBot 设计（Vue 3 实现，完全新建）

**背景**：myblog 项目中有一个成熟的 AI 聊天浮窗组件 `ChatBot.vue`，已在生产环境运行。它的核心设计——右下角浮窗、会话持久化、欢迎消息、键入动画、文章上下文感知——是经过验证的最佳实践。

**方案**：以 myblog 的 `ChatBot.vue` 为起点，设计 RAG_OS 的客服聊天挂件。保留其 UI/UX 框架，同时注入 RAG_OS 特有的能力（SSE 流式、思考步骤展示、来源引用、留资引导）。用 Vue 3 的 `defineCustomElement` 打包为标准 Web Component。

#### 关键差异：myblog ChatBot vs RAG_OS ChatWidget

以下从 myblog `ChatBot.vue` 出发，逐项说明哪些直接复用、哪些需要改造、哪些是 RAG_OS 独有的新增能力。

| 功能点 | myblog 实现 | RAG_OS 改造策略 |
|--------|-----------|----------------|
| **浮动按钮** | 圆形 FAB，渐变紫色，点击展开/关闭动画 | 直接复用。样式可通过 `--widget-primary` 等 CSS 变量定制品牌色 |
| **面板布局** | 380×520px，头部 + 消息区 + 输入栏三段式 | 直接复用。尺寸增加至 400×560px 以容纳更多信息来源引用 |
| **欢迎消息** | 简单文本，写死在组件中 | 复用结构，但内容改为从配置读取（`COMPANY_NAME`、`AGENT_NAME`），支持 Markdown 格式的富文本欢迎语 |
| **消息气泡** | 用户右对齐、AI 左对齐，圆角卡片样式 | 直接复用。AI 气泡新增：思考步骤折叠、来源引用标签、点赞/点踩按钮 |
| **键入动画** | 三点弹跳动画（bounce keyframes） | 直接复用。但 myblog 在调用完成后一次性显示结果，RAG 改为逐 token 流式追加，anima 停止时机不同 |
| **输入方式** | el-input + Enter 发送 | 直接复用。新增：Shift+Enter 换行、停止生成按钮（流式场景需要）、图片上传（可选） |
| **会话持久化** | `sessionId` 存 localStorage，后端 Redis 存 30min 历史 | 后端改为 MySQL 持久化（已在改造六中实现），前端 `visitorId` 存 localStorage，保持一致 |
| **文章上下文** | 通过 `route.params.id` 检测当前浏览的文章 | 改造为「页面上下文」——读取 `<chat-widget>` 标签上的 `page-context` 属性或 `window.CHAT_PAGE_CONTEXT`，官网可在任意页面注入上下文信息 |
| **流式输出** | **没有**——myblog 的 DeepSeek 调用是同步阻塞的，等完整结果返回后一次性显示 | **核心新增**——RAG_OS 后端已有 SSE 流式接口，前端新增 `useSSE` composable 解析 event stream，逐 token 渲染 |
| **思考步骤展示** | **没有** | **核心新增**——流式过程中实时展示 thinking 事件（查询改写→检索完成→生成中），以可折叠的步骤条呈现 |
| **来源引用** | **没有** | **核心新增**——回答尾部展示 `sources` 中的来源片段，点击可展开查看原文摘要和评分 |
| **留资引导** | **没有** | **核心新增**——接收 `lead_prompt` 事件后展示手机号/微信号输入表单 |
| **快捷问题** | **没有** | **核心新增**——首次打开时展示 3-5 个推荐问题按钮，点击即可发送，无需手动输入 |
| **点赞/点踩** | **没有** | **核心新增**——每条 AI 消息底部展示 👍/👎，反馈存入后端 |
| **API 调用** | `chatApi.sendMessage()` 同步 POST | 改为 SSE 流式调用 `POST /api/widget/chat/stream`，使用 Fetch API + ReadableStream |
| **加载状态** | 三点动画（调用中→完成） | 三点动画 + "正在检索知识库…"/"正在生成回答…" 的阶段提示文字 |

#### 六个新增功能的设计要点

**1. SSE 流式输出（最重要的差异）**

myblog 的 ChatBot 是同步的：发送消息 → 等 1-10 秒 → 一次性显示回复。RAG_OS 必须改为流式。

`useSSE` composable 的核心逻辑：

```
1. 发送 POST /api/widget/chat/stream，获取 Response.body（ReadableStream）
2. 逐行读取文本，解析 SSE 格式（event: xxx \n data: xxx）
3. 根据 event 类型分发：
   - thinking → 追加思考步骤到列表，ThinkingSteps 组件实时更新
   - token → 追加到当前 AgentMessage.content 字符串
   - sources → 更新 AgentMessage.sources 数组
   - system_message → 插入一条系统消息
   - lead_prompt → 设置 showLeadForm = true
   - done → 设置 isProcessing = false，保存最终的 conversationId
   - error → 弹出 ErrorToast
4. 支持 AbortController 中断（用户点击停止按钮）
```

与 myblog 的区别：myblog 在 `sendMessage()` 中直接 `await chatApi.sendMessage()`，单个 promise 完成即结束。RAG_OS 的 `sendMessage()` 启动流后不等待完成，而是在 `ReadableStream` 的循环中持续更新响应式状态，直到收到 `done` 事件或用户中止。

**2. 思考步骤展示**

收到 thinking 事件时，不再只显示三个点动画，而是展示一个有实际含义的步骤：

```
🔍 查询改写：将"iPhone 15 电池"改写为"iPhone 15 电池容量 参数 续航"
📚 知识库检索：检索到 8 个相关文档（耗时 0.32s），上下文共 2048 tokens
✍️ 正在生成回答…
```

用 Vue 的 `v-for` + `TransitionGroup` 实现步骤的逐个出现动画。

**3. 来源引用展示**

收到 sources 事件后，在 AI 消息底部展示来源标签。每个标签可点击展开显示原文摘要和检索/重排序分数。这个功能是 RAG 相比纯 LLM 聊天的核心价值——用户可以验证回答的真实性。

**4. 留资引导**

收到 `lead_prompt` 事件时，消息列表和输入框之间出现一个小表单，包含：
- 手机号输入框（11 位数字校验）
- 微信号输入框（可选）
- 提交按钮

提交后调用 `POST /api/widget/lead`，成功后显示"已收到，客服将在 1 个工作日内联系您"的提示，表单消失。

**5. 快捷问题推荐**

首次打开聊天窗口时，调用 `GET /api/widget/suggestions`，在消息列表顶部展示一排可点击的按钮。用户点击按钮相当于发送了该问题。推荐问题优先从管理员配置中读取，没有配置则用默认的兜底列表。

**6. 页面上下文注入**

借鉴 myblog 的 `route.params.id` 获取文章 ID 的方式，但改为更通用的方案：官网在引入挂件时，通过全局变量或标签属性注入当前页面的上下文信息：

```html
<chat-widget 
  api-base="https://api.example.com/api/widget"
  page-context="用户正在浏览：iPhone 15 产品规格页"
></chat-widget>
<!-- 或动态设置 -->
<script>
window.CHAT_PAGE_CONTEXT = {
  title: document.title,
  product: 'iPhone 15',
  category: '电子产品'
};
</script>
```

前端把 `pageContext` 附加到聊天请求中，后端把它注入到检索的 query 上下文中。

#### UI 设计参考（来自 myblog）

以下 myblog 的设计元素直接沿用：

- **浮动按钮**：右下角 24px 偏移，圆角 50%，渐变背景，hover 放大，z-index 1000
- **面板过渡**：`translateY(20px) + scale(0.95)` 弹入，`translateY(10px) + scale(0.98)` 弹出
- **消息气泡**：用户紫色渐变右对齐，AI 白色左对齐带边框，圆角 14px，font-size 13px
- **键入动画**：三点 bounce keyframes，`animation-delay` 各差 0.2s
- **输入区域**：底部固定，带 border-top 分隔线
- **滚动条**：4px 宽，圆角，浅灰色

#### 更新后的项目结构

```
chat-widget/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── index.html
├── src/
│   ├── main.ts                    # defineCustomElement + 注册
│   ├── App.ce.vue                 # 根组件（参照 myblog ChatBot.vue 结构）
│   ├── composables/
│   │   ├── useChat.ts             # 消息列表、会话 ID、发送/中止（参照 myblog sendMessage 逻辑，改为流式）
│   │   ├── useSSE.ts              # SSE ReadableStream 解析（新增）
│   │   ├── useStorage.ts          # visitorId + sessionId（复用 myblog localStorage 模式）
│   │   └── useWidget.ts           # isOpen、toggle、unreadCount
│   ├── components/
│   │   ├── ChatBubble.vue         # 浮动按钮（直接复用 myblog chatbot-fab 样式）
│   │   ├── ChatWindow.vue         # 面板容器（直接复用 myblog chatbot-panel 样式 + 三段式布局）
│   │   ├── ChatHeader.vue         # 头部（复用 myblog chatbot-header，标题/副标题从 props 读取）
│   │   ├── MessageList.vue        # 消息列表 + 自动滚动（复用 myblog chatbot-body 样式）
│   │   ├── UserMessage.vue        # 用户消息气泡（复用 myblog user bubble 样式）
│   │   ├── AgentMessage.vue       # AI 消息气泡（复用 myblog assistant bubble 样式）+ 新增：思考步骤、来源引用
│   │   ├── ThinkingSteps.vue      # 思考步骤（新增 RAG 独有）
│   │   ├── SourceChips.vue        # 来源引用标签（新增 RAG 独有）
│   │   ├── ChatInput.vue          # 输入框（复用 myblog chatbot-footer + el-input）
│   │   ├── QuickQuestions.vue     # 快捷问题按钮（新增）
│   │   ├── LeadForm.vue           # 留资表单（新增）
│   │   ├── FeedbackButtons.vue    # 点赞/点踩（新增）
│   │   └── ErrorToast.vue         # 错误提示（新增）
│   └── styles/
│       └── variables.css          # CSS 自定义属性
```

#### 初始化方式

```html
<!-- 官网嵌入 -->
<script src="https://your-domain.com/chat-widget.js"></script>
<chat-widget
    api-base="https://your-domain.com/api/widget"
    company-name="您的公司名称"
    primary-color="#2563eb"
    greeting="您好！我是{公司}的智能客服，有什么可以帮您的吗？"
></chat-widget>
```

#### 与 myblog 的后端适配差异

| 层面 | myblog 后端 | RAG_OS 后端 |
|------|-----------|-----------|
| AI 引擎 | 同步调用 DeepSeek API | 异步调用本地 Ollama + RAG 流水线 |
| 会话存储 | Redis，30min TTL | MySQL，24h 过期（已在改造六中设计） |
| 上下文注入 | 后端从 Redis 读 `post:detail:{id}` | 后端用 `pageContext` 参数增强检索 query（写在 prompt 前缀中） |
| 响应格式 | `{ sessionId, reply }` | SSE event stream：`event: token \n data: "..."` |
| 返回方式 | 完整 JSON response | 逐 token 流式推送 |

#### 开发顺序建议

**第 1 步**：搭建项目骨架 + 静态 UI（半天）
- 参照 myblog `ChatBot.vue` 的模板和样式
- 不做后端对接，用 mock 数据渲染消息列表
- 实现气泡展开/关闭动画、键入动画

**第 2 步**：接入 SSE 流式（1 天）
- 实现 `useSSE` composable
- 对接 `POST /api/widget/chat/stream`
- 实现逐 token 追加渲染

**第 3 步**：RAG 独有功能（1 天）
- 思考步骤展示
- 来源引用展示
- 快捷问题推荐
- 留资表单
- 点赞/点踩

**第 4 步**：配置化 + 打包（半天）
- CSS 变量定制品牌色
- props 传参（companyName、primaryColor、greeting 等）
- 构建为单 JS 文件

**第 5 步**：嵌入测试（半天）
- 在 myblog 的某个页面试嵌入 RAG_OS 的挂件
- 验证两个系统可以并存（CSS 不冲突、API 路径不冲突）

---

### 改造八：管理后台从 React 迁移到 Vue 3

**问题**：现有 `rag-agent-front/` 使用 React 18，维护 React 和 Vue 两套技术栈增加团队负担。

**方案**：用 Vue 3 + Vite + Tailwind CSS 重写管理后台，功能和现有 React 版本完全对齐。新建 `rag-agent-front-vue/` 目录，完成后可废弃 React 版本。

#### 核心技术选型

| 项 | React 旧版 | Vue 3 新版 |
|---|-----------|-----------|
| 框架 | React 18 + TSX | Vue 3 (Composition API) + `<script setup>` |
| 状态管理 | useState（组件内） | `ref` / `reactive` + Composables |
| 路由 | 无（Tab 切换） | 无（保持 Tab 切换，不引入 vue-router） |
| 样式 | Tailwind CSS 3.4 | Tailwind CSS 3.4（复用，不改动） |
| HTTP | 手写 fetch 封装 | 复用 fetch 封装，抽取为 `composables/useApi.ts` |
| SSE | 手写 ReadableStream 解析 | Composable `useSSE.ts`（与聊天挂件共享逻辑） |
| 构建 | Vite 5 | Vite 5（不变） |

#### 迁移步骤

**第 1 步：初始化项目**

在 `D:\project\RAG_OS\` 下初始化 Vue 3 + Vite + TypeScript 项目：

```bash
npm create vite@latest rag-agent-front-vue -- --template vue-ts
cd rag-agent-front-vue
npm install
npm install -D tailwindcss@3 postcss autoprefixer
npx tailwindcss init -p
```

配置 `tailwind.config.js`、`postcss.config.js`、`vite.config.ts`（API 代理到 `localhost:8000`）。可直接复制 React 版本中的对应配置，完全相同。

**第 2 步：迁移类型定义**

新建 `src/types/index.ts`，将 React 版 `types.ts` 的内容直接迁移。TypeScript 类型定义与框架无关，可以原样复制。

**第 3 步：迁移 API 层 + Composables**

将 `api/client.ts` 的函数式 API 调用的逻辑抽取为 Composables，映射关系如下：

| React Hook | Vue Composable | 说明 |
|---|---|---|
| `useAuth` | `composables/useAuth.ts` | `user`, `token`, `loading` 用 `ref` 替代 `useState`；`login`/`register`/`logout` 用普通 async 函数 |
| `useChat` | `composables/useChat.ts` | `messages`, `isProcessing`, `conversationId` 用 `ref`；`send`/`abort`/`switchConversation` 等用普通函数。SSE 解析逻辑抽取为独立的 `useSSE` composable |
| `useKnowledge` | `composables/useKnowledge.ts` | `documents`, `loading`, `error` 用 `ref`；`upload`/`remove`/`refresh` 用普通函数 |

SSE 流式解析是最大的差异点。React 版在 `useChat.send()` 中直接写 ReadableStream 解析逻辑，Vue 版应抽取为独立的 `useSSE.ts` composable，输入 `ReadableStream`，产出 `StreamEvent` 的 `ref` 数组，同时支持 `AbortController`。

**第 4 步：重写组件**

React 组件到 Vue SFC 的映射关系（功能一一对应）：

| React 组件 | Vue 组件 | 关键差异 |
|---|---|---|
| `App.tsx` | `App.vue` | `useState(activeTab)` → `ref('chat')`；`useEffect` 键盘快捷键 → `onMounted`/`onUnmounted` 注册事件 |
| `Header.tsx` | `Header.vue` | `onClick` → `@click`；`className` → `:class` |
| `LoginPage.tsx` | `LoginPage.vue` | 表单 `onSubmit` → `@submit.prevent`；`useState` 表单字段 → `ref` + `v-model` |
| `ProtectedRoute.tsx` | `ProtectedRoute.vue` | 条件渲染 `{condition && <Slot/>}` → `<slot v-if="condition" />` |
| `ConversationPanel.tsx` | `ConversationPanel.vue` | 列表渲染 `map()` → `v-for` |
| `ChatArea.tsx` | `ChatArea.vue` | 消息列表 `map()` → `v-for`；滚动到底部用 `nextTick` + `scrollTop` |
| `MessageBubble.tsx` | `MessageBubble.vue` | Markdown 渲染（如有）可复用 `marked` 库 |
| `ChatInput.tsx` | `ChatInput.vue` | `textarea` + `v-model`；`@keydown.enter` 发送 |
| `ThinkingSteps.tsx` | `ThinkingSteps.vue` | 折叠/展开用 `v-show` + `ref` |
| `RetrievalDetail.tsx` | `RetrievalDetail.vue` | 评分展示表格 |
| `SourceChips.tsx` | `SourceChips.vue` | 来源标签列表 |
| `SourcesTab.tsx` | `SourcesTab.vue` | 来源详情面板 |
| `TraceTab.tsx` | `TraceTab.vue` | 推理链路面板 |
| `KnowledgeBase.tsx` | `KnowledgeBase.vue` | 文件上传 + 文档列表；文件拖拽用原生事件绑定 |
| `ContextPanel.tsx` | `ContextPanel.vue` | 上下文信息面板 |

#### 关键差异注意事项

**1. 响应式系统**

React `useState` 返回 `[value, setter]`，更新时用新值替换。Vue 的 `ref` 通过 `.value` 访问和赋值，模板中自动解包。深层对象用 `reactive`，数组操作（push/splice）自动触发更新（Vue 3 的 Proxy 响应式）。

**2. 生命周期对应**

| React | Vue 3 |
|-------|-------|
| `useEffect(fn, [])` | `onMounted(fn)` |
| `useEffect(fn, [dep])` | `watch(dep, fn)` 或 `watchEffect` |
| `useEffect(() => { return cleanup }, [])` | `onUnmounted(cleanup)` |
| `useRef` | `ref` 或 `templateRef` |

**3. 条件渲染 + 列表**

React 的 `{list.map(item => <Comp/>)}` → Vue 的 `<Comp v-for="item in list" :key="item.id" />`

React 的 `{cond && <Comp/>}` → Vue 的 `<Comp v-if="cond" />`

**4. 样式**

Tailwind CSS 用法完全一致，React 的 `className="..."` → Vue 的 `class="..."`。动态类名 React 用模板字符串拼接，Vue 用 `:class="{ active: isActive }"` 对象语法。

#### 迁移后的项目结构

```
rag-agent-front-vue/
├── package.json
├── vite.config.ts             # proxy /api → localhost:8000
├── tailwind.config.js         # 复用 React 版的完整配置
├── postcss.config.js
├── tsconfig.json
├── index.html                 # 中文 locale
├── src/
│   ├── main.ts                # createApp + mount
│   ├── App.vue                # 根组件（Tab 切换 + 布局）
│   ├── index.css              # Tailwind 基础样式
│   ├── types/
│   │   └── index.ts           # 所有类型定义
│   ├── api/
│   │   └── client.ts          # HTTP 请求封装（与 React 版几乎相同）
│   ├── composables/
│   │   ├── useAuth.ts         # 认证状态（user, token, login, register, logout）
│   │   ├── useChat.ts         # 聊天核心逻辑
│   │   ├── useSSE.ts          # SSE 流式解析（可复用）
│   │   └── useKnowledge.ts    # 知识库管理
│   └── components/
│       ├── Header.vue         # 顶部导航栏
│       ├── LoginPage.vue      # 登录/注册表单
│       ├── ProtectedRoute.vue # 认证守卫
│       ├── ChatArea.vue       # 聊天消息列表 + 溯源面板
│       ├── ChatInput.vue      # 消息输入 + 图片上传
│       ├── MessageBubble.vue  # 单条消息（用户/AI）
│       ├── ConversationPanel.vue # 对话列表侧边栏
│       ├── KnowledgeBase.vue  # 知识库管理页面
│       ├── ThinkingSteps.vue  # 思考步骤折叠展示
│       ├── RetrievalDetail.vue # 检索评分详情
│       ├── SourceChips.vue    # 来源标签
│       ├── SourcesTab.vue     # 来源详情面板
│       ├── TraceTab.vue       # 推理链路时间线
│       └── ContextPanel.vue   # 上下文面板
```

#### 验证清单

迁移完成后，逐项对比 React 版确认功能完整：

- [ ] 用户注册/登录/登出
- [ ] 对话列表（创建、切换、删除）
- [ ] Stream 流式对话（逐字展示、支持中断）
- [ ] 图片上传 → 视觉模型描述后对话
- [ ] 思考步骤展示（查询改写 → 检索 → 生成）
- [ ] 来源引用展示（SourceChips + 评分）
- [ ] 推理链路展示（TraceTab 时间线）
- [ ] 知识库文档上传（拖拽 + 进度）+ 列表管理
- [ ] 错误提示（Toast 样式）
- [ ] Ctrl+1 / Ctrl+2 快捷键切换 Tab
- [ ] 401 自动登出 + token 过期处理

---

### 改造九：RBAC 后台管理（用户-角色-权限）

**问题**：当前 RAG_OS 的 User 模型只有一个字段（username + password），没有角色和权限概念。智能客服是独立部署的，系统需要一个完整的后台管理界面，支持多用户登录，按角色区分操作权限，按权限控制功能访问。

**核心要求**：
- 用户可以有多个角色（多对多）
- 角色可以有多个权限（多对多）
- 角色分为管理员和普通用户两个预设角色
- 智能客服的后端是独立部署的，因此 RBAC 数据也存储在自己的 MySQL 中
- 后台管理页面在 Vue 管理后台中新增一个 Tab（或路由）

#### 数据模型设计

当前 User 模型只有 `id`、`username`、`password_hash`、`created_at`。需要新增三张表：

```
User ─────────────────────────────────────┐
  id: UUID (PK)                            │
  username: VARCHAR(50) UNIQUE             │
  password_hash: VARCHAR(200)              │
  roles: UserRole[] ←── 关联表              │ 多对多关系
  created_at: DATETIME                     │
  updated_at: DATETIME (新增)              │
  is_active: BOOLEAN (新增，默认 true)      │
───────────────────────────────────────────┘
                    │
                    │ (多对多，通过中间表 UserRole)
                    ▼
Role ───────────────────────────┐
  id: UUID (PK)                  │
  name: VARCHAR(50) UNIQUE      │  如 "admin"、"user"
  display_name: VARCHAR(50)     │  如 "管理员"、"普通用户"
  description: VARCHAR(200)     │  角色描述
  is_system: BOOLEAN            │  是否为系统预设角色（不可删除）
  permissions: RolePermission[] │ ←── 关联表
  created_at: DATETIME          │
────────────────────────────────┘
                    │
                    │ (多对多，通过中间表 RolePermission)
                    ▼
Permission ─────────────────────┐
  id: UUID (PK)                  │
  code: VARCHAR(100) UNIQUE     │  如 "knowledge:upload"
  display_name: VARCHAR(50)     │  如 "文档上传"
  group_name: VARCHAR(50)       │  权限分组，如 "知识库管理"
  description: VARCHAR(200)     │  权限说明
  created_at: DATETIME          │
────────────────────────────────┘

中间表：
  UserRole: user_id + role_id (复合主键)
  RolePermission: role_id + permission_id (复合主键)
```

#### 权限码设计

按功能模块划分，每个模块有 CRUD 权限：

| 权限分组 | 权限码 | 说明 | 管理员 | 普通用户 |
|---------|--------|------|--------|---------|
| 用户管理 | `user:list` | 查看用户列表 | ✅ | ❌ |
| 用户管理 | `user:create` | 创建用户 | ✅ | ❌ |
| 用户管理 | `user:update` | 编辑用户（启用/禁用） | ✅ | ❌ |
| 用户管理 | `user:delete` | 删除用户 | ✅ | ❌ |
| 角色管理 | `role:list` | 查看角色列表 | ✅ | ❌ |
| 角色管理 | `role:assign` | 分配角色给用户 | ✅ | ❌ |
| 角色管理 | `role:edit` | 编辑角色权限 | ✅ | ❌ |
| 知识库 | `knowledge:upload` | 上传文档 | ✅ | ✅ |
| 知识库 | `knowledge:delete` | 删除文档 | ✅ | ❌ |
| 知识库 | `knowledge:view` | 查看文档列表 | ✅ | ✅ |
| 对话管理 | `chat:send` | 发送消息 | ✅ | ✅ |
| 对话管理 | `chat:history` | 查看自己的对话历史 | ✅ | ✅ |
| 对话管理 | `chat:history_all` | 查看所有用户的对话 | ✅ | ❌ |
| 留资管理 | `lead:list` | 查看留资列表 | ✅ | ❌ |
| 留资管理 | `lead:update` | 更新留资状态 | ✅ | ❌ |
| 统计数据 | `stats:view` | 查看数据统计面板 | ✅ | ❌ |
| 系统设置 | `settings:edit` | 修改系统配置 | ✅ | ❌ |

#### 后端改造

**新建文件：**

| 文件 | 职责 |
|------|------|
| `models/rbac.py` | Role、Permission、UserRole、RolePermission 四个 ORM 模型 |
| `api/admin_users.py` | 用户管理 CRUD（管理员专属） |
| `api/admin_roles.py` | 角色管理（列表 + 分配用户角色） |
| `api/admin_permissions.py` | 权限列表（只读，权限码由代码定义，不开放 CRUD） |
| `core/permissions.py` | 权限常量和依赖注入——`RequirePermission("knowledge:upload")` 装饰器 |
| `db/seed_rbac.py` | 启动时自动创建预设角色和权限，不存在则插入（幂等） |

**修改文件：**

| 文件 | 改动 |
|------|------|
| `models/__init__.py` | 注册 RBAC 模型 |
| `models/conversation.py` | User 表新增 `updated_at`、`is_active` 字段 |
| `api/deps.py` | 新增 `get_current_active_user()`（校验 is_active）、`require_permission(code)` 依赖函数 |
| `api/auth.py` | 注册接口默认给新用户分配"普通用户"角色；登录时检查 is_active |
| `api/documents.py` | 已有接口的 `get_current_user` 替换为带权限检查的依赖 |
| `main.py` | 注册新的 admin 路由；在 lifespan 中调用 `seed_rbac()` |

**关键设计决策：**

1. **权限检查方式**：用 FastAPI 的 `Depends` 依赖注入实现。在路由函数上叠加权限依赖：
   ```python
   @router.delete("/{id}")
   async def delete_doc(
       id: str,
       db: AsyncSession = Depends(get_db),
       current_user: User = Depends(get_current_user),
       _: None = Depends(require_permission("knowledge:delete")),
   ):
   ```

   `require_permission` 内部：
   - 从 JWT 中解析 user_id
   - 查 MySQL 获取用户的角色列表
   - 遍历角色获取对应的权限码集合
   - 检查目标权限码是否在集合中
   - 不在则返回 403 Forbidden

2. **权限缓存**：每次请求都查 MySQL 获取权限会很慢。用 Redis 缓存用户的权限码集合，key 为 `user:perm:{user_id}`，TTL 15 分钟。角色或权限变更时删除对应缓存。

3. **预设数据初始化**（`db/seed_rbac.py`，在 `main.py` 的 lifespan 中调用）：
   - 检查 `admin` 角色是否存在，不存在则创建
   - 检查 `user` 角色是否存在，不存在则创建
   - 检查所有权限码是否已入库，缺失的补入
   - 给 admin 角色分配所有权限
   - 给 user 角色分配基础权限（见上表）
   - 每个检查都是独立的插入操作（`INSERT ... ON DUPLICATE KEY UPDATE` 方式的幂等逻辑）

4. **注册时默认角色**：`api/auth.py` 的 register 接口中，用户创建成功后自动关联"普通用户"角色（`role_id = (SELECT id FROM role WHERE name = 'user')`）。第一个注册的用户可以手动在数据库或管理页面提升为 admin。

5. **JWT 中不存权限**：Token 只存 `{"sub": user_id}`，权限在每次请求时实时查询（配合 Redis 缓存）。这样角色变更无需重新登录。

#### 前端改造（管理后台新增页面）

改造八中已有 Vue 3 管理后台 `rag-agent-front-vue/`，在其基础上新增一个 Tab（或路由）和对应页面。

**新增文件：**

| 文件 | 职责 |
|------|------|
| `src/components/AdminUsers.vue` | 用户列表（表格：用户名、角色标签、状态、操作按钮） |
| `src/components/AdminRoles.vue` | 角色列表 + 角色权限编辑（左侧角色列表，右侧权限复选框树） |
| `src/components/AdminLeads.vue` | 留资列表（表格：联系方式、问题、状态、创建时间） |
| `src/components/AdminStats.vue` | 数据统计面板（总对话数、满意度、热门问题 Top N、留资趋势） |
| `src/components/AdminSettings.vue` | 系统设置（公司名称、客服电话、欢迎语等，对应 config.py 中的值） |
| `src/composables/usePermission.ts` | 前端权限检查（`hasPermission(code) → boolean`），控制按钮显示/隐藏 |
| `src/api/admin.ts` | 管理后台 API 调用（用户 CRUD、角色列表、权限列表、分配角色、留资列表、统计数据） |

**修改文件：**

| 文件 | 改动 |
|------|------|
| `App.vue` | Tab 新增"后台管理"项（仅管理员可见）；权限引导——当前用户角色不是管理员时，此 Tab 不显示 |
| `Header.vue` | 顶部 Tab 栏增加"后台管理"入口，用 `v-if="hasPermission('stats:view')"` 控制 |

**后台管理 Tab 下的子页面布局**：

```
┌──────────────────────────────────────────┐
│ Header: 聊天 | 知识库 | 后台管理 (仅admin可见) │
├────┬─────────────────────────────────────┤
│    │ 后台管理 Tab 内是一组子 Tab 或侧边栏  │
│ 侧 │  ┌─ 用户管理                        │
│ 边 │  ├─ 角色管理                        │
│ 栏 │  ├─ 留资列表                        │
│    │  ├─ 数据统计                        │
│    │  └─ 系统设置                        │
├────┴─────────────────────────────────────┤
│              正文内容区                    │
└──────────────────────────────────────────┘
```

**前端权限控制逻辑**（`usePermission.ts`）：

```typescript
// 登录时从后端获取当前用户的权限码列表
// GET /api/admin/permissions/my → ["chat:send", "knowledge:upload", ...]
// 存入 Pinia store 或组件中的 ref

function hasPermission(code: string): boolean {
  return permissions.value.includes(code)
}

// 使用方式（组件中）:
// <el-button v-if="hasPermission('user:create')">创建用户</el-button>
```

前端权限检查是 UI 层面的辅助控制（隐藏按钮），真正的安全校验在后端依赖注入中完成。即使用户绕过前端直接调 API，后端的 `require_permission` 也会拦截。

#### 独立部署说明

智能客服后端是独立部署的，这意味着：

1. RBAC 所有数据（User、Role、Permission、UserRole、RolePermission 表）都存在这套系统的 MySQL 中，不依赖外部用户系统
2. 如果未来需要对接外部 SSO 或 LDAP，可以在 `api/auth.py` 中增加 OAuth2/OIDC 登录作为可选的认证方式，但 RBAC 本身的用户-角色-权限映射仍然在本系统内维护
3. 初始管理员账号通过种子脚本创建（`db/seed_rbac.py`），或通过命令行工具手动设置某个用户的角色为 admin

---

## 四、改造完成后完整调用链路

```
用户: "iPhone 15 电池容量多少？"
    │
    ▼
┌──────────────────────────────────────┐
│ 1. Intent Router                     │  core/intent_router.py（新建）
│    classify() → "business"           │
└────────────────┬─────────────────────┘
                 ▼
┌──────────────────────────────────────┐
│ 2. Query Rewriter                    │  core/query_rewriter.py（不改）
│    "iPhone 15 电池容量 参数 续航"    │
└────────────────┬─────────────────────┘
                 ▼
┌──────────────────────────────────────┐
│ 3. Dual-Path Retrieval               │  services/retriever.py（修改）
│                                      │
│  浅层（70%权重）                      │
│  ├─ Milvus dense search              │  现有
│  └─ BM25 keyword search              │  现有
│  → RRF 融合                          │
│                                      │
│  深层（30%权重）                      │
│  ├─ NER: [iPhone 15, 电池容量]       │  core/ner.py（新建）
│  ├─ Graph expand:                    │  core/graph_store.py（新建）
│  │   iPhone 15 → [电池参数, 续航, A17]
│  └─ Milvus tag filter + BM25 again   │
│  → 独立评分                          │
│                                      │
│  加权融合 → reranker → 输出           │
└────────────────┬─────────────────────┘
                 ▼
┌──────────────────────────────────────┐
│ 4. Parent-Child Context Expansion    │  core/chunker_v2.py（新建）
│    子块 → 父块 → 完整上下文          │
└────────────────┬─────────────────────┘
                 ▼
┌──────────────────────────────────────┐
│ 5. Structured Prompt + Timeout       │  core/llm.py（修改）
│    BUSINESS_PROMPT 严格约束          │  core/timeout_guard.py（新建）
│    ├─ 正常: 流式输出                 │
│    └─ 超时(5s): 留资引导            │
└────────────────┬─────────────────────┘
                 ▼
┌──────────────────────────────────────┐
│ 6. SSE Response → 前端挂件           │  api/widget_chat.py（新建）
│    token × N + sources + done        │  chat-widget/（新建）
└──────────────────────────────────────┘
```

---

## 五、实施优先级

| 优先级 | 改造项 | 新建文件 | 修改文件 | 风险 | 预计工作量 |
|--------|--------|---------|---------|------|-----------|
| **P0** | 意图路由 | `core/intent_router.py` | `rag_pipeline.py`, `llm.py` | 低 | 0.5 天 |
| **P0** | 结构化 Prompt | 无 | `core/llm.py`, `config.py`, `.env` | 低 | 0.5 天 |
| **P0** | 匿名 Widget API | `api/widget_chat.py`, `schemas/widget.py` | `main.py`, `rag_pipeline.py`, `models/conversation.py` | 低 | 1 天 |
| **P1** | 父-子分块 | `core/chunker_v2.py` | `vectordb.py`, `retriever.py`, `document_service.py` | 中 | 1.5 天 |
| **P1** | NER + 图谱 | `core/ner.py`, `core/graph_store.py` | `retriever.py`, `vectordb.py`, `chunker_v2.py` | 中 | 2 天 |
| **P1** | 超时 + 留资 | `core/timeout_guard.py`, `models/lead.py`, `api/lead.py` | `rag_pipeline.py` | 低 | 1 天 |
| **P1** | RBAC 后台管理 | `models/rbac.py`, `api/admin_users.py`, `api/admin_roles.py`, `api/admin_permissions.py`, `core/permissions.py`, `db/seed_rbac.py` + 前端 `Admin*.vue` 5个页面 + `usePermission.ts` | `models/conversation.py`, `api/deps.py`, `api/auth.py`, `api/documents.py`, `main.py`, `App.vue`, `Header.vue` | 低 | 2.5 天 |
| **P2** | 前端聊天挂件 (Vue 3) | `chat-widget/`（整个项目） | 无 | 低 | 3.5 天 |
| **P2** | 管理后台迁移 Vue 3 | `rag-agent-front-vue/`（整个项目） | 无（React 版后续废弃） | 低 | 3 天 |

P0 三项合计约 2 天，完成后系统就能像一个正经客服那样回答问题了，且支持匿名访问。P1 四项合计约 7 天（父-子分块 1.5 + NER 图谱 2 + 超时留资 1 + RBAC 2.5），是检索精度和系统管理能力的核心提升。P2 两项合计约 6.5 天，前端全面 Vue 化，可并行开发。

P2 的聊天挂件预计比之前多 0.5 天（3 天→3.5 天），因为 SSE 流式 + 思考步骤 + 来源引用 + 留资 + 反馈这五个 RAG 独有功能需要从零实现，而 myblog 的 ChatBot 只有同步聊天一个模式。RBAC 提升到 P1 是因为它涉及后续所有管理接口的权限校验改造，属于基础设施型改动，应在管理功能大规模上线前完成。

---

## 六、风险与注意事项

1. **Milvus schema 变更**：新增 `parent_id` 和 `entity_tags` 字段需要重建 collection，已有向量数据会丢失。建议先在测试环境验证，或使用 Milvus 的 `alter_collection`（如果版本支持）。

2. **图谱持久化**：`graph_store` 为内存实现 + JSON 持久化，重启时会完整加载 JSON 文件。如果知识库文档量极大（>10 万 chunk），JSON 文件可能过大，届时需考虑 SQLite 存储或轻量图数据库。

3. **NER 准确性**：用通用 LLM（qwen2.5）做 NER 而非专用模型，在垂直领域（如医疗、法律）可能准确率不够。建议先用测试集验证，根据错误 case 迭代 few-shot prompt。

4. **Ollama 模型选择**：`.env` 中当前的 `qwen2.5:1.5b` 只适合快速测试。生产环境建议至少 `qwen2.5:7b-instruct` 做对话、`qwen2.5:14b` 做 Agent。

5. **Vue Custom Element 兼容性**：`defineCustomElement` 是 Vue 3.3+ 的特性，打包体积约 40-60KB（gzip 后约 15KB）。Shadow DOM 模式下部分 CSS 特性受限（如 `@font-face` 需在 shadow root 内声明、`:host` 选择器的优先级问题）。如需支持 IE11 等老旧浏览器需额外 polyfill，但 2026 年基本不需要。

6. **SSE 流式 vs 同步聊天的体验差异**：myblog 的 ChatBot 是同步模式（等完整结果→一次性渲染），RAG_OS 是流式（逐 token 追加）。流式模式下消息气泡需要在生成过程中不断重绘，需要处理滚动跟随的抖动问题。myblog 的键入动画是纯视觉装饰（不依赖实际数据到达），但 RAG_OS 的键入动画需要与实际 token 流同步——收到第一个 token 时动画结束、开始渲染文字。

7. **聊天挂件与宿主页面的样式冲突**：Shadow DOM 已隔离大部分样式，但表单元素的 focus 态、滚动条样式、字体平滑等全局属性可能受宿主页面影响。建议挂件内部显式设置 `all: initial` 重置，再自行构建样式层。在 myblog 上嵌入测试时需特别验证 Element Plus 全局样式不干扰挂件。

8. **两个系统共用 API 路径**：如果官网同时部署 myblog 和 RAG_OS（都在同一域名下通过 Nginx 代理），需确保 `/api/widget/*`（RAG 聊天挂件）和 `/api/post/ai/chat`（myblog 聊天机器人）路径不冲突。建议 Nginx 配置中明确不同 upstream 的路由规则。

9. **Vue vs React 组件行为差异**：迁移管理后台时注意 `v-model` 是语法糖（相当于 `:value` + `@input`），与 React 受控组件的 `value` + `onChange` 语义不完全一致。`watch` 默认不深度监听（需加 `{deep: true}`），与 React `useEffect` 默认在每次渲染后运行的习惯不同，需要适应。

10. **留资数据安全**：手机号和微信号是敏感个人信息，需确保数据库访问权限受控、传输过程 HTTPS 加密，按《个人信息保护法》要求告知用户数据用途。

11. **RBAC 权限粒度权衡**：当前设计是接口级别的权限控制（`require_permission("knowledge:delete")`）。如果未来需要数据级别的权限（如"用户A只能看自己上传的文档"），需要在业务查询中叠加 `user_id` 过滤条件，而非在 RBAC 层实现。当前设计已足够覆盖智能客服的场景——数据级权限是业务逻辑，不应混入 RBAC 框架。

12. **JWT Token 不存权限**：权限变更是即时的（因为每次请求实时查询 + Redis 缓存），不需要用户重新登录等待 token 刷新。但这也意味着每次 API 调用都多一次 Redis 查询。如果性能敏感，可以在 token payload 中增加一个 `perm_version` 字段，缓存命中时直接使用，缓存不命中时查 DB 并更新缓存。这是优化项，初期不做。

13. **管理员账号初始化**：`db/seed_rbac.py` 在启动时只会创建角色和权限数据，不会自动创建管理员用户（因为密码不可预设）。初始化管理员账号的方式：先通过 `/api/auth/register` 注册一个普通用户，再在 MySQL 中手动插入 `user_roles` 关联记录将其绑定到 admin 角色，或通过命令行工具执行。
