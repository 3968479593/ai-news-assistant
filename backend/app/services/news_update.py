"""定时新闻刷新服务：周期抓取 RSS → 落盘 → 入库（对应 .env 的 NEWS_REFRESH_*）。
容量治理：每次刷新后自动执行更新机制——过期淘汰（NEWS_RETENTION_DAYS）+ 总量上限（NEWS_MAX_ITEMS）。
"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import delete as sa_delete, func, insert as sa_insert, select

from app.config import settings
from app.core.news_fetcher import fetch_rss, save_raw
from app.core.vector_store import delete_by_news_ids
from app.models.database import AsyncSessionLocal
from app.models.news import News, SeenUrl
from app.services.ingestion import ingest_news_items

logger = logging.getLogger(__name__)


async def _drop_news(db, news_ids: list[int]) -> int:
    """删除指定新闻（SQLite + Chroma + seen_urls 防重抓），返回删除条数。"""
    if not news_ids:
        return 0
    ids = list(news_ids)
    urls = (await db.execute(select(News.url).where(News.id.in_(ids)))).scalars().all()
    if urls:
        await db.execute(
            sa_insert(SeenUrl).prefix_with("OR IGNORE"),
            [{"url": u} for u in urls],
        )
    removed_chunks = await delete_by_news_ids(ids)
    await db.execute(sa_delete(News).where(News.id.in_(ids)))
    await db.commit()
    return removed_chunks


async def cleanup_news() -> dict:
    """更新机制：删除过期新闻（> N 天）＋ 按模块配额淘汰最旧，SQLite 与 Chroma 同步清理。

    配额策略：每个模块最多保留 NEWS_MODULE_QUOTA[模块] 条（未列模块默认 10），
    模块内按发布时间保留最新，防止单一模块（如科技源多）挤占其他模块。
    被清理的 URL 记入 seen_urls（轻量防重抓），同时清理已超过保留期的 seen 记录。
    返回 {expired, overflow, total_dropped, remaining}。
    """
    cutoff = datetime.now() - timedelta(days=settings.NEWS_RETENTION_DAYS)
    default_quota = 10
    quota = dict(settings.NEWS_MODULE_QUOTA or {})
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(News.id, News.category, News.published_at)
                .order_by(News.published_at.desc())
            )
        ).all()

        expired_ids: list[int] = []
        overflow_ids: list[int] = []
        kept_per_cat: dict[str, int] = {}
        for nid, cat, published_at in rows:
            if published_at < cutoff:
                expired_ids.append(nid)
                continue
            cat_quota = quota.get(cat, default_quota)
            kept = kept_per_cat.get(cat, 0)
            if kept >= cat_quota:
                overflow_ids.append(nid)
            else:
                kept_per_cat[cat] = kept + 1

        drop_ids = expired_ids + overflow_ids
        if not drop_ids:
            # 即使无删除，也顺手清理过期的 seen_urls（防表无限膨胀）
            await db.execute(sa_delete(SeenUrl).where(SeenUrl.first_seen < cutoff))
            await db.commit()
            remaining = len(rows)
            # 总量硬上限：配额之外仍超 MAX_ITEMS 时按最旧补删（跨模块统一兜底）
            if remaining > settings.NEWS_MAX_ITEMS:
                excess = remaining - settings.NEWS_MAX_ITEMS
                extra = [nid for nid, _, _ in rows[-excess:]]
                await _drop_news(db, extra)
                remaining -= len(extra)
                logger.info("总量上限兜底: 额外删除 %d 条（%d -> %d）", len(extra), remaining + len(extra), remaining)
            return {"expired": 0, "overflow": 0, "total_dropped": 0, "remaining": remaining}

        # 被清理的 URL 记入 seen_urls（OR IGNORE 防重复），下轮刷新不再重抓
        drop_urls = (
            await db.execute(select(News.url).where(News.id.in_(drop_ids)))
        ).scalars().all()
        if drop_urls:
            await db.execute(
                sa_insert(SeenUrl).prefix_with("OR IGNORE"),
                [{"url": u} for u in drop_urls],
            )
        # 清理已超过保留期的 seen 记录（与新闻保留期对齐，防无限膨胀）
        await db.execute(sa_delete(SeenUrl).where(SeenUrl.first_seen < cutoff))

        removed_chunks = await delete_by_news_ids(drop_ids)
        await db.execute(sa_delete(News).where(News.id.in_(drop_ids)))
        await db.commit()

        remaining = (await db.execute(select(func.count()).select_from(News))).scalar()
        # 总量硬上限：模块配额之外仍超 MAX_ITEMS 时按最旧补删（跨模块统一兜底）
        if remaining > settings.NEWS_MAX_ITEMS:
            all_rows = (await db.execute(
                select(News.id).order_by(News.published_at.asc())
            )).scalars().all()
            excess = remaining - settings.NEWS_MAX_ITEMS
            extra = list(all_rows[:excess])
            await _drop_news(db, extra)
            remaining -= len(extra)
            logger.info("总量上限兜底: 额外删除 %d 条（%d -> %d）", len(extra), remaining + len(extra), remaining)
        logger.info(
            "新闻库更新机制: 过期 %d 条 / 超限淘汰 %d 条，共删 %d 条（Chroma %d 块），剩余 %d 条",
            len(expired_ids), len(overflow_ids), len(drop_ids), removed_chunks, remaining,
        )
        return {
            "expired": len(expired_ids),
            "overflow": len(overflow_ids),
            "total_dropped": len(drop_ids),
            "chunks_removed": removed_chunks,
            "remaining": remaining,
        }


class NewsUpdateService:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self.is_refreshing: bool = False
        self.last_refresh_info: dict = {
            "last_at": None,
            "added": 0,
            "skipped": 0,
            "failed": 0,
            "chunks": 0,
            "error": None,
        }
        # 刷新阶段进度（供前端轮询展示，避免 3 分钟黑盒）
        self.refresh_progress: dict = {
            "stage": "idle",      # idle / fetching / ingesting / cleaning / done / error
            "detail": "",
            "processed": 0,       # 入库已处理条数
            "total": 0,           # 本次抓取总条数
            "filtered": 0,        # 主题过滤拦截条数
        }

    async def start(self):
        if not settings.NEWS_REFRESH_ENABLED:
            logger.info("定时新闻刷新未启用（NEWS_REFRESH_ENABLED=false）")
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("定时新闻刷新已启动，间隔 %d 小时", settings.NEWS_REFRESH_INTERVAL_HOURS)

    async def stop(self):
        if self._task:
            self._task.cancel()
            logger.info("定时新闻刷新已停止")

    async def _loop(self):
        while True:
            await self.refresh_once()
            await asyncio.sleep(settings.NEWS_REFRESH_INTERVAL_HOURS * 3600)

    async def refresh_once(self) -> dict:
        if self.is_refreshing:
            return {"error": "刷新正在进行中", **self.last_refresh_info}
        self.is_refreshing = True
        try:
            self.refresh_progress.update({"stage": "fetching", "detail": "正在抓取新闻源…", "processed": 0, "total": 0, "filtered": 0})
            items = await fetch_rss()
            path = save_raw(items)
            self.refresh_progress.update({
                "stage": "ingesting", "total": len(items), "processed": 0,
                "detail": f"已抓取 {len(items)} 条，正在入库…",
            })
            stats = await ingest_news_items(items, progress=self.refresh_progress)
            # 更新机制：抓取后自动执行过期淘汰 + 容量上限
            self.refresh_progress.update({"stage": "cleaning", "detail": "正在清理过期 / 超限新闻…"})
            cleanup = await cleanup_news()
            self.last_refresh_info = {
                "last_at": _now_str(),
                "raw_file": path,
                **stats,
                "cleanup": cleanup,
                "error": None,
            }
            self.refresh_progress.update({"stage": "done", "detail": "完成", "processed": stats.get("added", 0)})
            logger.info("新闻刷新完成: %s | 清理: %s", stats, cleanup)
        except Exception as e:
            self.last_refresh_info.update({"error": str(e)})
            self.refresh_progress.update({"stage": "error", "detail": f"失败：{e}"})
            logger.error("新闻刷新失败: %s", e)
        finally:
            self.is_refreshing = False
        return self.last_refresh_info


def _now_str() -> str:
    import datetime as dt
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


news_update_service = NewsUpdateService()
