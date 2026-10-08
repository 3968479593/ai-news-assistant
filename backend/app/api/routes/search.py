"""🔍 语义检索接口：库内混合检索（POST /api/search）+ 全网实时搜索（POST /api/search/live）。"""

from fastapi import APIRouter

from app.core.news_fetcher import fetch_live
from app.models.schemas import SearchRequest, SearchResultItem
from app.services.retrieval import retrieve_news

router = APIRouter()


@router.post("", response_model=list[SearchResultItem])
async def search(req: SearchRequest):
    """库内检索：仅搜索已入库新闻（向量 + BM25 + 时间加权 + 精排），支持模块过滤。"""
    category = req.category or None
    docs = await retrieve_news(req.query, top_k=req.top_k, category=category)
    return [
        SearchResultItem(
            id=int(d["id"]),
            title=d["title"],
            source=d["source"],
            published_at=str(d["published_at"]),
            url=d["url"],
            trust_level=int(d["trust_level"]),
            category=d.get("category", "综合"),
            snippet=d["snippet"],
            score=round(float(d["score"]), 4),
        )
        for d in docs
    ]


@router.post("/live", response_model=list[SearchResultItem])
async def search_live(req: SearchRequest):
    """全网实时搜索：Tavily 抓最近 3 天实时新闻（无 key 时 RSS 关键词兜底），不入库。"""
    docs = await fetch_live(req.query)
    results = []
    for i, d in enumerate(docs[: req.top_k]):
        snippet = (d.get("content") or "")[:200]
        results.append(
            SearchResultItem(
                id=-(i + 1),  # 实时结果无库内 id，用唯一负 id 保证前端 key 不冲突
                title=d.get("title", ""),
                source=d.get("source", "tavily"),
                published_at=str(d.get("published_at", ""))[:16],
                url=d.get("url", ""),
                trust_level=int(d.get("trust_level") or 3),
                category="实时",
                snippet=snippet,
                score=round(max(0.0, 1.0 - i * 0.05), 4),
            )
        )
    return results
