"""模块化改造端到端验证：检索过滤 + Agent 领域路由 + 列表筛选。"""
import json
import urllib.parse
import urllib.request


def post(path, body):
    req = urllib.request.Request(
        "http://127.0.0.1:8000" + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=90).read().decode("utf-8"))


def get(path):
    url = "http://127.0.0.1:8000" + path
    return json.loads(urllib.request.urlopen(url, timeout=30).read().decode("utf-8"))


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


print("=== 1. 检索模块过滤 ===")
all_res = post("/api/search", {"query": "芯片", "top_k": 8})
cat_res = post("/api/search", {"query": "芯片", "top_k": 8, "category": "科技"})
sport_res = post("/api/search", {"query": "芯片", "top_k": 8, "category": "体育"})
check("不加过滤有结果", len(all_res) > 0, f"got {len(all_res)}")
check("科技过滤有结果且全为科技", len(cat_res) > 0 and all(d["category"] == "科技" for d in cat_res), f"got {[d['category'] for d in cat_res]}")
check("体育过滤无芯片结果", len(sport_res) == 0, f"got {len(sport_res)}")
if cat_res:
    top3 = " ".join(d["title"] + d["snippet"] for d in cat_res[:3])
    check("科技过滤前 3 条含芯片主题", any(w in top3 for w in ["芯片", "半导体", "大模型", "AI"]), cat_res[0]["title"][:40])
    for d in cat_res[:3]:
        print(f"    · [{d['category']}] {d['title'][:40]}")

print("=== 2. Agent 领域路由 ===")
r1 = post("/api/chat", {"message": "芯片行业最近有什么进展？"})
print(f"  「芯片行业」→ route={r1['route']} category={r1['category']} 来源{len(r1['sources'])}条")
check("芯片问题路由到科技", r1["route"] == "rag" and r1["category"] == "科技", f"{r1['route']}/{r1['category']}")
r2 = post("/api/chat", {"message": "国足世界杯预选赛情况如何？"})
print(f"  「国足」→ route={r2['route']} category={r2['category']} 来源{len(r2['sources'])}条")
check("国足问题路由到体育", r2["category"] == "体育", f"{r2['route']}/{r2['category']}")

print("=== 3. 新闻列表模块筛选 ===")
sport_news = get("/api/news?category=" + urllib.parse.quote("体育"))
tech_news = get("/api/news?category=" + urllib.parse.quote("科技") + "&size=3")
check("体育列表全为体育", all(n["category"] == "体育" for n in sport_news), f"got {len(sport_news)}")
check("科技列表全为科技", all(n["category"] == "科技" for n in tech_news), f"got {len(tech_news)}")

print("=== 4. 前端页面 ===")
s, body = 0, ""
try:
    r = urllib.request.urlopen("http://127.0.0.1:8000/", timeout=10)
    s = r.status
    body = r.read().decode("utf-8", "ignore")
except Exception as e:
    print(e)
check("首页 200 且为新构建", s == 200 and "index-NFNLQ8nP.js" in body, f"status={s}")

print(f"\n结果: {ok} 通过 / {fail} 失败")
raise SystemExit(1 if fail else 0)
