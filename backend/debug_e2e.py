import asyncio
from db import AsyncSessionLocal, init_db
from core.vectordb import init_collection, _get_client
from config import MILVUS_COLLECTION_NAME


async def test():
    await init_db()
    init_collection()

    # 1. 确保 collection 加载
    client = _get_client()
    client.load_collection(MILVUS_COLLECTION_NAME)
    state = client.get_load_state(MILVUS_COLLECTION_NAME)
    stats = client.get_collection_stats(MILVUS_COLLECTION_NAME)
    print(f"加载状态: {state['state']}, 向量数: {stats['row_count']}")

    # 2. 模拟 API 调用链
    from services.rag_pipeline import run_stream

    async with AsyncSessionLocal() as db:
        print("\n=== 开始流式对话 ===")
        try:
            async for event in run_stream(db, "什么是RAG？"):
                ev_type = event["event"]
                if ev_type == "thinking":
                    import json
                    data = json.loads(event["data"])
                    print(f"  [thinking] {data['text'][:60]}")
                elif ev_type == "token":
                    print(".", end="", flush=True)
                elif ev_type == "sources":
                    import json
                    data = json.loads(event["data"])
                    print(f"\n  [sources] {len(data)} 条")
                elif ev_type == "trace":
                    print(f"  [trace] ok")
                elif ev_type == "done":
                    print(f"\n  [done] 完成")
                elif ev_type == "error":
                    print(f"\n  [ERROR] {event['data']}")
        except Exception as e:
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test())