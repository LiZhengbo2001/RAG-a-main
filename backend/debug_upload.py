import asyncio
from db import AsyncSessionLocal, init_db
from core.vectordb import init_collection, _get_client
from config import MILVUS_COLLECTION_NAME


async def step1_collection_status():
    print("=== 1. Collection 状态 ===")
    client = _get_client()
    exists = client.has_collection(MILVUS_COLLECTION_NAME)
    print(f"存在: {exists}")
    if exists:
        stats = client.get_collection_stats(MILVUS_COLLECTION_NAME)
        print(f"向量总数: {stats['row_count']}")
        # 看 schema
        desc = client.describe_collection(MILVUS_COLLECTION_NAME)
        for f in desc.get("fields", []):
            print(f"  字段: {f['name']} 类型:{f.get('type', '?')}")
    else:
        print("Collection 不存在，手动调用 init...")
        init_collection()
        print("初始化完成")


async def step2_embedding_test():
    print("\n=== 2. Embedding 测试 ===")
    from core.embedding import embed
    vecs = await embed(["测试文本"])
    print(f"向量维度: {len(vecs[0])}")
    print(f"归一化后模长: {sum(v*v for v in vecs[0]):.4f} (应为 ≈1.0)")


async def step3_manual_insert():
    print("\n=== 3. 手动插入一条到 Milvus ===")
    from core.embedding import embed
    from core.vectordb import insert_vectors

    vecs = await embed(["这是一条手动测试的文本"])
    try:
        ids = insert_vectors(vecs, "test-doc-001", ["这是一条手动测试的文本"])
        print(f"插入成功，返回 IDs: {ids}")
    except Exception as e:
        print(f"插入失败: {e}")


async def step4_verify_count():
    print("\n=== 4. 插入后验证 ===")
    client = _get_client()
    stats = client.get_collection_stats(MILVUS_COLLECTION_NAME)
    print(f"当前向量总数: {stats['row_count']}")


async def step5_full_upload_pipeline():
    print("\n=== 5. 模拟 service 上传流程 ===")
    from services.document_service import process_and_index

    async with AsyncSessionLocal() as db:
        try:
            doc_id, chunk_count = await process_and_index(
                db,
                filename="test.txt",
                content="RAG（检索增强生成）是一种结合检索和生成的AI技术。\n它先检索相关文档，再基于文档生成答案。\n这种方法能有效减少大模型的幻觉问题。".encode("utf-8"),
            )
            print(f"上传成功: doc_id={doc_id}, chunks={chunk_count}")

            # 查状态
            from models.conversation import Document
            from sqlalchemy import select
            doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one()
            print(f"状态: {doc.status}, 分块数: {doc.chunk_count}")
        except Exception as e:
            import traceback
            print(f"上传失败: {e}")
            traceback.print_exc()


async def main():
    await init_db()
    await step1_collection_status()
    await step2_embedding_test()
    await step3_manual_insert()
    await step4_verify_count()
    await step5_full_upload_pipeline()

    client = _get_client()
    stats = client.get_collection_stats(MILVUS_COLLECTION_NAME)
    print(f"\n最终向量总数: {stats['row_count']}")


if __name__ == "__main__":
    asyncio.run(main())