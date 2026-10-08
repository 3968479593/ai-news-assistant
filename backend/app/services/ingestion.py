"""入库服务：标准化新闻 → 查重（URL + 标题归一化 + 语义） → 打模块标签 → 切块 → 嵌入 → 双写 Chroma + SQLite。"""

import datetime as dt
import re

from sqlalchemy import select

from app.config import settings
from app.core.categorizer import classify
from app.core.embedding import encode_dense_async
from app.core.vector_store import add_to_chroma, query_chroma
from app.models.database import AsyncSessionLocal
from app.models.news import News, SeenUrl
from app.services.ingest_filter import matches
from app.utils.chunker import semantic_chunk


def _parse_published(value) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value)
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value)
        except ValueError:
            return dt.datetime.now()
    return dt.datetime.now()


async def _load_existing_urls(db) -> set[str]:
    """现存 + 已见 URL 集合：news 表（在库）+ seen_urls 表（被清理过、保留期内不重抓）。"""
    rows = (await db.execute(select(News.url))).scalars().all()
    seen = (await db.execute(select(SeenUrl.url))).scalars().all()
    return set(rows) | set(seen)


def _norm_title(title: str) -> str:
    """标题归一化：去所有非字母数字字符（含中英文标点/空格）并小写。

    用于跨源转发去重：同一新闻被不同源转载时 URL 不同，但标题归一化后完全一致。
    """
    return re.sub(r"[\W_]+", "", title).lower()


async def _load_existing_titles(db) -> set[str]:
    """库内已有新闻的归一化标题集合。"""
    rows = (await db.execute(select(News.title))).scalars().all()
    return {_norm_title(t) for t in rows if t}


async def _semantic_duplicate(title: str, content: str, category: str) -> bool:
    """语义去重：新新闻与库内已有新闻的向量相似度 >= 阈值则视为重复（转载/改写）。

    用「标题 + 正文前 500 字」的向量查询**全库** top3（不限定同模块——跨模块转载
    也能拦；top3 提高发现率，避免同批入库时序/单条 top1 漏检）。
    """
    if not settings.SEMANTIC_DEDUP_THRESHOLD:
        return False
    try:
        probe = (await encode_dense_async([f"{title}\n{content[:500]}"]))[0]
        res = await query_chroma(probe, top_k=3)
        distances = (res.get("distances") or [[]])[0]
        if not distances:
            return False
        similarity = 1.0 - min(float(d) for d in distances)
        return similarity >= settings.SEMANTIC_DEDUP_THRESHOLD
    except Exception:
        return False


async def ingest_news_items(items: list[dict], dedup: bool = True, progress: dict | None = None) -> dict:
    """批量入库新闻，返回统计。

    流程：URL 查重 → 语义去重 → 模块标签 → SQLite 建档 → 切块 → BGE-M3 嵌入 → 写入 Chroma → 回填状态。
    dedup=False 时跳过 URL/语义查重（用于从 SQLite 重建 Chroma 索引）。
    progress 可选：刷新进度 dict（前端轮询展示），循环内回写 processed/filtered。
    """
    stats = {"total": len(items), "added": 0, "skipped": 0, "failed": 0, "filtered": 0, "chunks": 0}

    # 批量嵌入：攒够 BATCH 条新闻后一次性编码（CPU 上 batch 吞吐远高于逐条），再逐条写 Chroma
    BATCH = 16
    pending: list[tuple[News, list[str]]] = []

    async def flush_pending():
        nonlocal stats
        if not pending:
            return
        all_chunks: list[str] = []
        for _, chunks in pending:
            all_chunks.extend(chunks)
        try:
            all_emb = await encode_dense_async(all_chunks)
        except Exception as e:
            print(f"  [ingest] 批量嵌入失败: {e}")
            for news, _ in pending:
                news.status = "failed"
                stats["failed"] += 1
            pending.clear()
            return
        idx = 0
        for news, chunks in pending:
            n = len(chunks)
            emb = all_emb[idx:idx + n]
            idx += n
            news_id = news.id
            ids = [f"{news_id}::{j}" for j in range(n)]
            metadatas = [
                {
                    "news_id": str(news_id),
                    "title": news.title,
                    "source": news.source,
                    "category": news.category,
                    "url": news.url,
                    "published_at": news.published_at.timestamp(),
                    "trust_level": news.trust_level,
                }
                for _ in chunks
            ]
            try:
                await add_to_chroma(ids, emb, metadatas, chunks)
                news.chunk_count = n
                news.status = "ingested"
                stats["added"] += 1
                stats["chunks"] += n
            except Exception as e:
                news.status = "failed"
                stats["failed"] += 1
                print(f"  [ingest] 写向量失败 {news.title[:30]}: {e}")
        pending.clear()

    async with AsyncSessionLocal() as db:
        existing = await _load_existing_urls(db) if dedup else set()
        existing_titles = await _load_existing_titles(db) if dedup else set()
        seen_titles: set[str] = set()  # 本次批次内已入库的归一化标题

        processed = 0
        for item in items:
            processed += 1
            url = (item.get("url") or "").strip()
            title = (item.get("title") or "").strip()
            content = (item.get("content") or "").strip()
            if not url or not title or not content:
                stats["failed"] += 1
                continue
            if dedup and url in existing:
                stats["skipped"] += 1
                continue

            # 标题归一化去重：跨源转载同一新闻（URL 不同）直接跳过（语义去重前的第一道闸）
            nt = _norm_title(title)
            if dedup and (nt in existing_titles or nt in seen_titles):
                stats["skipped"] += 1
                continue

            source = (item.get("source") or "unknown")[:200]

            # 主题过滤闸门：频道源（财经/国际等）直接放行；泛源命中关键词白名单才入库
            if not matches(title, content, source):
                stats["filtered"] += 1
                if progress:
                    progress["filtered"] = stats["filtered"]
                    progress["processed"] = processed
                continue

            # 模块标签：优先取显式字段，否则自动分类
            category = (item.get("category") or classify(title, content, source))[:50]

            # 语义去重（阈值 .env SEMANTIC_DEDUP_THRESHOLD=0.90，全库 top3）
            if dedup and await _semantic_duplicate(title, content, category):
                stats["skipped"] += 1
                continue

            seen_titles.add(nt)  # 本次批次内标题去重登记

            news = News(
                title=title[:500],
                content=content,
                url=url,
                source=source,
                published_at=_parse_published(item.get("published_at")),
                trust_level=int(item.get("trust_level") or 3),
                category=category,
                status="processing",
            )
            db.add(news)
            await db.flush()  # 拿到自增 id

            try:
                chunks = semantic_chunk(f"{title}\n{content}")
                if not chunks:
                    raise ValueError("切块为空")
                pending.append((news, chunks))
                if len(pending) >= BATCH:
                    await flush_pending()
            except Exception as e:
                news.status = "failed"
                stats["failed"] += 1
                print(f"  [ingest] 入库失败 {title[:30]}: {e}")

            if progress:
                progress["processed"] = processed

        await flush_pending()
        await db.commit()

    return stats
