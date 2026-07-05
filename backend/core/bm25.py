"""BM25 关键词倒排索引 — 内存实现，零依赖（已依赖 jieba）"""

import math
import jieba


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b

        # 每篇文档（chunk）的元数据
        self.doc_ids: list[str] = []          # 对应 Milvus 的 doc_id (36 位 uuid)
        self.chunk_indices: list[int] = []     # 同一 doc 下的第几个 chunk
        self.docs: list[list[str]] = []        # 分词结果，每个元素是一个 token 列表
        self.doc_texts: list[str] = []         # 原文，返回给调用方

        self.N = 0
        self.avgdl = 0.0
        self.idf_cache: dict[str, float] = {}

    # ── 增 ──

    def add_document(self, doc_id: str, chunk_index: int, text: str):
        tokens = list(jieba.cut(text))
        tokens = [t.strip() for t in tokens if t.strip()]

        self.doc_ids.append(doc_id)
        self.chunk_indices.append(chunk_index)
        self.docs.append(tokens)
        self.doc_texts.append(text)

        self.N += 1
        self.avgdl = sum(len(d) for d in self.docs) / self.N
        self.idf_cache.clear()   # N 变了，所有 IDF 过期

    # ── 删 ──

    def remove_document(self, doc_id: str):
        # 倒序遍历避免索引偏移
        for i in range(len(self.doc_ids) - 1, -1, -1):
            if self.doc_ids[i] == doc_id:
                self.doc_ids.pop(i)
                self.chunk_indices.pop(i)
                self.docs.pop(i)
                self.doc_texts.pop(i)

        self.N = len(self.docs)
        if self.N > 0:
            self.avgdl = sum(len(d) for d in self.docs) / self.N
        else:
            self.avgdl = 0.0
        self.idf_cache.clear()

    # ── 查 ──

    def search(self, query: str, top_k: int = 10) -> list[dict]:
        if self.N == 0:
            return []

        query_tokens = list(jieba.cut(query))
        query_tokens = [t.strip() for t in query_tokens if t.strip()]
        if not query_tokens:
            return []

        scores: list[tuple[int, float]] = []
        for i in range(self.N):
            s = self._bm25_score(query_tokens, i)
            if s > 0:
                scores.append((i, s))

        scores.sort(key=lambda x: x[1], reverse=True)

        return [
            {
                "doc_id": self.doc_ids[idx],
                "chunk_index": self.chunk_indices[idx],
                "text": self.doc_texts[idx],
                "score": round(score, 4),
            }
            for idx, score in scores[:top_k]
        ]

    # ── BM25 公式 ──

    def _bm25_score(self, query_tokens: list[str], doc_index: int) -> float:
        doc_tokens = self.docs[doc_index]
        dl = len(doc_tokens)
        score = 0.0

        for token in query_tokens:
            tf = doc_tokens.count(token)
            if tf == 0:
                continue
            idf = self._idf(token)
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * (dl / self.avgdl))
            score += idf * numerator / denominator

        # 归一化：除以 query 长度，避免长 query 天然高分
        return score / len(query_tokens) if query_tokens else score

    def _idf(self, token: str) -> float:
        if token in self.idf_cache:
            return self.idf_cache[token]

        n = sum(1 for d in self.docs if token in d)
        idf = math.log((self.N - n + 0.5) / (n + 0.5) + 1)
        self.idf_cache[token] = idf
        return idf


# 全局单例，被 vectordb.py 和 retriever.py 引用
bm25_index = BM25Index()