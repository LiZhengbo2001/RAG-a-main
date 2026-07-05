"""
多跳查询 Agent — 将复杂问题拆解为多个子问题，分别检索后再综合回答

适用场景：
    - 对比类问题："Transformer 和 LSTM 在长序列任务上的表现对比"
    - 多步推理："RAG 系统的三个组件分别怎么优化"
    - 跨领域问题："电池技术和财务报表分析有什么相似的数据处理思路"

工作流：
    用户 "对比 A 和 B"
         │
         ├─ LLM 拆解 → sub1: "A 的核心特征", sub2: "B 的核心特征"
         │
         ├─ 并行检索 sub1 → 5 条 chunk
         ├─ 并行检索 sub2 → 5 条 chunk
         │
         ├─ 合并 + 去重 + reranker 精排 → top 8
         │
         └─ LLM 基于合并结果生成对比性回答


设计要点：
    - 拆解由 LLM 完成，不需要人工定义规则
    - 子问题并行检索，总延迟 ≈ max(单次检索延迟)，不累加
    - 与现有 reranker 和 retrieve 共享代码，不重复实现
"""

import json
import asyncio
from typing import AsyncIterator

from services.retriever import retrieve
from core.llm import chat, chat_stream
from core.logger import logger


# ─── 子问题拆解 ─────────────────────────────────────────────

_DECOMPOSE_PROMPT = """将以下复杂问题拆解为 2-3 个独立的子问题，每个子问题应能独立检索回答。

规则：
1. 每个子问题一行，不要编号
2. 子问题应为关键词短语（5-15 字），适合用于检索
3. 如果是对比类问题，每个对比对象拆一个子问题
4. 如果是步骤类问题，每个关键步骤拆一个子问题

原始问题：{query}
子问题："""


async def _decompose_query(query: str) -> list[str]:
    """LLM 将复杂问题拆解为子问题列表"""
    prompt = _DECOMPOSE_PROMPT.format(query=query)
    result = await chat(prompt, [])
    # 解析：每行一个子问题，去掉空行和编号前缀
    sub_queries = []
    for line in result.strip().split("\n"):
        line = line.strip().lstrip("0123456789.、- )")
        if line and len(line) >= 3:
            sub_queries.append(line[:100])  # 截断过长的
    return sub_queries[:3]  # 最多 3 个子问题


# ─── 合并去重 ───────────────────────────────────────────────

def _merge_results(results_list: list[list[dict]], top_k: int = 8) -> list[dict]:
    """
    合并多个子问题的检索结果，去重并保留分数最高的 chunk。

    去重逻辑：同 doc_id 只保留最高分 chunk。
    排序逻辑：按 score 降序，rerank_score 优先于 score。
    """
    best: dict[str, dict] = {}
    for results in results_list:
        for chunk in results:
            did = chunk["doc_id"]
            # 用 rerank_score 或 score 作为比较基准
            cur_score = chunk.get("rerank_score") or chunk.get("score", 0)
            existing = best.get(did)
            existing_score = 0.0
            if existing:
                existing_score = existing.get("rerank_score") or existing.get("score", 0)
            if existing is None or cur_score > existing_score:
                best[did] = chunk

    merged = list(best.values())
    merged.sort(
        key=lambda c: c.get("rerank_score") or c.get("score", 0),
        reverse=True,
    )
    return merged[:top_k]


# ─── 流式事件产出 ───────────────────────────────────────────

async def run_multi_hop(query: str) -> AsyncIterator[dict]:
    """
    多跳检索流式 pipeline。

    事件产出顺序：
        thinking(search)  → "拆解为 3 个子问题: ..."
        thinking(result)  → "子问题1 检索到 5 条, 子问题2 检索到 3 条..."
        thinking(generate)→ "基于 8 条合并结果生成回答"
        token × N         → Agent 逐 token 回答
        sources           → 合并后的来源列表
        trace             → 推理链路
        done              → 完成
    """

    # ── Step 1: 拆解子问题 ──
    yield {
        "event": "thinking",
        "data": json.dumps(
            {"type": "search", "text": f"多跳分析：拆解复杂问题「{query[:40]}...」"},
            ensure_ascii=False,
        ),
    }

    try:
        sub_queries = await _decompose_query(query)
    except Exception:
        sub_queries = [query]  # 拆解失败就用原 query 做单次检索

    yield {
        "event": "thinking",
        "data": json.dumps(
            {"type": "search", "text": f"拆解为 {len(sub_queries)} 个子问题: {', '.join(sub_queries)}"},
            ensure_ascii=False,
        ),
    }

    # ── Step 2: 并行检索所有子问题 ──
    async def _safe_retrieve(q: str):
        try:
            return await retrieve(q)
        except Exception:
            return []

    tasks = [_safe_retrieve(q) for q in sub_queries]
    all_results = await asyncio.gather(*tasks)

    for i, (q, results) in enumerate(zip(sub_queries, all_results)):
        yield {
            "event": "thinking",
            "data": json.dumps(
                {"type": "result", "text": f"子问题{i+1}「{q[:30]}」→ 检索到 {len(results)} 条"},
                ensure_ascii=False,
            ),
        }

    # ── Step 3: 合并去重 ──
    merged = _merge_results(all_results)

    yield {
        "event": "thinking",
        "data": json.dumps(
            {"type": "generate", "text": f"多跳合并：{len(sub_queries)} 个子问题共检索到 {len(merged)} 条不重复文档"},
            ensure_ascii=False,
        ),
    }

    # ── Step 4: 基于合并结果流式生成 ──
    full_answer = ""
    try:
        async for token in chat_stream(query, merged):
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
        return

    # ── Step 5: 元信息 ──
    sources = _build_sources_local(merged)
    trace = _build_trace_local(len(sub_queries))
    trace.insert(1, {
        "phase": "retrieval",
        "label": "多跳检索",
        "detail": f"拆解为 {len(sub_queries)} 个子问题，合并后 {len(merged)} 条文档",
        "time": "",
    })

    yield {"event": "sources", "data": json.dumps(sources, ensure_ascii=False)}
    yield {"event": "trace", "data": json.dumps(trace, ensure_ascii=False)}
    yield {"event": "done", "data": json.dumps({"conversation_id": ""})}


# ─── 复杂度判断 ─────────────────────────────────────────────

_COMPLEXITY_PROMPT = """判断以下问题是否为复杂问题（需要拆解为多个子问题）。

复杂问题的特征：
- 包含对比（"A和B的区别""对比""比较"）
- 包含列表（"有哪些""哪几个""几个方面"）
- 包含多步推理（"先...再...""如何...然后..."）

简单问题的特征：
- 单个定义或事实查询
- 可以直接用一个搜索查询回答

只回答一个词：复杂 或 简单

用户问题：{query}
类型："""


async def should_use_multi_hop(query: str) -> bool:
    """判断一个问题是否需要多跳检索"""
    if len(query) < 15:
        return False  # 短问题大概率不需要拆

    prompt = _COMPLEXITY_PROMPT.format(query=query)
    try:
        result = await chat(prompt, [])
        return "复杂" in result.strip()
    except Exception:
        return False


def _build_sources_local(chunks: list[dict]) -> list[dict]:
    """构建来源列表（独立实现，避免循环导入）"""
    result = []
    for i, chunk in enumerate(chunks):
        item = {
            "id": i + 1,
            "title": chunk.get("text", "")[:50]
            + ("…" if len(chunk.get("text", "")) > 50 else ""),
            "score": round(chunk.get("score", 0), 3),
            "excerpt": chunk.get("text", "")[:200],
        }
        if "rerank_score" in chunk:
            item["rerank_score"] = round(chunk["rerank_score"], 1)
        result.append(item)
    return result


def _build_trace_local(sub_count: int) -> list[dict]:
    """构建推理链路（独立实现，避免循环导入）"""
    import time
    now = time.strftime("%H:%M", time.localtime())
    return [
        {
            "phase": "planning",
            "label": "问题拆解",
            "detail": f"将复杂问题拆解为 {sub_count} 个子问题并行检索",
            "time": now,
        },
        {
            "phase": "retrieval",
            "label": "并行检索",
            "detail": f"{sub_count} 个子问题并行检索完成",
            "time": now,
        },
        {
            "phase": "generation",
            "label": "生成回答",
            "detail": "基于多跳合并结果，由 LLM 生成最终回答",
            "time": now,
        },
    ]