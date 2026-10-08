"""测试 news_dense 查询是否正常（只读）。"""

import asyncio


async def main():
    from app.core.embedding import encode_dense_async
    from app.core.vector_store import query_chroma

    emb = (await encode_dense_async(["芯片行业"]))[0]
    for name in ["news_dense", "chat_memory"]:
        try:
            res = await query_chroma(emb, top_k=2, collection=name)
            docs = (res.get("documents") or [[]])[0]
            print(f"{name}: 查询 OK, 返回 {len(docs)} 条 | {docs[0][:40] if docs else '-'}")
        except Exception as e:
            print(f"{name}: 查询 ERROR {type(e).__name__}: {str(e)[:150]}")


asyncio.run(main())
