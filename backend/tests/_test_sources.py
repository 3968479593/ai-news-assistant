"""批量测试候选 RSS 源可用性：能抓到几条、标题是否正常。只读不写入。"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

CANDIDATES = {
    "新浪体育": "http://rss.sina.com.cn/sports/sports.xml",
    "央视体育": "http://www.cctv.com/program/rss/02/03/index.xml",
    "人民体育": "http://www.people.com.cn/rss/sports.xml",
    "财新最新(RSSHub)": "https://rsshub.liumingye.cn/caixin/latest",
    "晚点LatePost": "https://supsub.net/feed/public/ff29ec00/rss",
    "深网腾讯新闻": "https://supsub.net/feed/public/1d09f394/rss",
    "三联生活周刊": "https://supsub.net/feed/public/759b41d1/rss",
    "央视新闻": "http://www.cctv.com/rss/01/index.xml",
}


async def main():
    from app.core.news_fetcher import _parse_feed

    for name, url in CANDIDATES.items():
        try:
            items = await asyncio.to_thread(_parse_feed, url, 10)
            if not items:
                print(f"[空]  {name}")
                continue
            sample = items[0]
            title = (sample.get("title") or "")[:40]
            print(f"[OK]  {name}: {len(items)} 条 | 示例: {title}")
        except Exception as e:
            print(f"[FAIL] {name}: {type(e).__name__} {str(e)[:60]}")


if __name__ == "__main__":
    asyncio.run(main())
