import os
import uuid
import base64
import tempfile

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models.conversation import Document
from core.chunker import chunk_text
from core.embedding import embed
from core.vectordb import insert_vectors, delete_by_doc_id
from config import UPLOAD_DIR


# ─── 文本解析 ───────────────────────────────────────────────

def _sanitize_text(text: str) -> str:
    """移除非法代理对字符，防止 JSON/Milvus 序列化报错"""
    return text.encode("utf-8", errors="replace").decode("utf-8")


def parse_file(file_path: str) -> str:
    """根据文件扩展名解析为纯文本"""
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        result = _parse_pdf_unstructured(file_path)
    elif ext in (".docx", ".doc"):
        from docx import Document as DocxDoc
        doc = DocxDoc(file_path)
        result = "\n".join(p.text for p in doc.paragraphs)
    elif ext == ".md":
        with open(file_path, encoding="utf-8") as f:
            text = f.read()
        import markdown
        html = markdown.markdown(text)
        from html.parser import HTMLParser
        class Stripper(HTMLParser):
            def __init__(self):
                super().__init__()
                self.parts = []
            def handle_data(self, data):
                self.parts.append(data)
        s = Stripper()
        s.feed(html)
        result = "".join(s.parts)
    elif ext in (".txt", ".json", ".csv", ".html"):
        with open(file_path, encoding="utf-8", errors="replace") as f:
            result = f.read()
    else:
        raise ValueError(f"不支持的文件格式: {ext}")

    return _sanitize_text(result)


def _parse_pdf_unstructured(file_path: str) -> str:
    """用 Unstructured 解析 PDF：自动识别表格、标题、正文，保留结构"""
    try:
        from unstructured.partition.pdf import partition_pdf

        elements = partition_pdf(
            file_path,
            strategy="auto",           # auto: 先试 fast，复杂页面用 hi_res
            infer_table_structure=True,  # 识别表格行列
        )

        lines = []
        for el in elements:
            el_type = type(el).__name__

            # 表格 → 格式化输出
            if el_type == "Table":
                text = str(el)
                lines.append(f"[表格]\n{text}")
            # 标题 → 保留标记
            elif el_type == "Title":
                lines.append(f"## {el}")
            # 图片 → 标记位置
            elif el_type == "Image":
                lines.append("[图片]")
            # 正文
            else:
                text = str(el).strip()
                if text:
                    lines.append(text)

        result = "\n\n".join(lines)
        if result.strip():
            return result
    except ImportError:
        pass  # Unstructured 未安装 → fallback 到 pypdf

    # Fallback: pypdf 作为备选
    from pypdf import PdfReader
    reader = PdfReader(file_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


# ─── 图片提取与描述 ─────────────────────────────────────────

def _extract_images_from_pdf(file_path: str) -> list[dict]:
    """从 PDF 中提取嵌入图片，返回 [{index, data(base64), page}，...]"""
    try:
        from pdf2image import convert_from_path
        import io
        from PIL import Image

        images = convert_from_path(file_path, dpi=200)
        results = []
        for i, img in enumerate(images):
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            results.append({"index": i, "data": b64, "page": i + 1})
        return results
    except ImportError:
        # pdf2image 未安装 → 跳过图片提取
        return []
    except Exception:
        return []


async def _describe_images(
    images: list[dict],
    query_context: str = "",
) -> str:
    """用 Ollama 视觉模型 (minicpm-v) 描述图片内容"""
    if not images:
        return ""

    try:
        from openai import AsyncOpenAI
        from config import LLM_BASE_URL

        client = AsyncOpenAI(
            base_url=LLM_BASE_URL,
            api_key="ollama",
        )

        descriptions = []
        for img in images[:5]:  # 最多处理 5 张图片
            prompt = "请用一段中文描述这张图片的内容，包括图表中的数据趋势或图片中的关键信息。"
            if query_context:
                prompt = f"请描述这张图片的内容，重点关注与「{query_context}」相关的信息。"

            try:
                resp = await client.chat.completions.create(
                    model="minicpm-v:8b",
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{img['data']}"
                                },
                            },
                        ],
                    }],
                    max_tokens=300,
                )
                desc = resp.choices[0].message.content or ""
                if desc.strip():
                    descriptions.append(
                        f"[图片{img['page']}描述]\n{desc.strip()}"
                    )
            except Exception:
                # 图片描述失败不阻断整体流程
                pass

        return "\n\n".join(descriptions)
    except ImportError:
        return ""
    except Exception:
        return ""


# ─── 上传 + 索引 ────────────────────────────────────────────

async def process_and_index(
    db: AsyncSession, filename: str, content: bytes, user_id: str | None = None
) -> tuple[str, int]:
    """上传文件全流程：存盘 → 解析 → 提取图片 → 分块 → 向量化 → Milvus → 更新状态"""
    doc_id = str(uuid.uuid4())
    doc_dir = os.path.join(UPLOAD_DIR, doc_id)
    os.makedirs(doc_dir, exist_ok=True)
    file_path = os.path.join(doc_dir, filename)

    with open(file_path, "wb") as f:
        f.write(content)

    doc = Document(
        id=doc_id, filename=filename, size=len(content),
        status="processing", file_path=file_path, user_id=user_id,
    )
    db.add(doc)
    await db.commit()

    try:
        # 1. 文本解析
        text = parse_file(file_path)

        # 2. PDF 额外处理：提取并描述图片
        ext = os.path.splitext(filename)[1].lower()
        if ext == ".pdf":
            images = _extract_images_from_pdf(file_path)
            if images:
                img_descriptions = await _describe_images(images, text[:200])
                if img_descriptions:
                    # 图片描述作为额外的 chunk 前缀，帮助检索时命中
                    text = img_descriptions + "\n\n" + text

        # 3. 分块
        chunks = chunk_text(text)
        if not chunks:
            chunks = [text[:2000]] if text else ["（空文档）"]

        # 4. 向量化 + 入库
        vectors = await embed(chunks)
        insert_vectors(vectors, doc_id, chunks)

        # 5. 更新状态
        doc = (
            await db.execute(select(Document).where(Document.id == doc_id))
        ).scalar_one()
        doc.status = "ready"
        doc.chunk_count = len(chunks)
        await db.commit()
        return doc_id, len(chunks)

    except Exception:
        doc = (
            await db.execute(select(Document).where(Document.id == doc_id))
        ).scalar_one()
        doc.status = "error"
        await db.commit()
        raise


# ─── 删除 ───────────────────────────────────────────────────

async def delete_document(db: AsyncSession, doc_id: str):
    """删文档：文件 + 向量 + 数据库记录"""
    doc = (
        await db.execute(select(Document).where(Document.id == doc_id))
    ).scalar_one_or_none()
    if not doc:
        raise ValueError("文档不存在")

    doc_dir = os.path.dirname(doc.file_path)
    if os.path.exists(doc_dir):
        import shutil
        shutil.rmtree(doc_dir)

    try:
        delete_by_doc_id(doc_id)
    except Exception:
        pass

    await db.delete(doc)
    await db.commit()
