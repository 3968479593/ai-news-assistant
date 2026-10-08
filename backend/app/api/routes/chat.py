"""💬 AI 对话接口：POST /api/chat -> LangGraph Agent 编排（路由/检索/实时抓取/生成）。
POST /api/chat/stream -> SSE 流式版本（检索阶段发 status，LLM 逐块发 delta）。

带记忆：请求传 session_id 保持会话内上下文；历史存内存、跨会话旧对话存向量库（chat_memory）。
带缓存：库内检索类问题（rag）10 分钟内相同问题直接命中缓存，秒级返回。
"""

import asyncio
import json
import time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.agent import ask, stream_ask
from app.models.schemas import ChatRequest, ChatResponse
from app.services import memory, session_store

router = APIRouter()

# 答案缓存：key=规范化问题 → (时间戳, 结果 dict)。仅缓存 rag 类（实时/live 类不缓存）
_answer_cache: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 600  # 10 分钟

def _build_search_query(message: str, topic: str) -> str:
    """检索锚定：当前话题 + 本轮问题（话题已在问题里则不重复拼接）。

    例："分析一下"（话题=一加16） → "一加16 分析一下"
        "美股最近怎么样"（话题=美股）  → "美股最近怎么样"（话题已在问题内，不重复）
    """
    m = message.strip()
    if not topic or topic in m or m in topic:
        return m
    return f"{topic} {m}"


def _cached_result(q_key: str) -> dict | None:
    cached = _answer_cache.get(q_key)
    if cached and time.time() - cached[0] < CACHE_TTL:
        return cached[1]
    return None


async def _search_memory_fast(message: str) -> str:
    """跨会话向量记忆检索：2 秒超时，失败/超时静默降级为空（不阻塞回答）。"""
    try:
        mem_docs = await asyncio.wait_for(memory.search_memory(message), timeout=2.0)
        return "\n".join(f"- {d}" for d in mem_docs)
    except Exception:
        return ""


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest):
    session_id = req.session_id or memory.new_session_id()
    q_key = req.message.strip().lower()

    # 缓存命中（仅库内检索类问题，跨会话复用；实时类问题不缓存保证时效）
    cached = _cached_result(q_key)
    if cached:
        return ChatResponse(
            answer=cached["answer"],
            sources=cached["sources"],
            related=cached.get("related", []),
            route=cached["route"],
            category=cached.get("category", "综合"),
            agent_trace=cached.get("agent_trace", []),
            session_id=session_id,
        )

    # 1) 会话内历史（最近 N 轮）
    history = memory.get_history(session_id)
    history_text = memory.format_history(history)
    # 2) 跨会话向量记忆（语义召回相关旧对话；2 秒超时，不阻塞回答）
    memory_text = await _search_memory_fast(req.message)
    # 3) 话题状态锚定：更新当前话题 → 检索 query = 话题 + 本轮问题（追问不漂移、切换不污染）
    topic = memory.update_topic(session_id, req.message, history)
    search_query = _build_search_query(req.message, topic)

    result = await ask(req.message, history=history_text, memory=memory_text, search_query=search_query, topic=topic)

    # 3) 保存本轮问答
    await memory.save_exchange(session_id, req.message, result["answer"])

    # 写入缓存（仅库内检索 rag 类缓存；live 实时类不缓存——实时新闻重时效，10 分钟内重复问必须重新抓取）
    if result["answer"] and result["route"] == "rag":
        _answer_cache[q_key] = (time.time(), result)
        if len(_answer_cache) > 200:
            oldest = min(_answer_cache, key=lambda k: _answer_cache[k][0])
            _answer_cache.pop(oldest, None)

    return ChatResponse(
        answer=result["answer"],
        sources=result["sources"],
        related=result.get("related", []),
        route=result["route"],
        category=result.get("category", "综合"),
        agent_trace=result.get("agent_trace", []),
        session_id=session_id,
    )


@router.post("/stream")
async def chat_stream(req: ChatRequest):
    """SSE 流式问答：检索阶段发 status 事件，LLM 生成逐块发 delta 事件，最后发 done。

    缓存命中时一次性输出 done（秒级），不重复检索。
    """
    session_id = req.session_id or memory.new_session_id()
    q_key = req.message.strip().lower()
    cached = _cached_result(q_key)

    def _sse(evt: str, payload: dict) -> str:
        return f"event: {evt}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

    if cached:
        async def gen_cached():
            yield _sse("done", {
                "answer": cached["answer"],
                "sources": cached["sources"],
                "route": cached["route"],
                "category": cached.get("category", "综合"),
                "agent_trace": cached.get("agent_trace", []),
                "question": req.message,
                "session_id": session_id,
            })
        return StreamingResponse(gen_cached(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    async def gen():
        # 会话内历史 + 跨会话向量记忆（与 /api/chat 同口径；记忆检索 2 秒超时不阻塞）
        history = memory.get_history(session_id)
        history_text = memory.format_history(history)
        memory_text = await _search_memory_fast(req.message)
        # 话题状态锚定：更新当前话题 → 检索 query = 话题 + 本轮问题
        topic = memory.update_topic(session_id, req.message, history)
        search_query = _build_search_query(req.message, topic)

        answer, sources, route, category, trace = "", [], "rag", "综合", []
        try:
            async for evt, payload in stream_ask(req.message, history=history_text, memory=memory_text, search_query=search_query, topic=topic, deep_think=req.deep_think):
                if evt == "done":
                    answer = payload.get("answer", "")
                    sources = payload.get("sources", [])
                    route = payload.get("route", "rag")
                    category = payload.get("category", "综合")
                    trace = payload.get("agent_trace", [])
                    yield _sse("done", {**payload, "session_id": session_id})
                else:
                    yield _sse(evt, payload)
            # 保存本轮问答（供记忆/缓存）
            await memory.save_exchange(session_id, req.message, answer)
            # 仅库内检索（rag）类缓存；live 实时类不缓存，保证时效
            if answer and route == "rag":
                _answer_cache[q_key] = (time.time(), {
                    "answer": answer, "sources": sources, "route": route,
                    "category": category, "agent_trace": trace,
                })
                if len(_answer_cache) > 200:
                    oldest = min(_answer_cache, key=lambda k: _answer_cache[k][0])
                    _answer_cache.pop(oldest, None)
        except Exception as e:
            yield _sse("error", {"detail": str(e)})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/history/clear")
async def chat_history_clear(req: ChatRequest):
    """撤回支持：清空该会话的对话历史与话题锚定，并清除答案缓存（撤回后重问同一问题不再秒回旧答案）。"""
    if req.session_id:
        memory.reset(req.session_id)
    _answer_cache.clear()
    return {"ok": True, "cleared": bool(req.session_id)}


@router.get("/history")
async def chat_history_list():
    """历史会话列表（最近更新倒序）：供左侧历史栏渲染。"""
    return {"sessions": session_store.list_sessions()}


@router.get("/history/{session_id}")
async def chat_history_get(session_id: str):
    """加载某个历史会话：返回完整消息，并回灌运行时记忆（继续追问上下文完整）。"""
    rec = session_store.get_session(session_id)
    if not rec:
        return {"ok": False, "error": "会话不存在"}
    memory.load_history(session_id, rec["messages"])
    return {"ok": True, "id": session_id, "title": rec["title"], "messages": rec["messages"]}


@router.post("/history/{session_id}")
async def chat_history_save(session_id: str, payload: dict):
    """覆盖保存整段会话（send/regenerate/recall 后调用，保证历史与前端一致）。"""
    messages = payload.get("messages") or []
    session_store.save_session(session_id, messages)
    memory.load_history(session_id, messages)
    return {"ok": True}


@router.delete("/history/{session_id}")
async def chat_history_delete(session_id: str):
    """删除历史会话（同时清运行时记忆与缓存）。"""
    existed = session_store.delete_session(session_id)
    memory.reset(session_id)
    _answer_cache.clear()
    return {"ok": True, "deleted": existed}
