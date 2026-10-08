"""📰 新闻管理接口：列表（来源/模块筛选）/ 实时热点 / 手动刷新 / 刷新状态 / 统计。"""

import time

from fastapi import APIRouter
from sqlalchemy import func, select

from app.core.categorizer import is_valid_category
from app.models.database import AsyncSessionLocal
from app.models.news import News
from app.models.schemas import NewsOut
from app.services.news_update import news_update_service

router = APIRouter()

# 实时热点缓存（按榜单类型分开缓存，RSS/头条抓取较慢，10 分钟内复用）
_hot_cache: dict[str, dict] = {}
HOT_CACHE_SECONDS: int = 600


@router.get("/hot")
async def hot_news(type: str = "general"):
    """实时热点榜（抖音式多榜）：
    - general：今日头条热榜（热搜词+热度），失败时 RSS 兜底，再兜底库内最新
    - tech：科技 RSS 源最新新闻（归一化去重 + 时间倒序），失败时兜底库内科技新闻
    - finance / intl：库内该模块最新 10 条（与库同步、毫秒级，不依赖网络）
    """
    cache = _hot_cache.get(type)
    if cache and cache["items"] and time.time() - cache["ts"] < HOT_CACHE_SECONDS:
        return cache["items"]

    from app.core.news_fetcher import fetch_rss, fetch_tech_hot, fetch_toutiao_hot

    if type == "tech":
        hot = await fetch_tech_hot(10)
        # 库内兜底：RSS 全失败时用库内最新科技新闻
        if not hot:
            async with AsyncSessionLocal() as db:
                rows = (await db.execute(
                    select(News)
                    .where(News.category == "科技")
                    .order_by(News.published_at.desc())
                    .limit(10)
                )).scalars().all()
            hot = [
                {
                    "title": r.title[:80],
                    "hotvalue": 0,
                    "source": r.source[:30],
                    "url": r.url,
                    "published_at": r.published_at.strftime("%Y-%m-%d %H:%M"),
                }
                for r in rows
            ]
    elif type in ("finance", "intl"):
        cat = "商业财经" if type == "finance" else "国际"
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(News)
                .where(News.category == cat)
                .order_by(News.published_at.desc())
                .limit(10)
            )).scalars().all()
        hot = [
            {
                "title": r.title[:80],
                "hotvalue": 0,
                "source": r.source[:30],
                "url": r.url,
                "published_at": r.published_at.strftime("%Y-%m-%d %H:%M"),
            }
            for r in rows
        ]
    else:
        hot = await fetch_toutiao_hot(10)

        # RSS 兜底（头条热榜失败或未配置 key 时）
        if not hot:
            items = await fetch_rss()
            seen: set[str] = set()
            for it in items:
                u = (it.get("url") or "").strip()
                if not u or u in seen:
                    continue
                seen.add(u)
                hot.append({
                    "title": (it.get("title") or "")[:80],
                    "hotvalue": 0,
                    "source": (it.get("source") or "unknown")[:30],
                    "url": u,
                    "published_at": str(it.get("published_at") or "")[:16],
                })

        # 库内兜底：头条与 RSS 都失败时用库内最新新闻
        if not hot:
            async with AsyncSessionLocal() as db:
                rows = (await db.execute(
                    select(News).order_by(News.published_at.desc()).limit(10)
                )).scalars().all()
            hot = [
                {
                    "title": r.title[:80],
                    "hotvalue": 0,
                    "source": r.source[:30],
                    "url": r.url,
                    "published_at": r.published_at.strftime("%Y-%m-%d %H:%M"),
                }
                for r in rows
            ]

        hot = sorted(hot, key=lambda x: x.get("hotvalue") or 0, reverse=True)[:10]

    _hot_cache[type] = {"ts": time.time(), "items": hot}
    return hot


@router.get("")
async def list_news(page: int = 1, size: int = 20, source: str = "", category: str = "", with_total: int = 0):
    """新闻列表（分页）。with_total=1 时返回 {items, total}，total 为筛选后实际条数（用于正确分页，避免空页）。"""
    async with AsyncSessionLocal() as db:
        conds = []
        if source:
            conds.append(News.source == source)
        if category and is_valid_category(category):
            conds.append(News.category == category)
        stmt = select(News).order_by(News.published_at.desc()).offset((page - 1) * size).limit(size)
        if conds:
            stmt = stmt.where(*conds)
        rows = (await db.execute(stmt)).scalars().all()
        items = [
            NewsOut(
                id=r.id,
                title=r.title,
                source=r.source,
                published_at=r.published_at.strftime("%Y-%m-%d %H:%M"),
                url=r.url,
                trust_level=r.trust_level,
                category=r.category,
                chunk_count=r.chunk_count,
                status=r.status,
                snippet=(r.content or "")[:180],
            )
            for r in rows
        ]
        if with_total:
            cnt = select(func.count()).select_from(News)
            if conds:
                cnt = cnt.where(*conds)
            total = (await db.execute(cnt)).scalar()
            return {"items": items, "total": total}
        return items


@router.post("/refresh")
async def trigger_refresh():
    """手动触发一次新闻抓取 + 入库。"""
    return await news_update_service.refresh_once()


@router.get("/refresh/status")
async def refresh_status():
    """刷新状态：最后一次结果 + 当前阶段进度（fetching/ingesting/cleaning/done/error）。"""
    return {
        **news_update_service.last_refresh_info,
        "progress": news_update_service.refresh_progress,
        "is_refreshing": news_update_service.is_refreshing,
    }


@router.get("/stats")
async def stats():
    from app.config import settings as app_settings
    async with AsyncSessionLocal() as db:
        total = (await db.execute(select(func.count()).select_from(News))).scalar()
        by_source = (await db.execute(select(News.source, func.count()).group_by(News.source))).all()
        by_category = (await db.execute(select(News.category, func.count()).group_by(News.category))).all()
    return {
        "total": total,
        "max_items": app_settings.NEWS_MAX_ITEMS,
        "retention_days": app_settings.NEWS_RETENTION_DAYS,
        "by_source": {s: c for s, c in by_source},
        "by_category": {c: n for c, n in by_category},
    }
