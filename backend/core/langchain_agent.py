"""
联网搜索 Agent — 当知识库检索无结果时，自动切换 DuckDuckGo 联网搜索

架构：
    用户 query
         │
         ├─ 1. 先走现有知识库检索 retrieve(query)
         │      ├─ 有结果（RRF 分 ≥ 阈值）→ 走现有 LLM 生成
         │      └─ 无结果 or 分数过低 → 触发联网搜索
         │
         ├─ 2. DuckDuckGo.search(query) → 获取前 5 条网页摘要
         │
         └─ 3. LLM 基于搜索结果生成回答（标注来源 URL）


设计要点：
    - 不替换现有 pipeline，作为 fallback 增强器
    - 与现有 SSE 事件格式兼容
    - 零额外 API Key（DuckDuckGo 免费）
"""

import json
import asyncio
from typing import AsyncIterator
from langchain_openai import ChatOpenAI

from langchain_ollama import ChatOllama
from langchain_core.tools import tool, StructuredTool
from langgraph.prebuilt import create_react_agent

from config import LLM_BASE_URL, LLM_AGENT_MODEL_NAME, LLM_API_KEY


# ─── 工具定义 ───────────────────────────────────────────────

# ── 本地知识库检索（异步 Tool，避免 asyncio.run 冲突）──

async def _search_knowledge_base_impl(query: str) -> str:
    """异步检索本地知识库"""
    from services.retriever import retrieve as async_retrieve

    try:
        chunks = await async_retrieve(query)
    except Exception:
        return "知识库检索出错"

    if not chunks:
        return "知识库中未找到相关信息"

    lines = []
    for i, c in enumerate(chunks):
        score = c.get("rerank_score") or c.get("score", 0)
        lines.append(f"[{i+1}] (相关度:{score}) {c['text'][:300]}")
    return "\n\n".join(lines)


search_knowledge_base = StructuredTool.from_function(
    coroutine=_search_knowledge_base_impl,
    name="search_knowledge_base",
    description=(
        "在本地知识库中检索文档。当你需要查找用户上传的文档中的信息时使用此工具。"
        "输入应为精简的关键词或短语，不要传完整句子。"
    ),
)


# ── 联网搜索（同步 Tool，LangGraph 自动放到线程池，不阻塞事件循环）──

@tool
def search_web(query: str) -> str:
    """
    在互联网上搜索最新信息。当你需要查找实时新闻、最新数据、
    或知识库中没有覆盖的话题时使用此工具。
    输入应为精简的搜索关键词。
    """
    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        if not results:
            return "未找到搜索结果"

        lines = []
        for i, r in enumerate(results):
            title = r.get("title", "无标题")
            snippet = r.get("body", "")[:200]
            link = r.get("href", "")
            lines.append(f"[{i+1}] {title}\n   摘要: {snippet}\n   来源: {link}")
        return "\n\n".join(lines)
    except Exception as e:
        return f"联网搜索失败: {str(e)}"


# ─── Agent 创建（缓存全局单例） ───────────────────────────────

_agent_cache = None


def _build_agent():
    """
    创建 ReAct Agent，配备两个工具：
    1. search_knowledge_base — 检索本地知识库
    2. search_web            — 联网搜索

    Agent 会自动判断先用哪个、要不要换一个再搜、搜完能不能回答。
    """
    global _agent_cache
    if _agent_cache is not None:
        return _agent_cache

    # langchain-ollama 的 ChatOllama: base_url 是 Ollama 地址，不需要 /v1 后缀
    llm = ChatOpenAI(
        model=LLM_AGENT_MODEL_NAME,
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        temperature=0.3,
    )

    system_prompt = """你是一个 RAG Agent 智能助手，配备两个工具：

1. search_knowledge_base — 检索用户上传的本地文档（技术手册、法律条文、病历指南等）
2. search_web — 联网搜索最新信息（新闻、实时数据、本地文档未覆盖的话题）

工作流程：
- 优先使用 search_knowledge_base 检索本地知识库
- 如果本地知识库无结果或信息不充分，自动切换到 search_web
- 如果问题需要多角度信息（例如对比两个概念），可以分别检索后再综合回答
- 回答时引用信息来源编号，如 [1][2]
- 用中文回答，结构清晰"""

    _agent_cache = create_react_agent(
        model=llm,
        tools=[search_knowledge_base, search_web],
        system_prompt=system_prompt,
    )
    return _agent_cache


# ─── 流式事件产出 ───────────────────────────────────────────

async def run_agent_stream(query: str) -> AsyncIterator[dict]:
    """
    以 SSE 兼容的事件格式流式产出 Agent 的推理过程。

    事件类型：
        thinking — Agent 的每一步推理/工具调用
        token    — 最终答案的逐 token 文本
        sources  — 引用的来源列表
        trace    — 完整推理链路
        done     — 完成标记
        error    — 错误信息
    """

    agent = _build_agent()
    full_answer = ""
    trace_steps: list[dict] = []

    try:
        async for event in agent.astream_events(
            {"messages": [("user", query)]},
            version="v2",
        ):
            kind = event.get("event", "")

            # ── LLM token 流 ──
            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                content = getattr(chunk, "content", "")
                if isinstance(content, str) and content:
                    full_answer += content
                    yield {
                        "event": "token",
                        "data": json.dumps({"text": content}, ensure_ascii=False),
                    }

            # ── 工具调用开始 ──
            if kind == "on_tool_start":
                tool_name = event.get("name", "unknown")
                tool_input = event["data"].get("input", "")
                msg = f"Agent 调用工具: {tool_name}"
                yield {
                    "event": "thinking",
                    "data": json.dumps(
                        {"type": "search", "text": msg}, ensure_ascii=False
                    ),
                }
                trace_steps.append({
                    "phase": "retrieval",
                    "label": f"调用 {tool_name}",
                    "detail": str(tool_input)[:200],
                    "time": "",
                })

            # ── 工具调用完成 ──
            if kind == "on_tool_end":
                tool_output = event["data"].get("output", "")
                result_len = len(str(tool_output))
                msg = f"工具返回 {result_len} 字符结果"
                yield {
                    "event": "thinking",
                    "data": json.dumps(
                        {"type": "result", "text": msg}, ensure_ascii=False
                    ),
                }

        # ── 发送元信息 ──
        sources = _extract_sources(full_answer)
        yield {
            "event": "sources",
            "data": json.dumps(sources, ensure_ascii=False),
        }
        yield {
            "event": "trace",
            "data": json.dumps(trace_steps, ensure_ascii=False),
        }
        yield {
            "event": "done",
            "data": json.dumps({"conversation_id": ""}),
        }

    except Exception as e:
        yield {
            "event": "error",
            "data": json.dumps({"message": f"Agent 执行出错: {str(e)}"}),
        }


def _extract_sources(text: str) -> list[dict]:
    """从 Agent 回答中提取引用来源（URL 或编号）"""
    import re

    sources: list[dict] = []
    urls = re.findall(r"来源:\s*(https?://[^\s\n]+)", text)
    for i, url in enumerate(urls):
        sources.append({
            "id": i + 1,
            "title": url[:50] + "…" if len(url) > 50 else url,
            "score": 0.5,
            "excerpt": url,
        })
    return sources
