import json
import re
import urllib.request


def get(path):
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8000" + path, timeout=30)
        body = r.read().decode("utf-8", "ignore")
        return r.status, r.headers.get("Content-Type", ""), body
    except Exception as e:
        return "ERR", "", str(e)


# 1. 首页 HTML → 提取 assets 引用并逐个验证 200
s, ct, body = get("/")
print("GET / ->", s, ct)
assert s == 200 and '<div id="app">' in body, "首页 HTML 异常"
assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', body)
print("  引用 assets:", assets)
for a in assets:
    s2, ct2, _ = get(a)
    print(f"  GET {a} -> {s2} {ct2}")
    assert s2 == 200, f"静态资源失败: {a}"

# 2. 后端 API 冒烟（确保 catch-all 没有吞 API）
s, ct, body = get("/api/news/stats")
print("GET /api/news/stats ->", s)
assert s == 200
stats = json.loads(body)
print("  total =", stats.get("total"), "| by_source =", stats.get("by_source"))

s, ct, body = get("/api/news?page=1&size=3")
print("GET /api/news?page=1&size=3 ->", s)
assert s == 200
items = json.loads(body)
print("  返回条数 =", len(items), "| 首条:", items[0]["title"][:40] if items else "无")

print("\n全部验证通过 ✓")
