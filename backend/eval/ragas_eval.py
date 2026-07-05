"""
RAG 管线评估脚本 —— 使用 LLM 作为裁判打分（替代 ragas，零额外依赖）

用法:
    python eval/ragas_eval.py

输出:
    四个指标的平均分 + 每条 QA 的明细 + 保存 eval_result.json
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.retriever import retrieve
from core.llm import chat

# ─── 加载测试数据 ────────────────────────────────────────────

TEST_QA_FILE = Path(__file__).parent / "test_qa.json"
data = json.loads(TEST_QA_FILE.read_text(encoding="utf-8"))
print(f"已加载 {len(data)} 条测试 QA")


# ─── LLM 裁判 prompt ─────────────────────────────────────────

async def llm_judge(prompt: str) -> float:
    """让 LLM 打分，返回 0-1 之间的浮点数"""
    reply = await chat(prompt, [])
    text = reply.strip()
    # 尝试直接转 float
    try:
        return max(0.0, min(1.0, float(text)))
    except ValueError:
        pass
    # 尝试找第一个像数字的 token
    for token in text.replace("\n", " ").split():
        token = token.rstrip("。，,;:：分)")
        try:
            v = float(token)
            if 0 <= v <= 1:
                return v
        except ValueError:
            continue
    return 0.0


async def score_faithfulness(answer: str, contexts: list[str]) -> float:
    """回答中有多大比例可以从上下文中找到依据"""
    if not contexts:
        return 0.0
    context_text = "\n\n".join(c[:600] for c in contexts[:3])
    prompt = f"""请判断以下 AI 回答的忠实度（faithfulness）。

AI 回答基于以下参考文档生成。请检查回答中每一条事实是否都能在参考文档中找到依据。

参考文档：
{context_text}

AI 回答：
{answer[:1000]}

打分标准：
1.0 = 全部陈述都能在文档中找到依据
0.7 = 大部分找到依据，少量不确定
0.5 = 一半有依据
0.3 = 大部分无依据
0.0 = 完全编造

请只输出一个 0 到 1 之间的小数："""
    return await llm_judge(prompt)


async def score_answer_relevancy(answer: str, question: str) -> float:
    """回答和问题的相关程度"""
    prompt = f"""请判断以下 AI 回答与用户问题的相关性。

用户问题：{question}

AI 回答：{answer[:1000]}

打分标准：
1.0 = 完全针对问题回答，无偏题
0.7 = 大部分相关，少量偏题
0.5 = 部分相关
0.3 = 大部分不相关
0.0 = 完全偏题或答非所问

请只输出一个 0 到 1 之间的小数："""
    return await llm_judge(prompt)


async def score_context_precision(question: str, contexts: list[str]) -> float:
    """检索到的文档中有多少真正对回答问题有帮助"""
    if not contexts:
        return 0.0
    context_list = "\n---\n".join(
        f"[{i+1}] {c[:300]}" for i, c in enumerate(contexts[:5])
    )
    prompt = f"""请判断检索到的文档片段的精准度（context precision）。

用户就是想问：{question}

以下是从知识库检索到的文档片段：
{context_list}

打分标准：
1.0 = 所有片段都高度相关且有用
0.7 = 大部分相关，少量无关
0.5 = 一半相关
0.3 = 大部分是噪音
0.0 = 全部不相关

请只输出一个 0 到 1 之间的小数："""
    return await llm_judge(prompt)


async def score_context_recall(ground_truth: str, contexts: list[str]) -> float:
    """标准答案中的信息有多少被检索到的文档覆盖"""
    if not contexts:
        return 0.0
    context_text = "\n\n".join(c[:600] for c in contexts[:5])
    prompt = f"""请判断检索到的文档覆盖了标准答案中多少信息。

标准答案（期望检索到的内容）：
{ground_truth[:600]}

实际检索到的文档：
{context_text}

打分标准：
1.0 = 完全覆盖，标准答案所需信息全部能查到
0.7 = 覆盖了大部分关键信息
0.5 = 覆盖了一半
0.3 = 只覆盖了少量
0.0 = 完全未覆盖

请只输出一个 0 到 1 之间的小数："""
    return await llm_judge(prompt)


# ─── 运行管线 ────────────────────────────────────────────────

async def run_one(qa: dict) -> dict:
    question = qa["question"]
    t0 = time.time()
    chunks = await retrieve(question)
    retrieval_time = time.time() - t0
    answer = await chat(question, chunks)
    return {
        "question": question,
        "answer": answer,
        "contexts": [c["text"][:600] for c in chunks],
        "ground_truth": qa["ground_truth"],
        "retrieval_time": round(retrieval_time, 3),
        "num_chunks": len(chunks),
    }


async def main():
    print("=" * 60)
    print("RAG 管线评估（LLM-as-Judge）")
    print("=" * 60)

    # 第一步：跑管线
    results = []
    for i, qa in enumerate(data):
        print(f"\n[{i+1}/{len(data)}] {qa['question'][:40]}...")
        try:
            r = await run_one(qa)
            results.append(r)
            print(f"  检索到 {r['num_chunks']} 个 chunk（{r['retrieval_time']}s）")
            print(f"  回答预览：{r['answer'][:80]}...")
        except Exception as e:
            print(f"  ❌ 失败：{e}")
            results.append({
                "question": qa["question"],
                "answer": f"ERROR: {e}",
                "contexts": [],
                "ground_truth": qa["ground_truth"],
                "retrieval_time": 0,
                "num_chunks": 0,
            })

    # 第二步：逐条打分
    print("\n" + "=" * 60)
    print("LLM 打分中（每条 4 个指标，共 {} 次调用）...".format(len(results) * 4))
    print("=" * 60)

    all_scores = []
    for i, r in enumerate(results):
        print(f"\n[{i+1}/{len(results)}] {r['question'][:40]}")
        try:
            fid = await score_faithfulness(r["answer"], r["contexts"])
            rel = await score_answer_relevancy(r["answer"], r["question"])
            prec = await score_context_precision(r["question"], r["contexts"])
            rec = await score_context_recall(r["ground_truth"], r["contexts"])
        except Exception as e:
            print(f"  打分失败：{e}")
            fid = rel = prec = rec = 0.0

        all_scores.append({
            "faithfulness": fid,
            "answer_relevancy": rel,
            "context_precision": prec,
            "context_recall": rec,
        })
        print(f"  忠实度={fid:.3f}  相关性={rel:.3f}  精度={prec:.3f}  召回={rec:.3f}")

    # ─── 汇总 ────────────────────────────────────────────

    print("\n" + "=" * 60)
    print("评  估  结  果")
    print("=" * 60)

    metrics = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    cnames  = ["忠实度", "相关性", "精度", "召回"]
    avg_scores = {}

    for metric, name in zip(metrics, cnames):
        values = [s[metric] for s in all_scores]
        avg = sum(values) / len(values) if values else 0.0
        avg_scores[metric] = round(avg, 3)
        print(f"  {name:6s} ({metric:20s})  {avg:.3f}  (n={len(values)})")

    # ─── 每条明细 ─────────────────────────────────────────

    print("\n" + "-" * 65)
    print(f"{'#':<3} {'问题（前30字）':<32} {'忠实度':<8} {'相关性':<8} {'精度':<8} {'召回':<8}")
    print("-" * 65)

    for i, r in enumerate(results):
        s = all_scores[i]
        q = r["question"][:30]
        print(f"{i+1:<3} {q:<32} {s['faithfulness']:<8.3f} {s['answer_relevancy']:<8.3f} {s['context_precision']:<8.3f} {s['context_recall']:<8.3f}")

    # ─── 保存 ────────────────────────────────────────────

    out = {
        "summary": avg_scores,
        "details": [
            {
                "question": r["question"],
                "answer": r["answer"][:300],
                **all_scores[i],
            }
            for i, r in enumerate(results)
        ],
    }
    out_path = Path(__file__).parent / "eval_result.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已保存至 {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
