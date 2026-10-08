"""纯 HTTP 最小复现：同 session 连续两轮（指向 8001），无本地 Chroma 访问。"""

import json
import urllib.request

BASE = "http://127.0.0.1:8000"


def post(body):
    req = urllib.request.Request(
        BASE + "/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        return json.loads(urllib.request.urlopen(req, timeout=180).read().decode("utf-8"))
    except Exception as e:
        return {"__error__": str(e)[:200]}


r1 = post({"message": "AI大模型最近有什么进展？"})
print("r1:", "OK" if "answer" in r1 else f"FAIL {r1}")
sid = r1.get("session_id", "")
print("r1 session:", sid[:8])

r2 = post({"message": "那成本方面呢？", "session_id": sid})
print("r2:", "OK" if "answer" in r2 else f"FAIL {r2}")
print("r2 answer:", (r2.get("answer") or "")[:120].replace("\n", " "))
