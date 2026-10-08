"""抓取 RSS 新闻到 backend/data/news_raw/（只抓取，不入库；入库走 offline_ingest）。

用法：
    cd backend && python scripts/fetch_news.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.news_fetcher import fetch_rss, save_raw


async def main():
    print("正在抓取 RSS 新闻源（逐源容错）...")
    items = await fetch_rss()
    print(f"共抓取 {len(items)} 条。")

    if not items:
        print("未抓到任何新闻：请检查 .env 的 NEWS_SOURCES 与本机网络。")
        return

    path = save_raw(items)
    print(f"已保存: {path}\n前 5 条预览：")
    for i in items[:5]:
        print(f"  - [{i['source']}] {i['title']} ({i['published_at']})")


if __name__ == "__main__":
    asyncio.run(main())
