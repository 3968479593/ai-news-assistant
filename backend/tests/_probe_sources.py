"""探测科技/AI 领域候选 RSS 源的可用性与条数（不写库）。"""

import asyncio


async def main():
    from app.core.news_fetcher import _parse_feed

    candidates = {
        "机器之心": "https://www.jiqizhixin.com/rss",
        "量子位": "https://www.qbitai.com/feed",
        "IT之家": "https://www.ithome.com/rss/",
        "cnBeta": "https://www.cnbeta.com.tw/backend.php",
        "虎嗅": "https://www.huxiu.com/rss/0.xml",
        "钛媒体": "https://www.tmtpost.com/rss",
        "雷锋网": "https://www.leiphone.com/feed",
    }
    for name, url in candidates.items():
        try:
            items = await asyncio.wait_for(asyncio.to_thread(_parse_feed, url, 8), timeout=18)
            print(f"✅ {name}: {len(items)} 条 | 示例: {items[0]['title'][:34] if items else '-'}")
        except Exception as e:
            print(f"❌ {name}: {type(e).__name__}: {str(e)[:60]}")


asyncio.run(main())
