"""打印各可用源的 feed.title（source 名称），用于配置分类映射。"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

URLS = {
    "央视体育": "http://www.cctv.com/program/rss/02/03/index.xml",
    "人民体育": "http://www.people.com.cn/rss/sports.xml",
    "财新最新": "https://rsshub.liumingye.cn/caixin/latest",
    "晚点LatePost": "https://supsub.net/feed/public/ff29ec00/rss",
    "深网腾讯新闻": "https://supsub.net/feed/public/1d09f394/rss",
    "三联生活周刊": "https://supsub.net/feed/public/759b41d1/rss",
}


async def main():
    import feedparser

    for name, url in URLS.items():
        try:
            p = await asyncio.to_thread(feedparser.parse, url)
            title = getattr(p.feed, "title", "")
            print(f"{name} -> feed.title = {title!r} | 条数={len(p.entries)}")
        except Exception as e:
            print(f"{name} -> FAIL {e}")


if __name__ == "__main__":
    asyncio.run(main())
