"""重建入库：清空 SQLite news 表 + 清空 Chroma collection → 重新离线导入全部数据。

适用：模型/元数据字段变更后（如新增 category），需要全量重建索引。
运行：cd backend && python scripts/reset_rebuild.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.models.news  # noqa: F401  确保 News 表注册到 Base.metadata
from app.config import settings
from app.core.vector_store import get_chroma_client
from app.models.database import Base, engine
from scripts.offline_ingest import load_json_dir


async def reset_and_rebuild():
    print("1/4 重建 SQLite 表结构（新列 category 生效）...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    print("2/4 清空 Chroma collection...")
    client = get_chroma_client()
    try:
        client.delete_collection(settings.CHROMA_COLLECTION)
        print("    已删除旧 collection")
    except Exception:
        print("    collection 不存在或已清空")

    print("3/4 加载数据...")
    base = os.path.join(os.path.dirname(__file__), "..")
    items = load_json_dir(os.path.join(base, "data", "news_sample"))
    items += load_json_dir(os.path.join(base, "data", "news_raw"))
    print(f"    共 {len(items)} 条待导入")

    print("4/4 重新入库（首次加载嵌入模型，请耐心等待）...")
    from app.services.ingestion import ingest_news_items
    stats = await ingest_news_items(items)
    print("\n入库统计:", stats)


if __name__ == "__main__":
    asyncio.run(reset_and_rebuild())
