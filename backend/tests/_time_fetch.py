"""独立定位：fetch_rss 并发抓取实际耗时 / 是否卡死。不碰 Chroma。"""
import asyncio
import time

from app.core.news_fetcher import fetch_rss


async def main():
    t0 = time.time()
    try:
        items = await asyncio.wait_for(fetch_rss(), timeout=120)
        print(f"[ok] fetch_rss returned in {time.time() - t0:.1f}s, items={len(items)}")
    except asyncio.TimeoutError:
        print(f"[timeout] fetch_rss did not finish in 120s")
    except Exception as e:
        print(f"[err] {type(e).__name__}: {e} after {time.time() - t0:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
