"""⚙️ 系统设置接口：入库主题过滤配置（GET/PUT /api/settings/ingest-filter）。"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import ingest_filter

router = APIRouter()


class IngestFilterIn(BaseModel):
    keywords: list[str] = []


@router.get("/ingest-filter")
async def get_ingest_filter():
    """当前入库过滤关键词（空 = 全量收录）。"""
    return {"keywords": ingest_filter.get_keywords()}


@router.put("/ingest-filter")
async def set_ingest_filter(body: IngestFilterIn):
    """保存入库过滤关键词，即时生效（下次抓取/导入按新规则过滤）。"""
    return {"keywords": ingest_filter.set_keywords(body.keywords)}
