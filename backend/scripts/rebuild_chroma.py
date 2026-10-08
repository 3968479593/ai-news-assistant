"""只重建 Chroma（news_dense + chat_memory 全删重嵌），SQLite 新闻数据完全不动。

适用：Chroma 元数据索引损坏（"Nothing found on disk"）时修复检索。
运行：cd backend && py -3.11 -m scripts.rebuild_chroma
注意：运行前必须确保没有服务进程占用 Chroma 目录。
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


async def main():
    from sqlalchemy import select

    import app.models.news  # noqa: F401
    from app.config import settings
    from app.core.embedding import encode_dense_async
    from app.core.vector_store import add_to_chroma, get_chroma_client
    from app.models.database import AsyncSessionLocal
    from app.models.news import News
    from app.utils.chunker import semantic_chunk

    # 1) 清空所有 Chroma collection（重新创建干净段）
    client = get_chroma_client()
    for name in [settings.CHROMA_COLLECTION, "chat_memory"]:
        try:
            client.delete_collection(name)
            print(f"已删除 collection: {name}")
        except Exception as e:
            print(f"collection {name} 无需删除: {type(e).__name__}")

    # 2) 从 SQLite 读全部新闻 → 纯 Chroma 重嵌（不写 SQLite）
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(News))).scalars().all()
    print(f"SQLite 现有新闻 {len(rows)} 条，开始重嵌...")

    total_chunks = 0
    for r in rows:
        try:
            chunks = semantic_chunk(f"{r.title}\n{r.content}")
            if not chunks:
                continue
            embeddings = await encode_dense_async(chunks)
            ids = [f"{r.id}::{idx}" for idx in range(len(chunks))]
            metadatas = [
                {
                    "news_id": str(r.id),
                    "title": r.title,
                    "source": r.source,
                    "category": r.category,
                    "url": r.url,
                    "published_at": r.published_at.timestamp(),
                    "trust_level": r.trust_level,
                }
                for _ in chunks
            ]
            await add_to_chroma(ids, embeddings, metadatas, chunks, collection=settings.CHROMA_COLLECTION)
            total_chunks += len(chunks)
        except Exception as e:
            print(f"  重嵌失败 id={r.id} {r.title[:20]}: {type(e).__name__}: {str(e)[:80]}")

    print(f"\n重建完成: {len(rows)} 条新闻 → {total_chunks} 个分块")


if __name__ == "__main__":
    asyncio.run(main())
