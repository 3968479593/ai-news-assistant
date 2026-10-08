"""评测接口：前端触发评测运行 + 查询进度 + 读取结果。"""
import json
import time

from fastapi import APIRouter, HTTPException

from app.services import eval_service

router = APIRouter()


@router.post("/run")
async def eval_run():
    """启动评测（异步，约 5-8 分钟）。已在跑则返回 started=false。"""
    return await eval_service.start_eval()


@router.get("/status")
async def eval_status():
    """评测进度：current/total/question/stage/running。"""
    return eval_service.get_eval_status()


@router.get("/report")
async def eval_report():
    """评测结果：三指标平均分 + top1 命中率 + 逐条明细（不含长回答）。"""
    if not eval_service.EVAL_RESULT.exists():
        raise HTTPException(status_code=404, detail="尚无评测结果，先点击「运行评测」")
    data = json.loads(eval_service.EVAL_RESULT.read_text(encoding="utf-8"))
    items = data.get("items", [])
    top1_hit = sum(
        1 for r in items
        if r.get("context_titles") and any(e in r["context_titles"][0] for e in r.get("expected", []))
    )
    return {
        "summary": data.get("summary", {}),
        "top1_hit_rate": round(top1_hit / len(items), 3) if items else 0,
        "n": len(items),
        "updated_at": eval_service.EVAL_RESULT.stat().st_mtime,
        "items": [
            {
                "question": r["question"],
                "category": r["category"],
                "context_precision": r["context_precision"],
                "faithfulness": r["faithfulness"],
                "answer_relevancy": r["answer_relevancy"],
                "top1_hit": bool(
                    r.get("context_titles") and any(e in r["context_titles"][0] for e in r.get("expected", []))
                ),
            }
            for r in items
        ],
    }
