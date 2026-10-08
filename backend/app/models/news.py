import datetime as dt

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base


class News(Base):
    """新闻记录：元数据存 SQLite，正文分块存 Chroma（按 news_id 关联）。"""

    __tablename__ = "news"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), index=True)
    content: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(1000), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(200), index=True)
    published_at: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    trust_level: Mapped[int] = mapped_column(Integer, default=3)  # 1~5，来源可信度
    category: Mapped[str] = mapped_column(String(50), default="综合", index=True)  # 模块：科技/商业财经/国际/体育/娱乐/健康/生活/综合
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="ingested", index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)


class SeenUrl(Base):
    """已见 URL 日志（轻量防重抓）。

    被容量治理清理掉的新闻 URL 记入本表，下轮刷新不再重复抓取（根治
    "清理 → 重抓 → 再清理" 死循环）。记录只保留 NEWS_RETENTION_DAYS 天，
    与新闻保留期对齐，防止表无限膨胀；过期的旧 URL 允许重新入库（它们
    若仍是热点会被再次抓回，符合时效性）。
    """

    __tablename__ = "seen_urls"

    url: Mapped[str] = mapped_column(String(1000), primary_key=True)
    first_seen: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)
