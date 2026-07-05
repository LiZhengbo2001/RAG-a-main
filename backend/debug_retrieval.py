import asyncio
from core.embedding import embed_single
from core.vectordb import search_vectors, _get_client
from config import MILVUS_COLLECTION_NAME


async def step1_embedding():
    print("=== 1. 测试 Embedding ===")
    vec = await embed_single("什么是RAG")
    print(f"向量维度: {len(vec)}")
    print(f"前5个值: {vec[:5]}")
    return vec


def step2_load_collection():
    print("\n=== 2. 测试 Milvus 加载 ===")
    client = _get_client()
    try:
        client.load_collection(MILVUS_COLLECTION_NAME)
        state = client.get_load_state(MILVUS_COLLECTION_NAME)
        print(f"加载状态: {state}")
        stats = client.get_collection_stats(MILVUS_COLLECTION_NAME)
        print(f"向量总数: {stats['row_count']}")
    except Exception as e:
        print(f"加载失败: {e}")


def step3_search(vec):
    print("\n=== 3. 测试向量检索 ===")
    try:
        hits = search_vectors(vec, top_k=5)
        print(f"检索到 {len(hits)} 条")
        for h in hits:
            print(f"  score={h['score']:.3f}  text={h['text'][:80]}...")
    except Exception as e:
        print(f"检索失败: {e}")


def step4_raw_search():
    print("\n=== 4. 绕过 search_vectors 直接查 ===")
    import httpx
    client = _get_client()
    # 先随便用一个向量做查询
    try:
        results = client.query(
            collection_name=MILVUS_COLLECTION_NAME,
            filter="id > 0",
            output_fields=["doc_id", "chunk_index", "text"],
            limit=3,
        )
        print(f"直接查询到 {len(results)} 条记录")
        for r in results:
            print(f"  doc_id={r.get('doc_id')}  text={r.get('text', '')[:60]}...")
    except Exception as e:
        print(f"查询失败: {e}")


async def main():
    vec = await step1_embedding()
    step2_load_collection()
    step3_search(vec)
    step4_raw_search()


if __name__ == "__main__":
    asyncio.run(main())