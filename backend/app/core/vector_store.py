import asyncio

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings

_client = None


def get_chroma_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=settings.CHROMA_PERSIST_DIR,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _client


def get_dense_collection(name: str | None = None):
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=name or settings.CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


def _sync_add_to_chroma(ids, embeddings, metadatas, documents, collection=None):
    col = get_dense_collection(collection)
    col.add(
        ids=ids,
        embeddings=embeddings,
        metadatas=metadatas,
        documents=documents,
    )


def _sync_query_chroma(query_embedding, top_k, where=None, collection=None):
    col = get_dense_collection(collection)
    kwargs: dict = {
        "query_embeddings": [query_embedding],
        "n_results": top_k,
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where
    return col.query(**kwargs)


def _sync_delete_from_chroma(ids, collection=None):
    if not ids:
        return
    col = get_dense_collection(collection)
    col.delete(ids=ids)


def _sync_delete_by_news_ids(news_ids, collection=None):
    """按 news_id 元数据删除某批新闻的所有分块（容量治理用）。"""
    if not news_ids:
        return 0
    col = get_dense_collection(collection)
    got = col.get(where={"news_id": {"$in": [str(i) for i in news_ids]}}, include=[])
    ids = got.get("ids", [])
    if ids:
        col.delete(ids=ids)
    return len(ids)


def _sync_peek_collection(limit: int = 10, collection=None):
    col = get_dense_collection(collection)
    return col.peek(limit=limit)


def _sync_count(collection=None):
    return get_dense_collection(collection).count()


async def add_to_chroma(ids: list[str], embeddings: list, metadatas: list[dict], documents: list[str], collection: str | None = None):
    await asyncio.to_thread(_sync_add_to_chroma, ids, embeddings, metadatas, documents, collection)


async def query_chroma(query_embedding, top_k: int = 20, where: dict | None = None, collection: str | None = None) -> dict:
    return await asyncio.to_thread(_sync_query_chroma, query_embedding, top_k, where, collection)


async def delete_from_chroma(ids: list[str], collection: str | None = None):
    await asyncio.to_thread(_sync_delete_from_chroma, ids, collection)


async def delete_by_news_ids(news_ids: list[int], collection: str | None = None) -> int:
    return await asyncio.to_thread(_sync_delete_by_news_ids, news_ids, collection)


async def peek_collection(limit: int = 10, collection: str | None = None) -> dict:
    return await asyncio.to_thread(_sync_peek_collection, limit, collection)


async def collection_count(collection: str | None = None) -> int:
    return await asyncio.to_thread(_sync_count, collection)
