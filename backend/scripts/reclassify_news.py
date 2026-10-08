"""重分类现有新闻：用最新分类规则（源映射 + 关键词门槛>=1）重算全部新闻的模块并更新 SQLite。

用法：cd backend && py -3.11 -m scripts.reclassify_news
之后必须运行 scripts.rebuild_chroma 重建向量索引（Chroma metadata 中的 category 同步更新）。
注意：运行前先停掉占用端口/Chroma 的服务。
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


async def main():
    from sqlalchemy import select

    import app.models.news  # noqa: F401
    from app.core.categorizer import classify
    from app.models.database import AsyncSessionLocal
    from app.models.news import News

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(News))).scalars().all()
        changed = 0
        for r in rows:
            new_cat = classify(r.title, r.content, r.source)
            if new_cat != r.category:
                r.category = new_cat
                changed += 1
        await db.commit()
        print(f"共 {len(rows)} 条新闻，重分类变更 {changed} 条")

        # 输出新分布
        from sqlalchemy import func
        dist = (await db.execute(select(News.category, func.count()).group_by(News.category))).all()
        for cat, n in sorted(dist, key=lambda x: -x[1]):
            print(f"  {cat}: {n}")


if __name__ == "__main__":
    asyncio.run(main())
