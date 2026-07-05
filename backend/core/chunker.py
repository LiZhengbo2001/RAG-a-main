def chunk_text(text: str) -> list[str]:
    """按段落 + 句子边界分块，保证 chunk 在语义完整处截断"""
    chunks = []
    start = 0
    chunk_size = 512
    chunk_overlap = 64

    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunk = text[start:].strip()
            if chunk:
                chunks.append(chunk)
            break

        # 向回找最近的句子边界
        for sep in ["。", ".", "！", "？", "\n\n", "\n", "，", " "]:
            pos = text.rfind(sep, start + 256, end)
            if pos > 0:
                end = pos + 1
                break

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start = end - chunk_overlap if end - start >= chunk_overlap else end

    return chunks