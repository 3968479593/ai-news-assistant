"""抓取 + 入库一条龙（手动触发，等价于调用 API /api/news/refresh）。

用法：
    cd backend && python scripts/refresh_news.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.news_fetcher import fetch_rss, save_raw
from app.services.ingestion import ingest_news_items


async def main():
    print("正在抓取 RSS 新闻源...")
    items = await fetch_rss()
    if not items:
        print("未抓到新闻，请检查网络与 .env 的 NEWS_SOURCES。")
        return
    path = save_raw(items)
    print(f"抓取 {len(items)} 条 → {path}")

    print("开始入库（双写 Chroma + SQLite）...")
    stats = await ingest_news_items(items)
    print("\n入库统计:", stats)


if __name__ == "__main__":
    asyncio.run(main())
