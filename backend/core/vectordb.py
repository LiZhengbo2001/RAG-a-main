from pymilvus import MilvusClient, DataType, FieldSchema, CollectionSchema
from config import MILVUS_SERVER, MILVUS_COLLECTION_NAME, MILVUS_VECTOR_DIMENSION
from core.bm25 import bm25_index

_client: MilvusClient | None = None


def _get_client() -> MilvusClient :
    global _client
    if _client is None:
        _client = MilvusClient(uri=f"{MILVUS_SERVER}")
    return _client


def init_collection():
    """启动时调用：集合不存在则创建，索引不存在则补建"""
    client = _get_client()

    if not client.has_collection(MILVUS_COLLECTION_NAME):
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=MILVUS_VECTOR_DIMENSION),
            FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=36),
            FieldSchema(name="chunk_index", dtype=DataType.INT64),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=4096),
        ]
        schema = CollectionSchema(fields, description="RAG document chunks")
        client.create_collection(
            collection_name=MILVUS_COLLECTION_NAME,
            schema=schema,
        )

    # 检查索引是否存在，没有则创建
    try:
        indexes = client.list_indexes(MILVUS_COLLECTION_NAME)
    except Exception:
        indexes = []

    if not indexes:
        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="HNSW",
            metric_type="IP",
            params={
                "M": 16,
                "efConstruction": 200,
            })
        client.create_index(
            collection_name=MILVUS_COLLECTION_NAME ,
            index_params=index_params,
        )
        client.load_collection(MILVUS_COLLECTION_NAME, load_params={"ef": 64})
        try:
            existing = client.query(
                collection_name=MILVUS_COLLECTION_NAME,
                filter="id > 0",
                output_fields=["doc_id", "chunk_index", "text"],
                limit=10000,
            )
            for row in existing:
                bm25_index.add_document(
                    row["doc_id"], row["chunk_index"], row["text"]
                )
        except Exception:
            pass  # Milvus 不可用或 collection 为空，跳过

def insert_vectors(
    vectors: list[list[float]],
    doc_id: str,
    texts: list[str],
) -> list[int]:
    client = _get_client()
    data = [
        {
            "vector": vec,
            "doc_id": doc_id,
            "chunk_index": i,
            "text": texts[i],
        }
        for i, vec in enumerate(vectors)
    ]
    result = client.insert(collection_name=MILVUS_COLLECTION_NAME, data=data)
    client.release_collection(MILVUS_COLLECTION_NAME)
    client.load_collection(MILVUS_COLLECTION_NAME)
    for i, text in enumerate(texts):
        bm25_index.add_document(doc_id, i, text)
    return result["ids"]


def search_vectors(query_vec: list[float], top_k: int = 10) -> list[dict]:
    """向量检索，返回 [{doc_id, chunk_index, text, score}, ...]"""
    client = _get_client()
    client.load_collection(MILVUS_COLLECTION_NAME)

    results = client.search(
        collection_name=MILVUS_COLLECTION_NAME,
        data=[query_vec],
        limit=min(top_k, 100),
        output_fields=["doc_id", "chunk_index", "text"],
    )
    if not results or not results[0]:
        return []

    return [
        {
            "doc_id": hit["entity"]["doc_id"],
            "chunk_index": hit["entity"]["chunk_index"],
            "text": hit["entity"]["text"],
            "score": hit["distance"],
        }
        for hit in results[0]
    ]


def delete_by_doc_id(doc_id: str):
    """按 doc_id 删除该文档的所有向量"""
    client = _get_client()
    client.delete(
        collection_name=MILVUS_COLLECTION_NAME,
        filter=f'doc_id == "{doc_id}"',
    )
    bm25_index.remove_document(doc_id)