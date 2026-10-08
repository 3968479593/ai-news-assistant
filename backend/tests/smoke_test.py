"""冒烟测试：混合检索 + LangGraph Agent 问答（RAG/实时/闲聊三条路由）。

用法：
    cd backend && py -3.11 -m tests.smoke_test
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.agent import ask
from app.core.retriever import retrieve


async def main():
    print("=== 1. 混合检索（向量 + BM25 + 时间加权）===")
    docs = await retrieve("新能源汽车销量", top_k=3)
    for d in docs:
        print(f"  - {d['title']} | score={d['score']:.3f} | {d['source']} | {d['published_at']}")
    assert docs, "检索为空"
    print(f"  命中 {len(docs)} 条 ✓\n")

    print("=== 2. Agent 问答（RAG 路由）===")
    r1 = await ask("新能源汽车市场怎么样？")
    print(f"route={r1['route']} | sources={len(r1['sources'])}")
    print(r1["answer"][:500])
    print()

    print("=== 3. Agent 问答（实时路由：Tavily/RSS）===")
    r2 = await ask("今天有什么科技最新消息？")
    print(f"route={r2['route']} | sources={len(r2['sources'])}")
    print(r2["answer"][:300])
    print()

    print("=== 4. Agent 闲聊 ===")
    r3 = await ask("你好")
    print(f"route={r3['route']}")
    print(r3["answer"][:120])

    print("\n冒烟测试完成 ✓")


if __name__ == "__main__":
    asyncio.run(main())
