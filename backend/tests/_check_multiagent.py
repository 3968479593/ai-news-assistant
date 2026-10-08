"""多 Agent 协作验证：检索→写稿→审核链路 + 反馈循环 + 闲聊直达。"""
import json
import urllib.request


def post(path, body):
    req = urllib.request.Request(
        "http://127.0.0.1:8000" + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=180).read().decode("utf-8"))


ok = 0
fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✅ {name}")
    else:
        fail += 1
        print(f"  ❌ {name} {extra}")


print("=== 1. 完整链路：检索→写稿→审核 ===")
r = post("/api/chat", {"message": "芯片行业最近有什么进展？"})
print("  trace:", " → ".join(r.get("agent_trace", [])))
trace = r.get("agent_trace", [])
check("路由判定", any("路由" in t for t in trace), str(trace))
check("检索Agent执行", any("检索Agent" in t for t in trace), str(trace))
check("写稿Agent执行", any("写稿Agent" in t for t in trace), str(trace))
check("审核Agent执行", any("审核Agent" in t for t in trace), str(trace))
check("有引用来源", len(r.get("sources", [])) > 0)
check("回答含引用标注", "[1]" in r.get("answer", ""))
check("正常问题不多轮循环", len([t for t in trace if "审核Agent" in t]) <= 2, str(trace))

print("=== 2. 检索 Agent 自主补实时 ===")
r2 = post("/api/chat", {"message": "今天有什么科技最新消息？"})
print("  trace:", " → ".join(r2.get("agent_trace", [])))
trace2 = r2.get("agent_trace", [])
check("检索Agent含实时抓取", any("实时抓取" in t for t in trace2), str(trace2))
check("route=live", r2["route"] == "live", r2["route"])

print("=== 3. 闲聊直达 ===")
r3 = post("/api/chat", {"message": "你好"})
check("route=chat", r3["route"] == "chat", r3["route"])
check("不经过检索/写稿/审核", not any(("Agent" in t and "闲聊" not in t) for t in r3.get("agent_trace", [])), str(r3.get("agent_trace")))

print("=== 4. 冷门问题：不无限循环、链路完整 ===")
r4 = post("/api/chat", {"message": "火星移民计划最新进展如何？"})
print("  trace:", " → ".join(r4.get("agent_trace", [])))
trace4 = r4.get("agent_trace", [])
check("链路完整", any("检索Agent" in t for t in trace4) and any("审核Agent" in t for t in trace4), str(trace4))
check("不无限循环(审核≤5轮)", len([t for t in trace4 if "审核Agent" in t]) <= 5, f"审核轮次={len([t for t in trace4 if '审核Agent' in t])}")
check("结束有答复", len(r4.get("answer", "")) > 0)

print(f"\n结果: {ok} 通过 / {fail} 失败")
raise SystemExit(1 if fail else 0)
