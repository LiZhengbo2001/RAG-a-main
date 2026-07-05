"""交叉编码器重排序：使用 bge-reranker-v2-m3 替代 LLM 打分"""

from sentence_transformers import CrossEncoder

_model: CrossEncoder | None = None
_model_dir = "D:/models/models--BAAI--bge-reranker-v2-m3"


def _get_model() -> CrossEncoder:
    global _model
    if _model is None:
        _model = CrossEncoder(_model_dir)
    return _model


async def rerank(
    query: str,
    candidates: list[dict],
    top_k: int = 5,
) -> list[dict]:
    """用 bge-reranker-v2-m3 对候选做交叉编码精排"""
    if len(candidates) <= top_k:
        return candidates

    model = _get_model()
    pairs = [[query, doc["text"]] for doc in candidates]
    scores = model.predict(pairs, show_progress_bar=False)

    for i, doc in enumerate(candidates):
        doc["rerank_score"] = round(float(scores[i]), 1)

    candidates.sort(key=lambda h: h.get("rerank_score", 0), reverse=True)
    return candidates[:top_k]
