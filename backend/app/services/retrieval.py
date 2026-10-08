"""检索服务：对外暴露检索接口（供 Agent / API 调用）。"""

from app.core.retriever import retrieve


async def retrieve_news(query: str, top_k: int | None = None, category: str | None = None) -> list[dict]:
    return await retrieve(query, top_k, category)
