from core.embedding import embed_single
from core.vectordb import search_vectors
from config import RETRIEVAL_TOP_K
from core.bm25 import bm25_index
from core.reranker import rerank
from core.query_rewriter import rewrite_query

RRF_K = 60


async def retrieve(query: str, rewritten: str | None = None) -> list[dict]:
    """双路召回：稠密向量 + BM25 → RRF 融合 → 去重 → 截断"""
    # 0. 查询改写
    search_text = rewritten if rewritten else query

    # 路 1：稠密向量
    query_vec = await embed_single(search_text)
    dense_hits = search_vectors(query_vec, top_k=RETRIEVAL_TOP_K * 2)

    # 路 2：BM25 关键词
    sparse_hits = bm25_index.search(search_text, top_k=RETRIEVAL_TOP_K * 2)

    # RRF 融合
    scores: dict[str, float] = {}    # key = f"{doc_id}_{chunk_index}"
    hits_map: dict[str, dict] = {}   # 保存原始 hit 信息

    for rank, hit in enumerate(dense_hits):
        key = f"{hit['doc_id']}_{hit['chunk_index']}"
        scores[key] = scores.get(key, 0) + 1.0 / (RRF_K + rank + 1)
        hits_map[key] = hit

    for rank, hit in enumerate(sparse_hits):
        key = f"{hit['doc_id']}_{hit['chunk_index']}"
        scores[key] = scores.get(key, 0) + 1.0 / (RRF_K + rank + 1)
        if key not in hits_map:
            hits_map[key] = hit

    # 按 RRF 总分降序
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    merged_hits = [hits_map[k] for k, _ in ranked]

    # 同一 doc_id 只保留 RRF 总分最高的 chunk
    best: dict[str, dict] = {}
    for h in merged_hits:
        did = h["doc_id"]
        key = f"{did}_{h['chunk_index']}"
        s = scores.get(key, 0)
        existing = best.get(did)
        existing_score = 0.0
        if existing:
            ek = f"{existing['doc_id']}_{existing['chunk_index']}"
            existing_score = scores.get(ek, 0)
        if existing is None or s > existing_score:
            best[did] = h

    sorted_hits = sorted(
        best.values(),
        key=lambda h: scores.get(f"{h['doc_id']}_{h['chunk_index']}", 0),
        reverse=True,
    )

    # 3. LLM 重排序（精排）
    sorted_hits = await rerank(query, sorted_hits, RETRIEVAL_TOP_K)
    if sorted_hits:
        best_rrf = scores.get(f"{sorted_hits[0]['doc_id']}_{sorted_hits[0]['chunk_index']}", 0)
        sorted_hits = [h for h in sorted_hits
                       if scores.get(f"{h['doc_id']}_{h['chunk_index']}", 0) >= best_rrf * 0.85]

    # 4. Lost in the Middle 规避：最相关的 chunk 放头部和尾部，次相关放中间
    n = len(sorted_hits)
    if n >= 3:
        n_head = max(1, n // 4)     # 前 25% → 放到 prompt 头部
        n_tail = max(1, n // 4)     # 后 25% → 放到 prompt 尾部

        head = sorted_hits[:n_head]
        tail = sorted_hits[-n_tail:]
        middle = sorted_hits[n_head:n - n_tail]

        # 尾部逆序：尾部最后一个（分数最低但也是最相关的之一）放 prompt 最后
        sorted_hits = head + middle + list(reversed(tail))

    return sorted_hits