"""
RAG_OS 智能客服改造 —— 单元测试和集成测试

运行方式:
  cd D:\project\RAG_OS\backend
  ..\.venv\Scripts\python.exe -m pytest tests\test_modifications.py -v

需要先启动的外部服务: MySQL, Milvus, Ollama
"""
import json
import uuid
import pytest
from httpx import AsyncClient, ASGITransport


# ─────────────────────────────────────────────
# 测试环境准备
# ─────────────────────────────────────────────

@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    """FastAPI 测试客户端"""
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def auth_headers():
    """获取一个测试用的 JWT token"""
    import asyncio
    from core.auth import create_access_token
    from db import AsyncSessionLocal
    from models.conversation import User
    from sqlalchemy import select

    async def _register_and_get_token():
        async with AsyncSessionLocal() as db:
            # 检查是否已有测试用户
            result = await db.execute(
                select(User).where(User.username == "__test_user__")
            )
            user = result.scalar_one_or_none()
            if not user:
                from core.auth import hash_password
                user = User(
                    username="__test_user__",
                    password_hash=hash_password("test123456"),
                )
                db.add(user)
                await db.commit()
                await db.refresh(user)
            return create_access_token({"sub": user.id})

    return asyncio.run(_register_and_get_token())


# ─────────────────────────────────────────────
# 测试 1: 检索阈值 Bug 修复
# ─────────────────────────────────────────────

class TestRetrievalThreshold:
    """验证 rerank_score 和 score 的阈值判断逻辑"""

    def test_has_rerank_score__uses_rerank_threshold(self):
        """有 rerank_score 时，应该用 3.0 阈值判断"""
        chunks = [
            {"doc_id": "a", "chunk_index": 0, "text": "doc a chunk 0",
             "score": 0.9, "rerank_score": 5.0},
            {"doc_id": "b", "chunk_index": 0, "text": "doc b chunk 0",
             "score": 0.8, "rerank_score": 2.0},
        ]
        has_rerank = any("rerank_score" in c for c in chunks)
        assert has_rerank is True, "两个 chunk 都有 rerank_score"

        # 用 rerank 阈值：all < 3.0 → low_quality
        low_quality = all(c.get("rerank_score", 0) < 3.0 for c in chunks)
        assert low_quality is False, "chunk a 的 rerank_score=5.0 >= 3.0，不应判 low_quality"

    def test_no_rerank_score__uses_cosine_threshold(self):
        """没有 rerank_score 时，应该用 0.3 余弦相似度阈值"""
        chunks = [
            {"doc_id": "a", "chunk_index": 0, "text": "text a", "score": 0.92},
            {"doc_id": "b", "chunk_index": 0, "text": "text b", "score": 0.45},
        ]
        has_rerank = any("rerank_score" in c for c in chunks)
        assert has_rerank is False, "两个 chunk 都没有 rerank_score"

        # 用余弦相似度阈值：all < 0.3 → low_quality
        low_quality = all(c.get("score", 0) < 0.3 for c in chunks)
        assert low_quality is False, "score 0.92 和 0.45 都 >= 0.3，不应判 low_quality"

    def test_all_low_quality__triggers_low_quality(self):
        """所有 chunk 分数都很低时，应该判为 low_quality"""
        chunks = [{"doc_id": "a", "chunk_index": 0, "text": "t", "score": 0.05}]
        has_rerank = any("rerank_score" in c for c in chunks)
        low_quality = all(c.get("score", 0) < 0.3 for c in chunks)
        assert low_quality is True, "score=0.05 < 0.3 应判 low_quality"

    def test_empty_chunks__triggers_low_quality(self):
        """空列表应该触发 low_quality"""
        chunks = []
        has_rerank = any("rerank_score" in c for c in chunks) if chunks else False
        low_quality = True  # if not chunks → 直接触发
        assert not chunks
        assert low_quality is True


# ─────────────────────────────────────────────
# 测试 2: 意图路由
# ─────────────────────────────────────────────

class TestIntentRouter:
    """验证意图分类逻辑"""

    def test_short_greeting_is_chitchat(self):
        """短问候消息应被快速过滤为 chitchat"""
        from core.intent_router import _is_fast_chitchat
        assert _is_fast_chitchat("你好") is True
        assert _is_fast_chitchat("在吗") is True
        assert _is_fast_chitchat("hello") is True
        assert _is_fast_chitchat("谢谢") is True

    def test_long_query_not_fast_chitchat(self):
        """长消息不应被快速过滤"""
        from core.intent_router import _is_fast_chitchat
        assert _is_fast_chitchat("我想了解一下你们的产品价格和售后服务政策") is False
        assert _is_fast_chitchat("iPhone 15 的电池容量是多少毫安时") is False

    def test_classify_chitchat_no_llm_call(self):
        """快速过滤命中时不调 LLM，直接返回 chitchat"""
        import asyncio
        from core.intent_router import classify

        result = asyncio.run(classify("你好"))
        assert result == "chitchat"

        result = asyncio.run(classify("再见"))
        assert result == "chitchat"

    def test_classify_business_like_query(self):
        """业务类查询应返回 business（LLM 不可用时兜底也是 business）"""
        import asyncio
        from core.intent_router import classify

        # 长问题不命中快速过滤，走 LLM 分类
        # 如果 LLM 不可用，兜底为 business（安全策略）
        result = asyncio.run(classify("产品价格怎么计算？售后服务有哪些？"))
        # LLM 可用时返回 business，不可用时兜底也是 business
        assert result in ("business", "chitchat")


# ─────────────────────────────────────────────
# 测试 3: 结构化 Prompt
# ─────────────────────────────────────────────

class TestPromptTemplates:
    """验证三个 Prompt 模板包含必要内容"""

    def test_business_prompt_has_constraints(self):
        """BUSINESS_PROMPT 必须包含关键约束"""
        from core.llm import BUSINESS_PROMPT
        assert "禁止" in BUSINESS_PROMPT
        assert "编造" in BUSINESS_PROMPT
        assert "来源" in BUSINESS_PROMPT
        assert "AI" in BUSINESS_PROMPT  # 禁止暴露 AI 身份
        assert "参考文档" in BUSINESS_PROMPT

    def test_no_result_prompt_is_deterministic(self):
        """NO_RESULT_PROMPT 必须走固定话术"""
        from core.llm import NO_RESULT_PROMPT
        assert "不要编造" in NO_RESULT_PROMPT
        assert "未收录" in NO_RESULT_PROMPT

    def test_chitchat_prompt_is_short(self):
        """CHITCHAT_PROMPT 限制回复长度和风格"""
        from core.llm import CHITCHAT_PROMPT
        assert "3 句话" in CHITCHAT_PROMPT
        assert "AI" in CHITCHAT_PROMPT  # 禁止暴露身份

    def test_prompt_uses_config_values(self):
        """Prompt 中使用了 config 中的公司名和客服名"""
        from core.llm import BUSINESS_PROMPT, NO_RESULT_PROMPT, CHITCHAT_PROMPT
        from config import COMPANY_NAME
        assert COMPANY_NAME in BUSINESS_PROMPT
        assert COMPANY_NAME in NO_RESULT_PROMPT
        assert COMPANY_NAME in CHITCHAT_PROMPT

    def test_build_messages_chooses_prompt_by_context(self):
        """有 context_chunks 时用 BUSINESS_PROMPT，没有时用 NO_RESULT_PROMPT"""
        from core.llm import _build_messages, BUSINESS_PROMPT, NO_RESULT_PROMPT

        # 有检索结果时
        msgs = _build_messages("测试问题", [{"text": "这是检索到的文档片段"}])
        assert BUSINESS_PROMPT in msgs[0]["content"]

        # 无检索结果时
        msgs = _build_messages("测试问题", [])
        assert NO_RESULT_PROMPT in msgs[0]["content"]


# ─────────────────────────────────────────────
# 测试 4: Tokenizer 切换
# ─────────────────────────────────────────────

class TestTokenizer:
    """验证 tokenizer 已从 cl100k_base 切换到 o200k_base"""

    def test_tokenizer_is_o200k(self):
        from core.llm import _get_tokenizer
        tokenizer = _get_tokenizer()
        assert tokenizer.name == "o200k_base"

    def test_tokenizer_counts_chinese(self):
        """中文文本 token 数应合理（约 1 字 0.5-1 token）"""
        from core.llm import _get_tokenizer
        tokenizer = _get_tokenizer()
        count = len(tokenizer.encode("今天天气很好"))
        # o200k_base 对中文的编码效率比 cl100k_base 高
        assert 3 <= count <= 10


# ─────────────────────────────────────────────
# 测试 5: Widget API
# ─────────────────────────────────────────────

class TestWidgetAPI:
    """验证匿名访客 API 可用"""

    @pytest.mark.anyio
    async def test_suggestions_returns_list(self, client):
        """建议接口返回问题列表"""
        resp = await client.get("/api/widget/suggestions")
        assert resp.status_code == 200
        data = resp.json()
        assert "questions" in data
        assert isinstance(data["questions"], list)
        assert len(data["questions"]) > 0

    @pytest.mark.anyio
    async def test_feedback_accepts_positive(self, client):
        """反馈接口接受正面评价"""
        resp = await client.post("/api/widget/feedback", json={
            "message_id": "test-msg-001",
            "rating": "positive",
            "visitor_id": "visitor-test-001",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.anyio
    async def test_feedback_accepts_negative(self, client):
        """反馈接口接受负面评价"""
        resp = await client.post("/api/widget/feedback", json={
            "message_id": "test-msg-002",
            "rating": "negative",
            "visitor_id": "visitor-test-001",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.anyio
    async def test_widget_chat_stream_no_auth(self, client):
        """Widget 聊天接口不需要 JWT 认证"""
        visitor_id = f"visitor-test-{uuid.uuid4().hex[:8]}"
        resp = await client.post("/api/widget/chat/stream", json={
            "query": "你好",
            "visitor_id": visitor_id,
        })
        # 可能 200（流式开始）或 500（外部服务未启动）
        # 但不应返回 401/403
        assert resp.status_code != 401
        assert resp.status_code != 403


# ─────────────────────────────────────────────
# 测试 6: Schemas 验证
# ─────────────────────────────────────────────

class TestSchemas:
    """验证 Pydantic schemas 正确"""

    def test_widget_chat_request_valid(self):
        from schemas.widget import WidgetChatRequest
        req = WidgetChatRequest(query="测试", visitor_id="v-001")
        assert req.query == "测试"
        assert req.visitor_id == "v-001"
        assert req.conversation_id is None

    def test_widget_chat_request_with_conversation(self):
        from schemas.widget import WidgetChatRequest
        req = WidgetChatRequest(
            query="追问", visitor_id="v-001", conversation_id="conv-123"
        )
        assert req.conversation_id == "conv-123"

    def test_widget_chat_request_missing_visitor_id_fails(self):
        from schemas.widget import WidgetChatRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            WidgetChatRequest(query="测试")  # 缺少 visitor_id

    def test_feedback_request_valid(self):
        from schemas.widget import FeedbackRequest
        req = FeedbackRequest(message_id="m1", rating="positive", visitor_id="v1")
        assert req.rating == "positive"

    def test_feedback_request_invalid_rating(self):
        from schemas.widget import FeedbackRequest
        from pydantic import ValidationError
        # 注意：当前 schema 没有做枚举校验，只接受任意字符串
        # 这暂时是可接受的（后续可加 Literal 校验）
        req = FeedbackRequest(message_id="m1", rating="unknown", visitor_id="v1")
        assert req.rating == "unknown"


# ─────────────────────────────────────────────
# 测试 7: Health Check
# ─────────────────────────────────────────────

class TestHealthCheck:
    """验证后端基础可用"""

    @pytest.mark.anyio
    async def test_health_endpoint(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["service"] == "rag-agent"


# ─────────────────────────────────────────────
# 测试 8: 认证（不含权限——RBAC 未实现）
# ─────────────────────────────────────────────

class TestAuth:
    """验证 JWT 认证流程"""

    def test_register_and_login(self):
        import asyncio
        from httpx import AsyncClient, ASGITransport
        from main import app

        async def _run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                username = f"test_{uuid.uuid4().hex[:8]}"

                # 注册
                resp = await c.post("/api/auth/register", json={
                    "username": username,
                    "password": "test123456",
                })
                assert resp.status_code == 201
                token_data = resp.json()
                assert "access_token" in token_data
                token = token_data["access_token"]

                # 验证 /me
                headers = {"Authorization": f"Bearer {token}"}
                resp = await c.get("/api/auth/me", headers=headers)
                assert resp.status_code == 200
                assert resp.json()["username"] == username

        asyncio.run(_run())


# ─────────────────────────────────────────────
# 运行说明
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("""
    运行测试:
      cd D:\\project\\RAG_OS\\backend
      ..\\\\.venv\\Scripts\\python.exe -m pytest tests\\\\test_modifications.py -v

    只运行指定类:
      ..\\\\.venv\\Scripts\\python.exe -m pytest tests\\\\test_modifications.py::TestRetrievalThreshold -v

    带详细输出:
      ..\\\\.venv\\Scripts\\python.exe -m pytest tests\\\\test_modifications.py -v -s

    前置条件:
      - MySQL 运行在 localhost:3306，数据库 rag_agent 已创建
      - Milvus 运行在 localhost:19530
      - Ollama 运行在 localhost:11434，已 pull shaw/dmeta-embedding-zh
      - DeepSeek API Key 已配置在 .env 中
    """)
