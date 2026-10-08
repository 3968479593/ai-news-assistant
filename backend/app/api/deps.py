"""FastAPI 依赖注入：数据库会话等（阶段一无鉴权，保留格式便于后续扩展）。"""

from app.models.database import AsyncSessionLocal


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
