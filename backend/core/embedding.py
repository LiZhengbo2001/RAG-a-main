"""Embedding 模型封装：通过 Ollama API 调用"""

import httpx
import math

EMBED_MODEL = "shaw/dmeta-embedding-zh:latest"
OLLAMA_BASE = "http://localhost:11434"
EMBED_URL = f"{OLLAMA_BASE}/api/embeddings"

def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]

async def embed(texts: list[str]) -> list[list[float]]:
    vectors = []
    async with httpx.AsyncClient(timeout=30) as client:
        for t in texts:
            # 清理非法代理对字符（PDF 中常出现，会导致 JSON 序列化失败）
            clean = t.encode("utf-8", errors="replace").decode("utf-8")
            resp = await client.post(
                EMBED_URL,
                json={"model": EMBED_MODEL, "prompt": clean},
            )
            resp.raise_for_status()
            vec = resp.json()["embedding"]
            vectors.append(_normalize(vec))
    return vectors


async def embed_single(text: str) -> list[float]:
    vecs = await embed([text])
    return vecs[0]