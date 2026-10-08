from typing import Optional


def sliding_window_chunk(
    text: str,
    chunk_size: int = 512,
    overlap: int = 100,
) -> list[str]:
    """滑动窗口切块（新闻正文兜底方案）。"""
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start += chunk_size - overlap
    return chunks


def semantic_chunk(
    text: str,
    max_chunk_size: int = 512,
    separators: Optional[list[str]] = None,
) -> list[str]:
    """语义切块：优先在自然分隔符处断句，防死循环；短尾并入上一块。"""
    if separators is None:
        separators = ["\n\n", "\n", "。", ".", "；", ";", " "]

    chunks = []
    current = ""

    for char in text:
        current += char
        if len(current) >= max_chunk_size:
            best_split = -1
            for sep in separators:
                pos = current.rfind(sep)
                if pos > best_split:
                    best_split = pos
            if best_split > max_chunk_size // 2:
                chunks.append(current[:best_split + 1].strip())
                current = current[best_split + 1:]
            else:
                chunks.append(current.strip())
                current = ""

    if current.strip():
        if chunks and len(current) < max_chunk_size // 4:
            chunks[-1] = chunks[-1] + current
        else:
            chunks.append(current.strip())

    return chunks
