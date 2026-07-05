import json
import time
from typing import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from models.conversation import Conversation, Message, CN_TZ
from services.retriever import retrieve
from core.llm import chat, chat_stream
from datetime import datetime
from core.query_rewriter import rewrite_query
from core.intent_router import classify
from core.logger import logger
import tiktoken
from core.multi_hop_agent import should_use_multi_hop, run_multi_hop


def _now():
    return time.strftime("%H:%M", time.localtime())


async def run(
    db: AsyncSession, query: str, conversation_id: str | None = None,
    user_id: str | None = None, image: str | None = None
) -> dict:
    """非流式：检索 → 生成 → 存储 → 返回完整结果"""
    conv = await _ensure_conversation(db, conversation_id, user_id)

    # 图片解析
    img_desc = ""
    if image:
        img_desc = await _describe_chat_image(image, query)
        search_query = f"{img_desc} {query}" if img_desc else query
    else:
        search_query = query

    msg_content = f"[图片] {query}" if image else query
    user_msg = Message(conversation_id=conv.id, role="user", content=msg_content)
    db.add(user_msg)
    await db.commit()

    thinking = [
        {"type": "search", "text": f"查询改写：将「{query}」转化为检索查询"},
    ]

    t0 = time.time()
    chunks = await retrieve(search_query)
    elapsed = time.time() - t0

    thinking.append({
        "type": "result",
        "text": f"从知识库中检索到 {len(chunks)} 个相关文档（耗时 {elapsed:.2f}s）,"
                f"上下文共 {_count_tokens(chunks)} tokens",
    })
    thinking.append({"type": "generate", "text": "综合检索结果，生成回答"})

    history = await _load_history(db, conv.id)
    gen_query = f"[图片内容] {img_desc}\n\n用户问题：{query}" if img_desc else query
    answer = await chat(gen_query, chunks, history)
    sources = _build_sources(chunks)
    trace = _build_trace(elapsed)

    agent_msg = Message(
        conversation_id=conv.id, role="agent", content=answer,
        thinking=thinking, sources=sources, trace=trace,
    )
    if conv.title == "新对话":
        conv.title = await _generate_title(query, answer)
    db.add(agent_msg)
    conv.updated_at = datetime.now(CN_TZ)
    await db.commit()

    return {
        "answer": answer,
        "thinking": thinking,
        "sources": sources,
        "trace": trace,
        "conversation_id": conv.id,
    }


async def run_stream(
    db: AsyncSession, query: str, conversation_id: str | None = None,
    user_id: str | None = None, image: str | None = None,
    visitor_id: str | None = None,
) -> AsyncIterator[dict]:
    """
    流式：每个步骤以 {event, data} dict 产出，
    调用方（api/chat.py）转成 SSE 发送。
    """
    conv = await _ensure_conversation(db, conversation_id, user_id, visitor_id)

    # 图片解析
    if image:
        yield {
            "event": "thinking",
            "data": json.dumps(
                {"type": "search", "text": "正在分析上传的图片…"},
                ensure_ascii=False,
            ),
        }
        img_desc = await _describe_chat_image(image, query)
        # 图片描述拼到 query 前，帮助检索命中知识库；同时保留原始 query
        search_query = f"{img_desc} {query}" if img_desc else query
    else:
        search_query = query
        img_desc = ""

    # 存储用户消息（含图片标记）
    msg_content = query
    if image:
        msg_content = f"[图片] {query}"
    user_msg = Message(conversation_id=conv.id, role="user", content=msg_content)
    db.add(user_msg)
    await db.commit()

    # ── 意图路由 ──
    intent = await classify(search_query)
    if intent == "chitchat":
        # 闲聊：直接用模板回复，不走检索流水线
        from core.llm import CHITCHAT_PROMPT
        from core.llm import chat_stream as _chat_stream

        full_answer = ""
        try:
            async for token in _chat_stream(search_query, []):
                full_answer += token
                yield {
                    "event": "token",
                    "data": json.dumps({"text": token}, ensure_ascii=False),
                }
        except Exception:
            full_answer = "您好！有什么可以帮您的吗？😊"
            yield {
                "event": "token",
                "data": json.dumps({"text": full_answer}, ensure_ascii=False),
            }

        yield {"event": "sources", "data": json.dumps([])}
        yield {"event": "trace", "data": json.dumps([])}
        yield {"event": "done", "data": json.dumps({"conversation_id": conv.id})}

        # 存储闲聊消息
        agent_msg = Message(
            conversation_id=conv.id, role="agent", content=full_answer,
            thinking=[], sources=[], trace=[],
        )
        db.add(agent_msg)
        conv.updated_at = datetime.now(CN_TZ)
        await db.commit()
        return

    # ── 查询改写 ──
    try:
        rewritten = await rewrite_query(search_query)
    except Exception:
        rewritten = search_query

    yield {
        "event": "thinking",
        "data": json.dumps(
            {"type": "search", "text": f"查询改写：将「{query}」改写为「{rewritten}」"},
            ensure_ascii=False,
        ),
    }
    if await should_use_multi_hop(query):
        async for ev in run_multi_hop(query):
            yield ev
        return  # 多跳流程结束，不继续往下走

    t0 = time.time()
    try:
        chunks = await retrieve(search_query, rewritten)

        # 判断是否有 reranker 参与：有 rerank_score 字段说明 reranker 跑了
        has_rerank = any("rerank_score" in c for c in chunks) if chunks else False

        if has_rerank:
            # reranker 跑了 → 用 3.0 阈值（bge-reranker raw logit 范围 -10~+10）
            low_quality = all(c.get("rerank_score", 0) < 3.0 for c in chunks)
        else:
            # reranker 没跑（candidates ≤ 5）→ 用 Milvus 余弦相似度阈值 0.3
            low_quality = all(c.get("score", 0) < 0.3 for c in chunks)

        if not chunks or low_quality:
            # 检索结果空或质量过低，切换到联网 Agent
            logger.info("触发联网搜索",
                        extra={"event": "fallback_web", "query": query[:60],
                               "chunks": len(chunks), "has_rerank": has_rerank})
            from core.langchain_agent import run_agent_stream
            async for ev in run_agent_stream(query):
                yield ev
            return
    except Exception:
        chunks = []
    elapsed = time.time() - t0
    token_count = _count_tokens(chunks)

    logger.info("检索完成",
                extra={"event": "retrieval_end", "query": query[:60],
                       "chunks": len(chunks), "tokens": token_count,
                       "elapsed_ms": int(elapsed * 1000)})

    yield {
        "event": "thinking",
        "data": json.dumps(
            {"type": "result", "text": f"从知识库中检索到 {len(chunks)} 个相关文档（耗时 {elapsed:.2f}s），"
                                      f"上下文共 {token_count} tokens"},
            ensure_ascii=False,
        ),
    }
    yield {
        "event": "thinking",
        "data": json.dumps(
            {"type": "generate", "text": "综合检索结果，生成回答"},
            ensure_ascii=False,
        ),
    }

    # ── 生成阶段（逐 token） ──
    full_answer = ""
    history = await _load_history(db, conv.id)
    # 如果有图片描述，拼入 query 供 LLM 引用
    gen_query = f"[图片内容] {img_desc}\n\n用户问题：{query}" if img_desc else query
    try:
        async for token in chat_stream(gen_query, chunks, history):
            full_answer += token
            yield {
                "event": "token",
                "data": json.dumps({"text": token}, ensure_ascii=False),
            }
    except Exception as e:
        yield {
            "event": "error",
            "data": json.dumps({"message": f"生成出错: {str(e)}"}),
        }
        logger.warning("生成出错",
                       extra={"event": "generation_error", "query": query[:60],
                              "error": str(e)})
        return

    gen_elapsed = time.time() - t0
    gen_tokens = len(full_answer)
    logger.info("生成完成",
                extra={"event": "generation_end", "query": query[:60],
                       "tokens": gen_tokens, "elapsed_ms": int(gen_elapsed * 1000)})

    # ── 发送元信息 ──
    search_text = rewritten if rewritten != query else query
    thinking = [
        {"type": "search", "text": f"查询改写：将「{query}」改写为「{search_text}」"},
        {"type": "result", "text": f"从知识库中检索到 {len(chunks)} 个相关文档（耗时 {elapsed:.2f}s）,"
                                   f"上下文共 {_count_tokens(chunks)} tokens"},
        {"type": "generate", "text": "综合检索结果，生成回答"},
    ]
    sources = _build_sources(chunks)
    trace = _build_trace(elapsed)

    yield {"event": "sources", "data": json.dumps(sources, ensure_ascii=False)}
    yield {"event": "trace", "data": json.dumps(trace, ensure_ascii=False)}
    yield {
        "event": "done",
        "data": json.dumps({"conversation_id": conv.id}),
    }

    # ── 存储 Agent 消息 ──
    agent_msg = Message(
        conversation_id=conv.id, role="agent", content=full_answer,
        thinking=thinking, sources=sources, trace=trace,
    )
    if conv.title == "新对话":
        conv.title = await _generate_title(query, full_answer)
    db.add(agent_msg)
    conv.updated_at = datetime.now(CN_TZ)
    await db.commit()


async def _ensure_conversation(
    db: AsyncSession, cid: str | None, user_id: str | None = None,
    visitor_id: str | None = None,
) -> Conversation:
    if cid:
        conv = (
            await db.execute(select(Conversation).where(Conversation.id == cid))
        ).scalar_one_or_none()
        if conv:
            return conv
    # 匿名访客：查找 24 小时内最近的会话复用
    if visitor_id:
        from datetime import timedelta
        recent = await db.execute(
            select(Conversation)
            .where(Conversation.visitor_id == visitor_id)
            .where(Conversation.updated_at > datetime.now(CN_TZ) - timedelta(hours=24))
            .order_by(Conversation.updated_at.desc())
            .limit(1)
        )
        conv = recent.scalar_one_or_none()
        if conv:
            return conv
    conv = Conversation(title="新对话", user_id=user_id, visitor_id=visitor_id)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


async def _generate_title(query: str, answer: str) -> str:
    """用 LLM 生成简洁的对话标题（≤12字）"""
    prompt = f"""根据以下问答生成一个简洁的对话标题，不超过12个字，不要加引号或标点。

用户问题：{query[:100]}
AI回答：{answer[:200]}

标题："""
    try:
        title = await chat(prompt, [])
        title = title.strip().strip("\"'。，,：:").replace("\n", "")
        return title[:24] if title else query[:20]
    except Exception:
        return query[:20]


async def _describe_chat_image(image_b64: str, query: str) -> str:
    """用视觉模型描述用户上传的图片，返回文字描述"""
    try:
        from openai import AsyncOpenAI
        from config import LLM_BASE_URL

        client = AsyncOpenAI(base_url=LLM_BASE_URL, api_key="ollama")
        prompt = f"请详细描述这张图片的内容。用户的问题是：「{query}」，请侧重描述与问题相关的信息。"
        resp = await client.chat.completions.create(
            model="minicpm-v:8b",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                ],
            }],
            max_tokens=500,
        )
        desc = (resp.choices[0].message.content or "").strip()
        return desc if desc else ""
    except Exception:
        return ""


async def _load_history(db: AsyncSession, conversation_id: str) -> list[dict]:
    """加载最近 6 条历史消息（3 轮对话），排除当前正在生成的消息"""
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(desc(Message.created_at))
        .limit(7)  # 当前 user message 也在里面，多取一条排除
    )
    messages = result.scalars().all()
    # 反转回时间正序，跳过最新的那条（当前 user message）
    history = []
    for msg in reversed(messages):
        # 跳过空内容或当前这一轮
        if not msg.content.strip():
            continue
        role = "assistant" if msg.role == "agent" else "user"
        history.append({"role": role, "content": msg.content[:500]})
    # 去掉最后一条（当前 user message）
    if history and history[-1]["role"] == "user":
        history = history[:-1]
    return history


def _build_sources(chunks: list[dict]) -> list[dict]:
    result = []
    for i, chunk in enumerate(chunks):
        item = {
            "id": i + 1,
            "title": chunk.get("text", "")[:50] + ("…" if len(chunk.get("text", "")) > 50 else ""),
            "score": round(chunk.get("score", 0), 3),
            "excerpt": chunk.get("text", "")[:200],
        }
        if "rerank_score" in chunk:
            item["rerank_score"] = round(chunk["rerank_score"], 1)
        result.append(item)
    return result


def _build_trace(elapsed: float) -> list[dict]:
    now = _now()
    return [
        {"phase": "planning", "label": "问题分析", "detail": "接收用户查询，准备检索策略", "time": now},
        {"phase": "retrieval", "label": "知识库检索", "detail": f"向量检索完成（耗时 {elapsed:.2f}s）", "time": now},
        {"phase": "generation", "label": "生成回答", "detail": "基于检索到的文档片段，由 LLM 生成最终回答", "time": now},
    ]

def _count_tokens(chunks: list[dict]) -> int:
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        total = 0
        for c in chunks:
            total += len(enc.encode(c.get("text", "")))
        return total
    except Exception:
        return 0