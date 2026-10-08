"""新闻抓取模块：RSS（feedparser）+ Tavily 实时搜索（可选），统一输出标准化新闻 dict。"""

import asyncio
import datetime as dt
import glob
import html
import json
import logging
import os
import re
import urllib.parse

import feedparser
import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_TRUST_BY_SOURCE = {
    "36氪": 4, "少数派": 4, "联合早报": 4, "BBC": 4,
    "量子位": 3, "IT之家": 3, "钛媒体": 3, "雷锋网": 3,
    "cnBeta": 3, "澎湃": 4, "财新": 5, "新华社": 5,
    "财经频道": 4, "国际频道": 4, "中新网": 4, "人民网": 4,
}
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(raw: str) -> str:
    """去 HTML 标签、实体与多余空白。"""
    if not raw:
        return ""
    text = _TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _to_local(parsed) -> dt.datetime:
    if not parsed:
        return dt.datetime.now()
    try:
        return dt.datetime(*parsed[:6], tzinfo=dt.timezone.utc).astimezone().replace(tzinfo=None)
    except (TypeError, ValueError):
        return dt.datetime.now()


def _trust_level(source: str) -> int:
    for key, level in _TRUST_BY_SOURCE.items():
        if key in source:
            return level
    return 3


def _parse_feed(feed_url: str, timeout: int = 10) -> list[dict]:
    # feedparser.parse 无 timeout 参数，用全局 socket 超时控制连接/读取（串行抓取，安全）
    import socket
    old = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        parsed = feedparser.parse(feed_url)
    finally:
        socket.setdefaulttimeout(old)
    if parsed.bozo and not parsed.entries:
        return []
    source_name = getattr(parsed.feed, "title", feed_url) or feed_url
    items = []
    for entry in parsed.entries[:50]:
        title = clean_text(getattr(entry, "title", ""))
        link = getattr(entry, "link", "")
        if not title or not link:
            continue
        summary = clean_text(
            entry.get("summary") or (entry.get("content") or [{}])[0].get("value", "")
        )
        # 正文空壳直接丢弃（宁缺毋滥）：无正文的条目入库后点开无内容，用户明确不要
        if not summary:
            continue
        published = _to_local(getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None))
        now = dt.datetime.now()
        # 新鲜度闸门：RSS 条目发布日期超过 3 天 → 视为过时源/旧缓存，直接丢弃（新闻重时效）
        # 避免人民网等冻结源把 489 天前的旧条目包装成"最新新闻"入库、用户点开全是死链
        if published < now - dt.timedelta(days=3):
            continue
        # 仅修正未来日期 bug（RSS 时间戳错乱晚于现在 1 天以上 → 用抓取时间）
        if published > now + dt.timedelta(days=1):
            published = now
        items.append({
            "title": title,
            "content": summary[:2000],
            "url": link,
            "source": source_name,
            "published_at": published.isoformat(sep=" ", timespec="minutes"),
            "trust_level": _trust_level(source_name),
        })
    return items


async def fetch_rss(sources: list[str] | None = None) -> list[dict]:
    """抓取全部 RSS 源（异步并发，单源失败/超时不影响其他）。

    14 个源并发抓取，总耗时 ≈ 单个最慢源（约 20s），而非串行累加。
    """
    if sources is None:
        sources = settings.NEWS_SOURCES

    async def _fetch_one(url: str) -> list[dict]:
        try:
            # wait_for 兜底：feedparser 底层 socket 超时不可靠时强制整体超时
            return await asyncio.wait_for(
                asyncio.to_thread(_parse_feed, url, settings.NEWS_FETCH_TIMEOUT),
                timeout=settings.NEWS_FETCH_TIMEOUT + 10,
            )
        except Exception as e:
            print(f"  [rss] {url} 抓取失败: {e}")
            return []

    batches = await asyncio.gather(*[_fetch_one(u) for u in sources])
    results: list[dict] = []
    for items in batches:
        results.extend(items)
    # 注意：金十/每日简报为伪 URL（无原文链接），用户不要点不进去的新闻，已移除
    return results


async def fetch_jin10() -> list[dict]:
    """金十数据财经快讯：flash_newest.js（实时财经/市场快讯，伪 URL 去重）。"""
    import re as _re
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://www.jin10.com/flash_newest.js",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
            raw = resp.text
    except Exception as e:
        print(f"  [jin10] 拉取失败: {e}")
        return []
    m = _re.search(r"var\s+newest\s*=\s*(\[.*\])\s*;?\s*$", raw, _re.S)
    if not m:
        print("  [jin10] 格式不匹配")
        return []
    try:
        import json as _json
        items_raw = _json.loads(m.group(1))
    except Exception as e:
        print(f"  [jin10] JSON 解析失败: {e}")
        return []
    items = []
    import hashlib as _hashlib
    for it in items_raw[:50]:
        d = it.get("data") or {}
        title = clean_text(d.get("title") or "")
        content = clean_text(d.get("content") or "")
        if not content:
            continue
        # 金十中英双语重复：只保留中文版（content 含中文才入库）
        if not re.search(r"[\u4e00-\u9fff]", content):
            continue
        if not title:
            title = content[:20]
        fake_url = f"jin10://{_hashlib.md5(str(it.get('id') or title).encode('utf-8')).hexdigest()[:16]}"
        items.append({
            "title": title[:80],
            "content": content[:1000],
            "url": fake_url,
            "source": "金十数据",
            "published_at": it.get("time") or dt.datetime.now().isoformat(sep=" ", timespec="minutes"),
            "trust_level": 3,
        })
    print(f"  [jin10] 拉取 {len(items)} 条财经快讯")
    return items


async def fetch_tianapi_bulletin() -> list[dict]:
    """天行「每日简报」：全领域热点标题+短摘要（无原文链接，伪 URL 仅用于去重）。"""
    if not settings.TIANAPI_KEY:
        return []
    import hashlib
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://apis.tianapi.com/bulletin/index",
                params={"key": settings.TIANAPI_KEY},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        print(f"  [bulletin] 拉取失败: {e}")
        return []
    if data.get("code") != 200:
        print(f"  [bulletin] code={data.get('code')} msg={data.get('msg')}")
        return []
    items = []
    for r in (data.get("result") or {}).get("list", []):
        title = clean_text(r.get("title") or "")
        digest = clean_text(r.get("digest") or "")
        mtime = r.get("mtime") or ""
        if not title or not digest:
            continue
        fake_url = f"tianapi-bulletin://{hashlib.md5(title.encode('utf-8')).hexdigest()[:16]}"
        published = f"{mtime} 12:00" if mtime else dt.datetime.now().isoformat(sep=" ", timespec="minutes")
        items.append({
            "title": title,
            "content": digest[:500],
            "url": fake_url,
            "source": "每日简报",
            "published_at": published,
            "trust_level": 3,
        })
    print(f"  [bulletin] 拉取 {len(items)} 条热点")
    return items


async def tavily_search(query: str, max_results: int = 5) -> list[dict]:
    """Tavily 实时搜索（需 TAVILY_API_KEY；topic=news 且限定近 3 天）。"""
    if not settings.TAVILY_API_KEY:
        return []
    payload = {
        "api_key": settings.TAVILY_API_KEY,
        "query": query,
        "max_results": max_results,
        "topic": "news",
        "days": 3,
        "include_raw_content": False,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post("https://api.tavily.com/search", json=payload)
            resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  [tavily] 搜索失败: {e}")
        return []
    items = []
    for r in data.get("results", []):
        items.append({
            "title": r.get("title", ""),
            "content": r.get("content", "")[:2000],
            "url": r.get("url", ""),
            "source": r.get("source", "tavily"),
            "published_at": (r.get("published_date") or dt.datetime.now().isoformat(sep=" ", timespec="minutes")),
            "trust_level": 3,
        })
    return items


async def tianapi_news_search(query: str, num: int = 8) -> list[dict]:
    """天行综合新闻搜索（中文 query 专用，返回有真实链接的中文新闻）。"""
    if not settings.TIANAPI_KEY:
        return []
    # 天行关键词搜索是精确匹配，整句搜不到，截短成前 4-6 个字（取核心关键词）
    short_query = query.strip()[:6]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://apis.tianapi.com/generalnews/index",
                params={"key": settings.TIANAPI_KEY, "word": short_query, "num": num},
            )
            resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("天行综合新闻搜索失败: %s", e)
        return []
    if data.get("code") != 200:
        logger.warning("天行综合新闻搜索返回错误: %s", data.get("msg"))
        return []
    items = []
    for n in data.get("result", {}).get("newslist", []):
        items.append({
            "title": n.get("title", ""),
            "content": (n.get("description") or "")[:2000],
            "url": n.get("url", ""),
            "source": n.get("source", "天行综合新闻"),
            "published_at": n.get("ctime", ""),
            "trust_level": 4,
        })
    return items


def _live_keywords(query: str) -> list[str]:
    """从查询里提取检索关键词：中文连续段 + 字母数字混合单元（滤掉纯数字防误命中）。"""
    cn = re.findall(r"[\u4e00-\u9fff]{2,}", query)
    alnum = re.findall(r"(?<![0-9A-Za-z\u4e00-\u9fff])[A-Za-z0-9]+", query)
    alnum = [t for t in alnum if not t.isdigit()]
    return cn + alnum


def _hit_count(item: dict, keywords: list[str]) -> int:
    text = (item.get("title") or "") + (item.get("content") or "")
    return sum(1 for k in keywords if k and k in text)


async def fetch_live(query: str) -> list[dict]:
    """实时抓取：天行（中文）→ Tavily（英文备用）→ RSS（兜底）。

    - 天行综合新闻：中文 query 专用，返回有真实链接的中文新闻
    - Tavily：英文/技术新闻备用
    - RSS：最后兜底
    """
    # 1. Tavily 实时搜索（有结果就用）
    tavily_items = await tavily_search(query)
    if tavily_items:
        return tavily_items[:5]

    # 2. 天行综合新闻兜底
    tianapi_items = await tianapi_news_search(query, num=8)
    if tianapi_items:
        return tianapi_items[:5]

    return []


async def fetch_tech_hot(top_n: int = 10) -> list[dict]:
    """科技热榜：科技 RSS 源最新新闻，套用入库主题过滤关键词（AI/芯片等）后，
    归一化标题去重，按发布时间倒序取 top_n。

    返回 [{title, hotvalue:0, source, url, published_at}]，失败返回空。
    """
    from app.services.ingest_filter import matches
    items = await fetch_rss()
    seen: set[str] = set()
    result: list[dict] = []
    for it in sorted(items, key=lambda x: str(x.get("published_at") or ""), reverse=True):
        t = clean_text(it.get("title") or "")
        if not t:
            continue
        # 与入库同口径：命中主题过滤关键词才算"科技/AI 热点"
        if not matches(t, it.get("content") or ""):
            continue
        key = re.sub(r"[\W_]+", "", t).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "title": t[:80],
            "hotvalue": 0,
            "source": (it.get("source") or "unknown")[:30],
            "url": it.get("url") or "",
            "published_at": str(it.get("published_at") or "")[:16],
        })
        if len(result) >= top_n:
            break
    return result


async def fetch_toutiao_hot(top_n: int = 10) -> list[dict]:
    """今日头条热榜（天聚数行 TianAPI）：热搜词 + 热度值。
    返回 [{title, hotvalue, url(头条站内搜索落地), source, published_at}]，失败返回空。
    """
    if not settings.TIANAPI_KEY:
        return []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://apis.tianapi.com/toutiaohot/index",
                params={"key": settings.TIANAPI_KEY},
            )
            resp.raise_for_status()
            data = resp.json()
        if data.get("code") != 200:
            logger.warning("头条热榜 API 异常: code=%s msg=%s", data.get("code"), data.get("msg"))
            return []
        now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        items = []
        for it in (data.get("result") or {}).get("list") or []:
            word = (it.get("word") or "").strip()
            if not word:
                continue
            items.append({
                "title": word[:80],
                "hotvalue": int(it.get("hotindex") or 0),
                "url": "https://www.toutiao.com/search/?keyword=" + urllib.parse.quote(word),
                "source": "今日头条热榜",
                "published_at": now,
            })
            if len(items) >= top_n:
                break
        return items
    except Exception as e:
        logger.warning("头条热榜获取失败: %s", e)
        return []


def save_raw(items: list[dict], name: str | None = None) -> str:
    """把抓取结果落盘到 backend/data/news_raw/（供 offline_ingest 使用）。"""
    raw_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "data", "news_raw")
    os.makedirs(raw_dir, exist_ok=True)
    if name is None:
        name = dt.datetime.now().strftime("%Y%m%d_%H%M%S.json")
    path = os.path.join(raw_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    return path


def load_raw(pattern: str = "*.json") -> list[dict]:
    """读取 data/news_raw/ 下全部抓取结果。"""
    raw_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "data", "news_raw")
    items: list[dict] = []
    for path in sorted(glob.glob(os.path.join(raw_dir, pattern))):
        try:
            with open(path, "r", encoding="utf-8") as f:
                items.extend(json.load(f))
        except Exception:
            continue
    return items
