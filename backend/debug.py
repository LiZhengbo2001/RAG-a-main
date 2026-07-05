import asyncio
from db import AsyncSessionLocal, init_db
from models.conversation import Document
from sqlalchemy import select
from core.vectordb import init_collection, _get_client
from config import MILVUS_COLLECTION_NAME
from services.retriever import retrieve


async def check_db():
    await init_db()
    async with AsyncSessionLocal() as s:
        docs = (await s.execute(select(Document))).scalars().all()
        for d in docs:
            print(f"{d.filename} | status={d.status} | chunks={d.chunk_count} | id={d.id}")


def check_milvus():
    client = _get_client()
    stats = client.get_collection_stats(MILVUS_COLLECTION_NAME)
    print(f"Milvus 向量总数: {stats['row_count']}")


async def check_retrieval():
    init_collection()
    chunks = await retrieve("测试查询")
    print(f"检索到 {len(chunks)} 条结果")
    for c in chunks:
        print(f"  score={c['score']:.3f}  text={c['text'][:60]}...")


async def main():
    print("=== 文档状态 ===")
    await check_db()
    print("\n=== Milvus ===")
    check_milvus()
    print("\n=== 检索测试 ===")
    await check_retrieval()


if __name__ == "__main__":
    asyncio.run(main())