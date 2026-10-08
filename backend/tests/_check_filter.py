"""入库主题过滤验证：抓 RSS 后按当前关键词统计命中数（不写库）。"""

import asyncio


async def main():
    from app.core.news_fetcher import fetch_rss
    from app.services.ingest_filter import get_keywords, matches

    kws = get_keywords()
    print("当前关键词:", kws)
    items = await fetch_rss()
    hit = [i for i in items if matches(i.get("title", ""), i.get("content", ""))]
    print(f"原始 {len(items)} 条 → 命中 {len(hit)} 条")
    for i in hit[:6]:
        print("  🎯", i["title"][:50])


asyncio.run(main())
