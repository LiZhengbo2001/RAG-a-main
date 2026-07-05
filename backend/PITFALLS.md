# RAG Agent 踩坑记录

## 环境变量类型（致命）

`config.py` 里 `os.getenv(...)` 返回的是 `str`，没加类型转换。

- `RETRIEVAL_TOP_K * 2` 变成了字符串拼接 `"1010"`，超出 Milvus 限制
- `MILVUS_VECTOR_DIMENSION` 是 `"1024"` 但 nomic-embed-text 输出 768 维，向量和 collection schema 维度不匹配
- `LLM_TEMPERATURE` 是 `"0.7"` 字符串传给 Ollama 报类型错误（见下方 Ollama 那节）

**解决**：所有数值型环境变量必须用 `int()` / `float()` 包：

```python
RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "10"))
MILVUS_VECTOR_DIMENSION = int(os.getenv("MILVUS_VECTOR_DIMENSION", "768"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "512"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "64"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))
```

## load_dotenv 读取了错误的 .env

没指定路径时 `load_dotenv()` 从工作目录往上搜，读到了 `RAG_OS` 根目录下的 `.env`，里面的变量覆盖了 backend 自己的值，导致 `RETRIEVAL_TOP_K` 被覆盖成异常值。

**解决**：

```python
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")
```

## langchain-text-splitters 的 marshmallow 版本冲突

`marshmallow 3.22+` 删掉了 `__version_info__` 属性，`langchain-text-splitters` 依赖它，import 时报错：

```
AttributeError: module 'marshmallow' has no attribute '__version_info__'
```

**解决**：去掉 langchain 依赖，手写分块函数。按句子边界（`。.！？\n`）在 512 字符处截断，保持 64 字符重叠。20 行代码，零依赖，效果一样。

## sentence-transformers 下载 huggingface 超时

`BAAI/bge-large-zh-v1.5` 需要从 huggingface 下载 1.3GB，国内大概率超时，反复 retry 后失败。

**解决**：改用 Ollama 的 `nomic-embed-text`（785MB，模型中转更快），用 `httpx` 直接调 Ollama 的 `/api/embeddings` 端点，不再依赖 sentence-transformers。从 `requirements.txt` 删掉 `sentence-transformers`。

## nomic-embed-text 向量未归一化

Ollama 的 `nomic-embed-text` 输出的 embedding **没有 L2 归一化**，直接使用会导致 Milvus 的 `IP`（内积）度量无法正确计算余弦相似度。虽然检索能返回结果，但排序完全不对，LLM 拿不到相关文档，看起来就像没检索。

**解决**：在 embedding 层手动 L2 归一化：

```python
def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]
```

## pymilvus 版本 API 兼容问题

**create_index 参数格式变化**：pymilvus 2.4+ 不能直接传 dict，必须用 `prepare_index_params()` 构建，否则报：

```
AttributeError: 'str' object has no attribute 'pop'
```

正确写法：

```python
index_params = client.prepare_index_params()
index_params.add_index(
    field_name="vector",
    index_type="IVF_FLAT",
    metric_type="IP",
    params={"nlist": 128},
)
client.create_index(collection_name=..., index_params=index_params)
```

**insert 后数据不可见**：部分版本 `insert` 后数据不会被自动加载到内存，需要 release 再 load：

```python
result = client.insert(...)
client.release_collection(MILVUS_COLLECTION_NAME)
client.load_collection(MILVUS_COLLECTION_NAME)
```

**get_collection_stats row_count 不准**：这个 API 返回值不可靠，以实际检索命中数为准。

**search limit 上限**：`limit` 参数有上限（取决于 Milvus 版本），建议加保护：

```python
limit=min(top_k, 100)
```

## Ollama 的 temperature 类型校验

Ollama 对 JSON 字段类型校验比 OpenAI 严格。`temperature` 以字符串 `"0.7"` 传入时报：

```
cannot unmarshal string into Go struct field ChatCompletionRequest.temperature of type float64
```

**解决**：确保 `config.py` 里 `LLM_TEMPERATURE = float(os.getenv(...))` 是 float，或者直接在调用时硬编码 `temperature=0.3`。

## Ollama embedding API 字段名

Ollama 的 `/api/embeddings` 请求体字段名是 `prompt` 而不是 `input`：

```python
resp = await client.post(
    "http://localhost:11434/api/embeddings",
    json={"model": "nomic-embed-text", "prompt": t},  # 注意：是 prompt
)
```

## asyncio.run() 不能在事件循环中调用

FastAPI 本身就运行在 asyncio 事件循环里，embedding 函数如果用 `asyncio.run()` 包裹会报：

```
asyncio.run() cannot be called from a running event loop
```

**解决**：embdding、retriever、document_service 全部改为 `async def`，调用方用 `await`。不做同步包装。

## agent_msg.created_at 在 commit 前是 None

`rag_pipeline.py` 里 `agent_msg.created_at` 在 commit 之前是 None，赋给 `conv.updated_at` 触发：

```
sqlite3.IntegrityError: NOT NULL constraint failed: conversation.updated_at
```

**解决**：用独立时间戳赋值：

```python
from datetime import datetime, timezone
conv.updated_at = datetime.now(timezone.utc)
await db.commit()
```

## Milvus collection 索引缺失导致 load 失败

旧版 `init_collection` 逻辑只检测 collection 是否存在，不检测索引。如果 collection 在之前创建但没有索引，`load_collection` 时报：

```
MilvusException: (code=700, message=index not found)
```

**解决**：collection 和索引两项独立检测，缺啥补啥。
