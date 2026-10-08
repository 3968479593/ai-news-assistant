"""📡 新闻源状态接口：GET /api/sources -> 逐源探测 RSS 可达性与条数。"""

import asyncio

from fastapi import APIRouter

from app.config import settings
from app.core.news_fetcher import _parse_feed
from app.models.schemas import SourceStatus

router = APIRouter()


@router.get("", response_model=list[SourceStatus])
async def source_status():
    results = []
    for url in settings.NEWS_SOURCES:
        try:
            items = await asyncio.to_thread(_parse_feed, url, settings.NEWS_FETCH_TIMEOUT)
            results.append(SourceStatus(url=url, ok=True, item_count=len(items)))
        except Exception as e:
            results.append(SourceStatus(url=url, ok=False, error=str(e)))
    return results
