"""本地直调复现对话 500（不经 HTTP，完整打印异常）。"""

import asyncio
import traceback


async def main():
    from app.api.routes.chat import chat
    from app.models.schemas import ChatRequest

    print("=== 第一轮 ===")
    try:
        r1 = await chat(ChatRequest(message="芯片行业最近有什么进展？"))
        sid = r1.session_id
        print("第一轮 OK, session:", sid[:8])
    except Exception:
        traceback.print_exc()
        return

    print("=== 第二轮（带历史） ===")
    try:
        r2 = await chat(ChatRequest(message="展开讲讲刚才提到的第三条", session_id=sid))
        print("第二轮 OK:", r2.answer[:120].replace("\n", " "))
    except Exception:
        traceback.print_exc()


asyncio.run(main())
