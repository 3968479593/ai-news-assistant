# -*- coding: utf-8 -*-
"""评测服务：在前端触发 RAGAS 风格评测（异步任务 + 进度状态）。

评测任务在服务进程内运行（检索只读 Chroma，单进程安全），结果写回 eval_result.json。
"""
import asyncio
import json
import time
from pathlib import Path

from app.core.agent import _build_write_prompt, _needs_analysis, get_chat_model
from app.core.retriever import retrieve_multi
from langchain_core.messages import HumanMessage, SystemMessage

ROOT = Path(__file__).resolve().parent.parent.parent  # backend/
EVAL_SET = ROOT / "tests" / "eval_set.json"
EVAL_RESULT = ROOT / "data" / "eval_result.json"
EVAL_REPORT = ROOT / "data" / "eval_report.md"
TOP_K = 5

# 全局评测状态（单任务并发控制）
_state = {
    "running": False,
    "task": None,
    "current": 0,
    "total": 0,
    "question": "",
    "stage": "idle",  # idle / retrieving / writing / judging / done / error
    "error": "",
    "started_at": 0,
    "finished_at": 0,
}


def get_eval_status() -> dict:
    return {
        "running": _state["running"],
        "current": _state["current"],
        "total": _state["total"],
        "question": _state["question"],
        "stage": _state["stage"],
        "error": _state["error"],
        "started_at": _state["started_at"],
        "finished_at": _state["finished_at"],
    }


def judge(prompt: str, max_tokens: int = 800) -> str:
    resp = get_chat_model().invoke([
        SystemMessage(content=prompt),
        HumanMessage(content="请按上述要求输出。"),
    ])
    return (resp.content or "").strip()


async def retrieve_for(q: str, category: str) -> list[dict]:
    docs = await retrieve_multi(q, top_k=TOP_K, category=category)
    return [
        {"title": d.get("title", ""), "source": d.get("source", ""),
         "content": (d.get("content") or d.get("snippet") or "")[:400], "url": d.get("url", "")}
        for d in docs
    ]


def eval_context_precision(question: str, contexts: list[dict]) -> float:
    if not contexts:
        return 0.0
    ctx_text = "\n".join(
        f"[{i + 1}] 标题：{c['title']}\n内容：{c['content'][:200]}" for i, c in enumerate(contexts)
    )
    prompt = (
        "你是评测员。给定用户问题与检索到的上下文列表，逐条判定每条上下文是否与问题相关。\n"
        f"问题：{question}\n\n上下文列表：\n{ctx_text}\n\n"
        "输出格式：每行一条「序号: 是/否」，只输出这个，不要解释。"
    )
    try:
        out = judge(prompt, 300)
    except Exception as e:
        return 0.0
    rel = {}
    for line in out.splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        idx_s, verdict = line.split(":", 1)
        try:
            idx = int(idx_s.strip())
        except ValueError:
            continue
        rel[idx] = verdict.strip() in ("是", "yes", "Yes", "YES")
    hits, prec_sum = 0, 0.0
    for k in range(1, len(contexts) + 1):
        if rel.get(k, False):
            hits += 1
            prec_sum += hits / k
    return prec_sum / len(contexts)


def eval_faithfulness(question: str, answer: str, contexts: list[dict]) -> float:
    ctx_text = "\n".join(f"[{i + 1}] {c['title']}：{c['content'][:250]}" for i, c in enumerate(contexts))
    prompt = (
        "你是评测员。给定用户问题、AI 回答与参考上下文，把回答拆成若干原子事实声明（每句一个），"
        "然后逐条判定该声明是否被参考上下文支持（支持=能从上文找到依据；不支持=与上文矛盾或凭空编造）。\n"
        "注意：若回答包含【AI 解读】段落，该段为已显式标注的模型分析推断，不作为事实声明判定，忽略该段。\n"
        f"问题：{question}\n\n参考上下文：\n{ctx_text}\n\n回答：\n{answer}\n\n"
        "输出格式：每行一条「声明文本 || 支持/不支持」，只输出这个，不要解释。"
    )
    try:
        out = judge(prompt, 1200)
    except Exception as e:
        return 0.0
    supported = total = 0
    for line in out.splitlines():
        line = line.strip()
        if "||" not in line:
            continue
        claim, verdict = line.split("||", 1)
        verdict = verdict.strip()
        if not claim.strip() or verdict not in ("支持", "不支持"):
            continue
        total += 1
        if verdict == "支持":
            supported += 1
    return supported / total if total else 0.0


def eval_answer_relevancy(question: str, answer: str) -> float:
    prompt = (
        "你是评测员。评估 AI 回答与用户问题的相关性（1-5 分）：\n"
        "5=完全切题且信息充分；3=部分切题或略冗余；1=答非所问或关键缺失。\n"
        f"问题：{question}\n\n回答：\n{answer}\n\n只输出一个整数分数，不要解释。"
    )
    try:
        out = judge(prompt, 50)
        score = int("".join(ch for ch in out if ch.isdigit()) or "0")
        return min(max(score, 1), 5) / 5
    except Exception:
        return 0.0


def write_answer(question: str, contexts: list[dict]) -> str:
    docs = [{"title": c["title"], "source": c["source"], "published_at": "",
             "url": c["url"], "content": c["content"]} for c in contexts]
    context = "\n\n".join(
        f"[{i}] 标题：{d['title']}\n来源：{d['source']}\n{(d.get('content') or '')[:400]}"
        for i, d in enumerate(docs[:8], 1)
    )
    prompt = _build_write_prompt(context, "", "", "", _needs_analysis(question))
    resp = get_chat_model().invoke([
        SystemMessage(content=prompt),
        HumanMessage(content=question),
    ])
    return resp.content or ""


async def run_eval(progress_cb=None) -> dict:
    """跑完整评测，写回 eval_result.json / eval_report.md，返回 summary。"""
    data = json.loads(EVAL_SET.read_text(encoding="utf-8"))
    rows = []
    for i, item in enumerate(data, 1):
        q, cat = item["question"], item["category"]
        _state.update({"current": i, "total": len(data), "question": q, "stage": "retrieving"})
        if progress_cb:
            progress_cb(i, len(data), q, "retrieving")
        contexts = await retrieve_for(q, cat)
        _state["stage"] = "writing"
        answer = write_answer(q, contexts)
        _state["stage"] = "judging"
        ap = eval_context_precision(q, contexts)
        faith = eval_faithfulness(q, answer, contexts)
        rel = eval_answer_relevancy(q, answer)
        rows.append({
            "question": q, "category": cat,
            "context_titles": [c["title"] for c in contexts],
            "expected": item["expected_titles"],
            "answer": answer,
            "context_precision": round(ap, 3),
            "faithfulness": round(faith, 3),
            "answer_relevancy": round(rel, 3),
        })
        if progress_cb:
            progress_cb(i, len(data), q, "done")

    avg = lambda k: round(sum(r[k] for r in rows) / len(rows), 3)
    summary = {
        "avg_context_precision": avg("context_precision"),
        "avg_faithfulness": avg("faithfulness"),
        "avg_answer_relevancy": avg("answer_relevancy"),
        "n": len(rows),
    }
    EVAL_RESULT.write_text(json.dumps({"summary": summary, "items": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_report(summary, rows)
    return summary


def _write_report(summary: dict, rows: list):
    md = ["# AI 新闻助手 · RAG 评测报告", "",
          "> 评测集：%d 条真实问题（科技/财经/国际）｜judge：DeepSeek｜检索：项目真实链路 top-%d" % (len(rows), TOP_K), "",
          "## 总分", "", "| 指标 | 平均分 | 满分 |", "| --- | --- | --- |",
          "| 上下文精确率 AP@%d | %.3f | 1.0 |" % (TOP_K, summary["avg_context_precision"]),
          "| 忠实度 Faithfulness | %.3f | 1.0 |" % summary["avg_faithfulness"],
          "| 答案相关性 Relevancy | %.3f | 1.0 |" % summary["avg_answer_relevancy"], "",
          "## 逐条明细", "", "| # | 问题 | AP@K | Faith | Rel | top1命中 |", "| --- | --- | --- | --- | --- | --- |"]
    for i, r in enumerate(rows, 1):
        hit = "✅" if r["context_titles"] and any(e in r["context_titles"][0] for e in r["expected"]) else "❌"
        md.append(f"| {i} | {r['question']} | {r['context_precision']} | {r['faithfulness']} | {r['answer_relevancy']} | {hit} |")
    md += ["", "---", "由前端评测界面生成：%s" % time.strftime("%Y-%m-%d %H:%M:%S")]
    EVAL_REPORT.write_text("\n".join(md), encoding="utf-8")


async def start_eval():
    """启动评测任务（幂等：已在跑则拒绝）。"""
    if _state["running"]:
        return {"started": False, "reason": "评测已在运行中"}
    _state.update({"running": True, "current": 0, "total": 0, "question": "",
                   "stage": "starting", "error": "", "started_at": time.time(), "finished_at": 0})

    async def _task():
        try:
            await run_eval()
            _state.update({"running": False, "stage": "done", "finished_at": time.time()})
        except Exception as e:
            _state.update({"running": False, "stage": "error", "error": str(e), "finished_at": time.time()})

    _state["task"] = asyncio.create_task(_task())
    return {"started": True}
