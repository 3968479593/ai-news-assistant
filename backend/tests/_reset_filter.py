"""重置入库过滤为全量收录（修复乱码关键词）。"""
import json
from pathlib import Path

f = Path(r"D:\DesktopFiles\cangku-main\ai新闻助手\backend\data\ingest_filter.json")
f.write_text(json.dumps({"keywords": []}, ensure_ascii=False, indent=2), encoding="utf-8")
print("已清空:", f.read_text(encoding="utf-8"))
