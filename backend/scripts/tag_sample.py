"""给示例新闻（news_sample/sample_news.json）手工补模块标签（category）。

运行：cd backend && python scripts/tag_sample.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 标题关键词 → 模块（按示例数据逐条精标，比纯规则更准）
TITLE_RULES = [
    ("AI 芯片", "科技"),
    ("大模型", "科技"),
    ("折叠屏", "科技"),
    ("新能源汽车", "商业财经"),
    ("黄金", "商业财经"),
    ("A 股", "商业财经"),
    ("大飞机", "科技"),
    ("空间站", "科技"),
    ("医保", "健康"),
    ("旅游", "生活"),
    ("世界杯", "体育"),
    ("台风", "生活"),
]


def main():
    path = os.path.join(os.path.dirname(__file__), "..", "data", "news_sample", "sample_news.json")
    with open(path, "r", encoding="utf-8") as f:
        items = json.load(f)
    for item in items:
        title = item.get("title", "")
        cat = "综合"
        for kw, c in TITLE_RULES:
            if kw in title:
                cat = c
                break
        item["category"] = cat
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    from collections import Counter
    print("已标注", len(items), "条:", dict(Counter(i["category"] for i in items)))


if __name__ == "__main__":
    main()
