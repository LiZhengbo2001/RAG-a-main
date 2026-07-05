"""
RAG 召回率 A/B 对比：纯稠密向量 vs 完整管线

用法:
    python eval/compare_recall.py
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.embedding import embed_single
from core.vectordb import search_vectors
from core.llm import chat
from services.retriever import retrieve
from config import RETRIEVAL_TOP_K

TEST_QA_FILE = Path(__file__).parent / "test_qa.json"
data = json.loads(TEST_QA_FILE.read_text(encoding="utf-8"))


# ===== 两套检索 =====

async def baseline(query: str) -> list[dict]:
    """基准：纯稠密向量，无 BM25，无 RRF，无 reranker，无查询改写"""
    vec = await embed_single(query)
    return search_vectors(vec, top_k=RETRIEVAL_TOP_K)


async def full_pipeline(query: str) -> list[dict]:
    """完整管线：BM25 + 稠密 + RRF + reranker + 查询改写"""
    return await retrieve(query)


# ===== 召回率裁判 =====

async def judge_recall(ground_truth: str, contexts: list[str]) -> float:
    if not contexts:
        return 0.0
    ctx = "\n---\n".join(c[:400] for c in contexts[:8])
    prompt = f"""标准答案：{ground_truth[:600]}

检索文档：\n{ctx}

检索到的文档覆盖了标准答案中多少信息？
1.0=全覆盖 0.7=大部分 0.5=一半 0.3=少量 0.0=未覆盖
只输出一个小数（如0.65）："""
    try:
        reply = await chat(prompt, [])
        return max(0.0, min(1.0, float(reply.strip())))
    except Exception:
        return 0.0


async def main():
    print("纯稠密向量 → 完整管线 召回率对比\n")

    baseline_total = 0.0
    full_total = 0.0
    comparisons: list[tuple[str, float, float, float]] = []

    for i, qa in enumerate(data):
        q = qa["question"]
        gt = qa.get("ground_truth", "")

        b_chunks = await baseline(q)
        f_chunks = await full_pipeline(q)

        b_recall = await judge_recall(gt, [c["text"][:400] for c in b_chunks]) if b_chunks else 0.0
        f_recall = await judge_recall(gt, [c["text"][:400] for c in f_chunks]) if f_chunks else 0.0

        baseline_total += b_recall
        full_total += f_recall
        comparisons.append((q[:30], b_recall, f_recall, f_recall - b_recall))
        print(f"[{i+1:2d}] {q[:35]:<37} {b_recall:.2f} → {f_recall:.2f}  {'+' if f_recall > b_recall else ''}{f_recall - b_recall:+.2f}")

    n = len(data)
    base_avg = baseline_total / n
    full_avg = full_total / n
    improvement = (full_avg - base_avg) / base_avg * 100 if base_avg > 0 else 0

    print(f"\n{'='*55}")
    print(f"基准（纯稠密向量） 平均召回率: {base_avg:.3f}")
    print(f"完整管线            平均召回率: {full_avg:.3f}")
    print(f"提升: {full_avg - base_avg:+.3f} ({improvement:.0f}%)")
    print(f"{'='*55}")

    # 各 QA 排序，找最受益的问题
    top3 = sorted(comparisons, key=lambda x: x[3], reverse=True)[:3]
    print(f"\n召回率提升最大的 3 个问题：")
    for q, b, f, d in top3:
        print(f"  +{d:.2f}  「{q}」")

    # 保存
    out_path = Path(__file__).parent / "recall_comparison.json"
    json.dump({
        "baseline_avg_recall": round(base_avg, 3),
        "full_pipeline_avg_recall": round(full_avg, 3),
        "improvement_pct": round(improvement, 1),
        "details": [{"question": q, "baseline": b, "full": f, "delta": round(d, 3)} for q, b, f, d in comparisons],
    }, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"结果已保存至 {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
