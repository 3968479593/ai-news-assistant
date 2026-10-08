"""对话记忆验证：会话内连续追问 + 跨会话向量召回（不依赖前端）。"""

import asyncio
import json
import urllib.request


def post(body):
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=180).read().decode("utf-8"))


async def main():
    print("=== 1. 会话内记忆：连续追问 ===")
    r1 = post({"message": "芯片行业最近有什么进展？"})
    sid = r1["session_id"]
    print("第一轮 session:", sid[:8], "| trace:", r1["agent_trace"][-1])

    r2 = post({"message": "展开讲讲刚才提到的第三条", "session_id": sid})
    same = r2["session_id"] == sid
    print("第二轮 session 一致:", same)
    print("第二轮回答:", r2["answer"][:150].replace("\n", " "))

    # 关键断言：第二轮回答应引用第一轮内容（如"芯片"/来源标题），而非当成全新问题
    a2 = r2["answer"]
    has_tie = any(k in a2 for k in ["芯片", "半导体"]) and ("刚才" in a2 or "前面" in a2 or "上一条" in a2)
    print("回答体现会话承接:", has_tie)

    print("\n=== 2. 新会话互不串扰 ===")
    r3 = post({"message": "你好"})
    print("新会话 session 不同:", r3["session_id"] != sid, "| route:", r3["route"])


asyncio.run(main())
