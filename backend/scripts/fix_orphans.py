# -*- coding: utf-8 -*-
"""数据层修复（停服务后执行）：
1. 清理 Chroma 孤儿 chunk（news_id 已不在 SQLite 的残留，污染语义去重）。
2. 清理前端不可见的娱乐/生活存量新闻（SQLite + Chroma + seen_urls）。
"""
import chromadb
import sqlite3
import sys
from pathlib import Path

ROOT = Path(r"D:\DesktopFiles\cangku-main\ai新闻助手\backend")
sys.path.insert(0, str(ROOT))
from app.config import settings
from app.core.vector_store import get_dense_collection

HIDE_CATEGORIES = ("娱乐", "生活", "体育", "健康")

c = sqlite3.connect(str(ROOT / "data" / "news.db"))
c.row_factory = sqlite3.Row

# 1) Chroma 孤儿 chunk
col = get_dense_collection()
got = col.get(limit=5000, include=["metadatas"])
orphan_ids, orphan_chunks = [], 0
if got and got.get("metadatas"):
    valid = {str(r["id"]) for r in c.execute("select id from news").fetchall()}
    by_news: dict[str, list[str]] = {}
    for meta, cid in zip(got["metadatas"], got["ids"]):
        nid = str(meta.get("news_id"))
        by_news.setdefault(nid, []).append(cid)
    for nid, cids in by_news.items():
        if nid not in valid:
            orphan_ids.append(nid)
            orphan_chunks += len(cids)
if orphan_chunks:
    col.delete(ids=[cid for nid in orphan_ids for cid in by_news[nid]])
print(f"[1] 孤儿 news_id: {len(orphan_ids)} 条，删除 chunk: {orphan_chunks} 个，Chroma 剩余: {col.count()}")

# 2) 隐藏模块存量清理（SQLite + Chroma + seen_urls 防重抓）
rows = c.execute("select id, url from news where category in (%s)" % ",".join("?" * len(HIDE_CATEGORIES)), HIDE_CATEGORIES).fetchall()
if rows:
    ids = [r["id"] for r in rows]
    urls = [r["url"] for r in rows]
    got2 = col.get(where={"news_id": {"$in": [str(i) for i in ids]}}, include=[])
    if got2 and got2.get("ids"):
        col.delete(ids=got2["ids"])
    cur = c.cursor()
    cur.executemany("insert or ignore into seen_urls(url, first_seen) values (?, datetime('now'))", [(u,) for u in urls])
    cur.execute("delete from news where id in (%s)" % ",".join("?" * len(ids)), ids)
    c.commit()
    print(f"[2] 隐藏模块清理: {len(rows)} 条（{dict(c.execute('select category, count(*) from news where category in (%s) group by category' % ','.join('?'*len(HIDE_CATEGORIES)), HIDE_CATEGORIES).fetchall())} 剩余）")
else:
    print("[2] 无隐藏模块存量")

print("SQLite 剩余:", c.execute("select count(*) from news").fetchone()[0])
print("模块分布:", c.execute("select category, count(*) from news group by category").fetchall())
