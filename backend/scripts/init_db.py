"""初始化 SQLite 数据库表结构（首次运行前执行）。

用法：
    cd backend && python scripts/init_db.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.database import Base, engine
import app.models.news  # noqa: F401  确保 News 表注册到 Base.metadata


async def init():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("数据库表结构创建完成（backend/data/news.db）")


if __name__ == "__main__":
    asyncio.run(init())
