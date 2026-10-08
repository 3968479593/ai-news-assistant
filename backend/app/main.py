import logging
import os
import sys

# ---- 关键：必须在任何 huggingface/sentence_transformers 导入之前设置 ----
from app.config import settings

if settings.HF_ENDPOINT:
    os.environ["HF_ENDPOINT"] = settings.HF_ENDPOINT

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import chat, eval, news, search, sources
from app.api.routes import settings as settings_router
from app.models.database import Base, engine
import app.models.news  # noqa: F401  确保 News 表注册到 Base.metadata

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    # 建表（SQLite）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("=" * 50)
    logger.info("正在预加载嵌入模型（首次启动较慢，之后走缓存）...")
    logger.info(f"嵌入模型: {settings.EMBEDDING_MODEL}")
    logger.info("=" * 50)
    try:
        from app.core.embedding import get_embedding_model
        get_embedding_model()
        logger.info("嵌入模型加载完成！")
    except Exception as e:
        logger.error(f"嵌入模型加载失败: {e}")
        logger.error("提示: 检查 .env 的 EMBEDDING_MODEL 路径，或先运行 backend/scripts/download_models.py")

    if settings.RERANK_ENABLED:
        logger.info("=" * 50)
        logger.info("正在预加载重排序模型（可选，失败不影响主流程）...")
        logger.info("=" * 50)
        try:
            from app.core.reranker import get_reranker
            get_reranker()
            logger.info("重排序模型加载完成！")
        except Exception as e:
            logger.warning(f"重排序模型加载失败（将仅用融合分排序）: {e}")

    logger.info("服务已就绪！")
    logger.info(f"LLM 模式: {'真实 LLM（LangGraph Agent）' if settings.USE_REAL_LLM and settings.LLM_API_KEY else '规则路由 + 模板（演示模式）'}")

    # 启动定时新闻刷新（可选）
    from app.services.news_update import news_update_service, cleanup_news
    await news_update_service.start()
    # 启动时先执行一次容量治理（过期淘汰 + 总量上限），让存量立即收敛
    try:
        cleanup = await cleanup_news()
        logger.info("启动容量治理完成: %s", cleanup)
    except Exception as e:
        logger.warning("启动容量治理失败（不影响服务）: %s", e)


@app.on_event("shutdown")
async def shutdown():
    from app.services.news_update import news_update_service
    await news_update_service.stop()
    logger.info("定时刷新已停止")


app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(news.router, prefix="/api/news", tags=["news"])
app.include_router(sources.router, prefix="/api/sources", tags=["sources"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])
app.include_router(eval.router, prefix="/api/eval", tags=["eval"])

@app.get("/api/health")
async def health_check():
    from app.core.vector_store import collection_count
    chunks = await collection_count()
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "use_real_llm": settings.USE_REAL_LLM and bool(settings.LLM_API_KEY),
        "chroma_chunks": chunks,
    }


# ===== 前端静态托管（frontend/dist 构建产物 → 单端口一体化访问）=====
# 注意：必须放在所有显式路由（含 /api/health）之后注册，否则 catch-all 会吞掉 API 路由。
FRONTEND_DIST = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "frontend", "dist",
)

if os.path.isdir(FRONTEND_DIST):
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles

    assets_dir = os.path.join(FRONTEND_DIST, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """SPA 回退：未匹配的 /api/* 返回 404 JSON，其余路径回退到 index.html。"""
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        idx = os.path.join(FRONTEND_DIST, "index.html")
        if os.path.exists(idx):
            # index.html 不缓存：每次重新验证（防止前端重建后浏览器仍用旧入口引用已被清理的 JS）
            return FileResponse(idx, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
        return JSONResponse({"detail": "Not Found"}, status_code=404)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
