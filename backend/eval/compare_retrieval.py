"""
检索管线 A/B 对比脚本 —— 对比每个优化阶段的召回率与精度分

用法:
    python eval/compare_retrieval.py

输出:
    每个 QA 在各阶段的召回率 + 精度分 + 对比表格
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.retriever import retrieve
from core.llm import chat
from core.embedding import embed_single
from core.vectordb import search_vectors
from core.bm25 import bm25_index
from core.reranker import rerank
from core.query_rewriter import rewrite_query
from config import RETRIEVAL_TOP_K

TEST_QA_FILE = Path(__file__).parent / "test_qa.json"
data = json.loads(TEST_QA_FILE.read_text(encoding="utf-8"))

RRF_K = 60


# ===== 各阶段检索实现 =====

async def stage1_dense_only(query: str) -> list[dict]:
    """阶段 1: 纯稠密向量"""
    query_vec = await embed_single(query)
    return search_vectors(query_vec, top_k=RETRIEVAL_TOP_K)


async def stage2_dense_bm25(query: str) -> list[dict]:
    """阶段 2: 稠密向量 + BM25"""
    query_vec = await embed_single(query)
    dense = search_vectors(query_vec, top_k=RETRIEVAL_TOP_K)
    sparse = bm25_index.search(query, top_k=RETRIEVAL_TOP_K)

    seen: set[str] = set()
    merged: list[dict] = []
    for h in dense + sparse:
        if h["doc_id"] not in seen:
            seen.add(h["doc_id"])
            merged.append(h)
    return merged[:RETRIEVAL_TOP_K]


async def stage3_rrf(query: str) -> list[dict]:
    """阶段 3: + RRF 融合"""
    query_vec = await embed_single(query)
    dense = search_vectors(query_vec, top_k=RETRIEVAL_TOP_K * 2)
    sparse = bm25_index.search(query, top_k=RETRIEVAL_TOP_K * 2)

    scores: dict[str, float] = {}
    hits_map: dict[str, dict] = {}

    for rank, hit in enumerate(dense):
        k = f"{hit['doc_id']}_{hit['chunk_index']}"
        scores[k] = scores.get(k, 0) + 1.0 / (RRF_K + rank + 1)
        hits_map[k] = hit
    for rank, hit in enumerate(sparse):
        k = f"{hit['doc_id']}_{hit['chunk_index']}"
        scores[k] = scores.get(k, 0) + 1.0 / (RRF_K + rank + 1)
        if k not in hits_map:
            hits_map[k] = hit

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    merged = [hits_map[k] for k, _ in ranked]

    best: dict[str, dict] = {}
    for h in merged:
        if h["doc_id"] not in best:
            best[h["doc_id"]] = h
    return list(best.values())[:RETRIEVAL_TOP_K]


async def stage4_reranker(query: str) -> list[dict]:
    """阶段 4: + bge-reranker"""
    chunks = await stage3_rrf(query)
    if len(chunks) <= RETRIEVAL_TOP_K:
        return chunks
    return await rerank(query, chunks, RETRIEVAL_TOP_K)


async def stage5_rewrite(query: str) -> list[dict]:
    """阶段 5: + 查询改写（当前完整管线）"""
    rewritten = await rewrite_query(query)
    search_text = rewritten if rewritten != query else query
    return await retrieve(query, search_text)


# ===== LLM 裁判打分 =====

async def judge_recall(ground_truth: str, contexts: list[str]) -> float:
    """让 LLM 判断检索到的文档覆盖了多少标准答案信息（0-1 召回率）"""
    if not contexts:
        return 0.0

    context_text = "\n---\n".join(c[:400] for c in contexts[:8])
    prompt = f"""请判断检索到的文档片段覆盖了标准答案中多少信息（召回率，0-1）。

标准答案：{ground_truth[:600]}

检索到的文档：
{context_text}

1.0 = 完全覆盖，标准答案中所有关键信息都能查到
0.7 = 覆盖了大部分关键信息
0.5 = 覆盖了一半
0.3 = 只覆盖少量
0.0 = 完全未覆盖

请只输出一个 0 到 1 之间的小数："""
    return await _parse_score(prompt)


async def judge_precision(question: str, contexts: list[str]) -> float:
    """让 LLM 判断检索文档中有多少是真正相关的（0-1 精度）"""
    if not contexts:
        return 0.0

    context_lines = "\n---\n".join(
        f"[{i+1}] {c[:400]}" for i, c in enumerate(contexts[:8])
    )
    prompt = f"""请判断检索到的文档片段的精准度（0-1）。

用户问题是：{question}

检索到的文档：
{context_lines}

0.0 = 全部不相关
0.5 = 一半相关
1.0 = 全部高度相关

请只输出一个 0 到 1 之间的小数："""
    return await _parse_score(prompt)


async def _parse_score(prompt: str) -> float:
    try:
        reply = await chat(prompt, [])
        text = reply.strip()
        try:
            return max(0.0, min(1.0, float(text)))
        except ValueError:
            for t in text.split():
                t = t.rstrip("。，,;:：分)")
                try:
                    v = float(t)
                    if 0 <= v <= 1:
                        return v
                except ValueError:
                    continue
            return 0.0
    except Exception:
        return 0.0


# ===== 入口 =====

async def main():
    print("=" * 70)
    print("RAG 管线 A/B 对比评估")
    print(f"测试 QA: {len(data)} 条")
    print(f"RETRIEVAL_TOP_K: {RETRIEVAL_TOP_K}")
    print("=" * 70)

    stages = [
        ("1. 纯稠密向量", stage1_dense_only),
        ("2. + BM25 双路", stage2_dense_bm25),
        ("3. + RRF 融合", stage3_rrf),
        ("4. + bge-reranker", stage4_reranker),
        ("5. + 查询改写", stage5_rewrite),
    ]

    results: dict[str, dict] = {}

    for stage_name, stage_fn in stages:
        print(f"\n{'─' * 50}")
        print(f"正在评估: {stage_name}")
        hits = 0
        total_recall = 0.0
        total_precision = 0.0
        n_recall = 0
        n_precision = 0

        for i, qa in enumerate(data):
            question = qa["question"]
            ground_truth = qa.get("ground_truth", "")
            try:
                chunks = await stage_fn(question)
            except Exception:
                chunks = []

            count = len(chunks)
            hits += count
            end = ""

            if count > 0:
                contexts = [c.get("text", "")[:400] for c in chunks]
                if ground_truth:
                    recall = await judge_recall(ground_truth, contexts)
                    total_recall += recall
                    n_recall += 1
                    end += f"  召回={recall:.2f}"
                precision = await judge_precision(question, contexts)
                total_precision += precision
                n_precision += 1
                if end:
                    end += f"  精度={precision:.2f}"
                else:
                    end = f"  精度={precision:.2f}"

            print(f"  [{i+1:2d}/{len(data)}] {question[:28]:<30} → {count:2d} 条{end}")

        results[stage_name] = {
            "avg_hits": hits / len(data),
            "avg_recall": round(total_recall / n_recall, 3) if n_recall > 0 else 0.0,
            "avg_precision": round(total_precision / n_precision, 3) if n_precision > 0 else 0.0,
        }
        time.sleep(1)

    # ===== 汇总 =====
    print("\n\n" + "=" * 70)
    print("对  比  结  果")
    print("=" * 70)
    header = f"{'阶段':<24} {'平均命中':>8}  {'召回率':>8}  {'精度分':>8}  {'召回变化':>10}  {'精度变化':>10}"
    print(header)
    print("-" * 70)

    prev_recall: float | None = None
    prev_precision: float | None = None

    for stage_name, _ in stages:
        r = results[stage_name]
        d_recall = ""
        d_precision = ""
        if prev_recall is not None:
            d_recall = f"{r['avg_recall'] - prev_recall:+.3f}"
        if prev_precision is not None:
            d_precision = f"{r['avg_precision'] - prev_precision:+.3f}"

        print(
            f"{stage_name:<24} {r['avg_hits']:>8.1f}  {r['avg_recall']:>8.3f}  {r['avg_precision']:>8.3f}"
            f"  {d_recall:>10}  {d_precision:>10}"
        )
        prev_recall = r["avg_recall"]
        prev_precision = r["avg_precision"]

    # ===== 结论 =====
    base = results[stages[0][0]]
    final = results[stages[-1][0]]

    print("\n" + "-" * 70)
    print(f"纯稠密向量 → 当前完整管线")
    print(f"  召回率: {base['avg_recall']:.3f} → {final['avg_recall']:.3f} (提升 {final['avg_recall'] - base['avg_recall']:+.3f})")
    print(f"  精度分: {base['avg_precision']:.3f} → {final['avg_precision']:.3f} (提升 {final['avg_precision'] - base['avg_precision']:+.3f})")

    # 单阶段最大提升
    prev_key = stages[0][0]
    for stage_name, _ in stages[1:]:
        recall_gain = results[stage_name]["avg_recall"] - results[prev_key]["avg_recall"]
        precision_gain = results[stage_name]["avg_precision"] - results[prev_key]["avg_precision"]
        if recall_gain > 0.02 or precision_gain > 0.02:
            gain_desc = f"{stage_name} vs {prev_key}"
            if recall_gain >= precision_gain:
                print(f"  单阶段最大提升: {gain_desc} (召回: {recall_gain:+.3f})")
            else:
                print(f"  单阶段最大提升: {gain_desc} (精度: {precision_gain:+.3f})")
        prev_key = stage_name

    # 保存
    out = {
        "test_qa_count": len(data),
        "retrieval_top_k": RETRIEVAL_TOP_K,
        "results": {
            k: {
                "avg_hits": round(v["avg_hits"], 1),
                "avg_recall": v["avg_recall"],
                "avg_precision": v["avg_precision"],
            }
            for k, v in results.items()
        },
    }
    out_path = Path(__file__).parent / "compare_result.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已保存至 {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
