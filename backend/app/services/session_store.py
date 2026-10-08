# -*- coding: utf-8 -*-
"""会话持久化存储：历史对话以 JSON 落盘（data/sessions.json），支持列表/加载/保存/删除。

与 memory.py 的关系：
- memory.py：运行时历史（注入 Agent 的最近 N 轮）+ 话题状态锚定（服务内存，重启即丢）。
- 本模块：完整消息的持久化（磁盘），加载历史会话时把消息回灌给 memory 恢复上下文。
"""
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # backend/
SESSIONS_FILE = ROOT / "data" / "sessions.json"

MAX_SESSIONS = 50  # 本地项目上限，超出删最旧


def _load() -> dict:
    if SESSIONS_FILE.exists():
        try:
            return json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(data: dict):
    SESSIONS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _title_of(messages: list[dict]) -> str:
    for m in messages:
        if m.get("role") == "user":
            t = (m.get("content") or "").strip().replace("\n", " ")[:30]
            return t or "新对话"
    return "新对话"


def list_sessions() -> list[dict]:
    """会话列表（按最近更新倒序）：id/title/updated_ts/message_count。"""
    data = _load()
    rows = [
        {
            "id": sid,
            "title": rec.get("title") or _title_of(rec.get("messages", [])),
            "updated_ts": rec.get("updated_ts", 0),
            "message_count": len(rec.get("messages", [])),
        }
        for sid, rec in data.items()
    ]
    rows.sort(key=lambda r: r["updated_ts"], reverse=True)
    return rows


def get_session(session_id: str) -> dict | None:
    rec = _load().get(session_id)
    if not rec:
        return None
    return {"id": session_id, "title": rec.get("title"), "messages": rec.get("messages", [])}


def save_session(session_id: str, messages: list[dict]):
    """覆盖保存整段会话消息（send/regenerate/recall 后调用，保证与前端一致）。"""
    data = _load()
    now = time.time()
    rec = data.get(session_id, {"created_ts": now})
    rec["title"] = _title_of(messages)
    rec["messages"] = messages
    rec["updated_ts"] = now
    data[session_id] = rec
    if len(data) > MAX_SESSIONS:
        for sid in sorted(data, key=lambda s: data[s].get("updated_ts", 0))[: len(data) - MAX_SESSIONS]:
            data.pop(sid, None)
    _save(data)


def delete_session(session_id: str) -> bool:
    data = _load()
    existed = session_id in data
    if existed:
        data.pop(session_id, None)
        _save(data)
    return existed
