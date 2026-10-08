# -*- coding: utf-8 -*-
"""RAGAS 风格评测 CLI 入口（逻辑已迁移到 app/services/eval_service.py）。

用法（backend/ 下，建议先停服务避免 Chroma 并发读写的极端场景）：
    py -3.11 -X utf8 -m tests.eval_ragas
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services import eval_service  # noqa: E402


async def main():
    print("开始评测（15 条真实问题，约 5-8 分钟）…")
    prev = 0
    async def progress_cb(i, total, q, stage):
        nonlocal prev
        if i != prev:
            print(f"  [{i}/{total}] {q[:40]}… ({stage})")
            prev = i
    summary = await eval_service.run_eval(progress_cb=progress_cb)
    print("\n=== 评测完成 ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"报告: {eval_service.EVAL_REPORT}")


if __name__ == "__main__":
    asyncio.run(main())
