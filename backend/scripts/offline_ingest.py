"""离线批量导入新闻（不通过 API）：示例数据 + 已抓取原始数据 → Chroma + SQLite 双写。

用法：
    cd backend && python scripts/offline_ingest.py
    # 指定额外目录：
    python scripts/offline_ingest.py --dirs data/news_sample D:/other/news
"""

import argparse
import asyncio
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.ingestion import ingest_news_items

BASE = os.path.join(os.path.dirname(__file__), "..")


def load_json_dir(data_dir: str) -> list[dict]:
    if not os.path.isdir(data_dir):
        print(f"目录不存在，跳过: {data_dir}")
        return []
    items = []
    for path in sorted(glob.glob(os.path.join(data_dir, "*.json"))):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                items.extend(data)
            elif isinstance(data, dict):
                items.append(data)
        except Exception as e:
            print(f"解析失败 {path}: {e}")
    return items


async def main(data_dirs: list[str] | None = None):
    if data_dirs is None:
        data_dirs = [
            os.path.join(BASE, "data", "news_sample"),
            os.path.join(BASE, "data", "news_raw"),
        ]
    items = []
    for d in data_dirs:
        items += load_json_dir(d)

    if not items:
        print("没有可导入的新闻数据。")
        return

    print(f"共 {len(items)} 条待导入，开始入库（首次会加载嵌入模型，请耐心等待）...")
    stats = await ingest_news_items(items)
    print("\n入库统计:", stats)
    print("可用 python scripts/refresh_news.py 抓取最新新闻后再次导入。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dirs", nargs="*", default=None)
    args = parser.parse_args()
    asyncio.run(main(args.dirs))
