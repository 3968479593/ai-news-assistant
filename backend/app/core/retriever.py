import asyncio
import datetime as dt
import logging
import re

from rank_bm25 import BM25Okapi
from sqlalchemy import select

from app.config import settings
from app.core.embedding import encode_dense_async
from app.core.vector_store import query_chroma
from app.core.rrf import rrf_merge
from app.models.database import AsyncSessionLocal
from app.models.news import News

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+")
_SPLIT_RE = re.compile(r"[、，,；;和与及]")


def tokenize(text: str) -> list[str]:
    """中英混合切分：汉字逐字、英文/数字按词，统一小写。"""
    return _TOKEN_RE.findall(text.lower())


def _distance_to_score(distance: float) -> float:
    """Chroma cosine distance → 相似度分数（0~1）。"""
    return 1.0 - float(distance)


def _time_weight(score: float, published_at: dt.datetime, now: dt.datetime | None = None) -> float:
    """时间衰减：新闻越旧分越低；超过 MAX_NEWS_AGE_DAYS 直接剔除。"""
    if now is None:
        now = dt.datetime.now(published_at.tzinfo) if published_at.tzinfo else dt.datetime.now()
    age = max(0, (now - published_at).days)
    if age > settings.MAX_NEWS_AGE_DAYS:
        return 0.0
    return score / (1 + settings.TIME_DECAY * age)


def _as_datetime(value) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value)
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value)
        except ValueError:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.datetime.now()


async def _load_news_items(max_age_days: int | None = None, category: str | None = None) -> list[dict]:
    """从 SQLite 加载新闻（BM25 语料 + 元数据补齐），可按时效 / 模块过滤。"""
    async with AsyncSessionLocal() as db:
        stmt = select(News).where(News.status == "ingested")
        if max_age_days is not None:
            cutoff = dt.datetime.now() - dt.timedelta(days=max_age_days)
            stmt = stmt.where(News.published_at >= cutoff)
        if category:
            stmt = stmt.where(News.category == category)
        rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(r.id),
            "title": r.title,
            "content": r.content,
            "url": r.url,
            "source": r.source,
            "published_at": r.published_at,
            "trust_level": r.trust_level,
            "category": r.category,
        }
        for r in rows
    ]


def _bm25_rank(query: str, items: list[dict], top_k: int) -> set[str]:
    """BM25 召回，返回有词重叠命中的 news_id 集合。"""
    corpus = [tokenize(f'{i["title"]} {i["content"]}') for i in items]
    if not corpus:
        return set()
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(tokenize(query))
    ranked = sorted(range(len(items)), key=lambda idx: scores[idx], reverse=True)[:top_k]
    return {str(items[idx]["id"]) for idx in ranked if scores[idx] > 0}


async def _vector_rank(query: str, top_k: int, category: str | None = None) -> dict[str, float]:
    """稠密向量召回，返回 {news_id: 最高 chunk 相似度}（chunk 级去重）。"""
    emb = (await encode_dense_async([query]))[0]
    where = {"category": category} if category else None
    res = await query_chroma(emb, top_k=top_k, where=where)
    ids = (res.get("ids") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    best: dict[str, float] = {}
    for cid, meta, dist in zip(ids, metas, dists):
        news_id = str(meta.get("news_id") or cid)
        sim = 1.0 - float(dist)
        if sim > best.get(news_id, 0.0):
            best[news_id] = sim
    return best


async def retrieve(query: str, top_k: int | None = None, category: str | None = None) -> list[dict]:
    """混合检索管道：
    向量召回 + BM25 召回 → RRF 融合 → 时间衰减重排 → （可选）Cross-encoder 精排
    category 不为空时仅在该模块内检索（向量 where 过滤 + BM25 语料过滤）。
    仅被向量召回且相似度低于下限、又无 BM25 词重叠的结果会被剔除（避免无关结果充数）。
    """
    if top_k is None:
        top_k = settings.RERANK_TOP_K if settings.RERANK_ENABLED else settings.RETRIEVAL_TOP_K

    # 并行：语料加载（DB）与向量召回（编码 + Chroma）互不依赖，同时进行
    items_task = asyncio.create_task(_load_news_items(max_age_days=settings.MAX_NEWS_AGE_DAYS, category=category))
    vector_task = asyncio.create_task(_vector_rank(query, settings.RETRIEVAL_TOP_K, category))
    try:
        items, vector_map = await asyncio.gather(items_task, vector_task)
    except Exception as e:
        logger.warning("并行检索阶段失败，降级串行: %s", e)
        items = await _load_news_items(max_age_days=settings.MAX_NEWS_AGE_DAYS, category=category)
        vector_map = await _vector_rank(query, settings.RETRIEVAL_TOP_K, category)
    by_id = {str(i["id"]): i for i in items}
    bm25_ids = _bm25_rank(query, items, settings.BM25_TOP_K)

    merged = rrf_merge([list(vector_map), list(bm25_ids)])
    if not merged:
        return []

    now = dt.datetime.now()
    scored = []
    for news_id in merged:
        item = by_id.get(news_id)
        if not item:
            continue
        # 相关性下限：无 BM25 词重叠且向量相似度过低 → 剔除
        if news_id not in bm25_ids and vector_map.get(news_id, 0.0) < settings.MIN_VECTOR_SIMILARITY:
            continue
        score = _time_weight(1.0, item["published_at"], now)
        if score <= 0:
            continue
        item = dict(item)
        item["score"] = score
        item["vector_sim"] = vector_map.get(news_id, 0.0)  # 纯向量相似度（写稿前筛素材用）
        item["snippet"] = item["content"][:200]
        scored.append(item)

    scored.sort(key=lambda d: d["score"], reverse=True)
    scored = scored[: max(top_k * 3, 20)]

    # 可选精排：Cross-encoder 对 (query, 片段) 打分，覆盖融合分
    if settings.RERANK_ENABLED:
        try:
            from app.core.reranker import rerank
            scored = await rerank(query, scored)
        except Exception:
            pass

    return scored[:top_k]


def split_queries(query: str) -> list[str]:
    """把复合问题按中文并列连接词拆成多个子检索 query（多路检索用，零 LLM 成本）。

    例："大模型训练和推理成本有什么区别" → ["大模型训练", "推理成本", "有什么区别"]
    无连接词时原样返回单路。最多拆 3 路，避免检索过碎。
    """
    parts = [p.strip() for p in _SPLIT_RE.split(query) if len(p.strip()) >= 2]
    if len(parts) < 2:
        return [query]
    return parts[:3]


async def retrieve_multi(query: str, top_k: int | None = None, category: str | None = None) -> list[dict]:
    """多路混合检索：复合问题拆成子 query 并行检索，按融合分合并去重后取 top_k。

    相比单路检索：覆盖更全（如"XX 和 YY"两主题都能召回），子路各自按相似度把关，
    合并后只保留分最高的 top_k，避免稀释答案。
    关键：合并后追加一次「对原始 query 的全局精排」——子 query 精排分跨路不可比，
    不重排会导致第 2-N 位混入同实体不同事件的弱相关新闻（评测 AP 低的机制根因）。
    """
    if top_k is None:
        top_k = settings.RERANK_TOP_K if settings.RERANK_ENABLED else settings.RETRIEVAL_TOP_K
    subs = split_queries(query)
    if len(subs) <= 1:
        return await retrieve(query, top_k, category)

    results = await asyncio.gather(
        *[retrieve(s, max(top_k * 2, 10), category) for s in subs]
    )
    merged: dict[str, dict] = {}
    for docs in results:
        for d in docs:
            u = d.get("url")
            if not u or u in merged:
                continue
            merged[u] = d
    ranked = sorted(merged.values(), key=lambda d: d.get("score", 0.0), reverse=True)
    # 全局精排：以原始 query 对合并结果重新打分，跨路分数归一可比
    if settings.RERANK_ENABLED:
        try:
            from app.core.reranker import rerank
            ranked = await rerank(query, ranked[: max(top_k * 3, 20)])
        except Exception:
            pass
    return ranked[:top_k]
