"""交互式 CLI：像聊天一样测试新闻助手（无需启动 Web 服务）。

用法：
    cd backend && py -3.11 -m tests.chat_cli
    （输入 exit / quit / 退出 结束）
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.agent import ask


async def main():
    print("=" * 50)
    print("AI 新闻助手 CLI（终端对话测试）")
    print("=" * 50)
    print("试试这些问法：")
    print("  · 新能源汽车市场怎么样？      -> 库内检索(RAG)")
    print("  · 今天有什么科技最新消息？     -> 实时抓取(live)")
    print("  · 你好                        -> 闲聊(chat)")
    print("输入 exit / quit / 退出 结束\n")

    while True:
        try:
            q = input("你：")
        except (EOFError, KeyboardInterrupt):
            break
        if q.strip().lower() in ("exit", "quit", "退出"):
            break
        if not q.strip():
            continue

        r = await ask(q)
        print(f"\n[路由: {r['route']}]")
        print(r["answer"])
        if r.get("sources"):
            print("\n参考来源：")
            for i, s in enumerate(r["sources"], 1):
                print(f"  [{i}] {s['title']} | {s['source']} | {s['published_at']}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
