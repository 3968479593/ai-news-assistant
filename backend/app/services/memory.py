"""对话记忆服务：会话内滑动窗口（内存）+ 话题状态锚定 + 跨会话向量记忆（复用 Chroma/BGE-M3）。

- 会话内：按 session_id 在内存保留最近 MAX_HISTORY_TURNS 轮，注入 Agent 时取最近 N 轮。
- 话题状态：每会话维护「当前话题」关键词，追问时检索锚定话题（而非机械拼 3 轮），
  话题切换时自动更新，避免旧话题污染新检索。
- 跨会话：每轮问答（问题+回答摘要）嵌入后存入独立 collection「chat_memory」，
  新问题时语义召回相关旧对话，让 Agent"记得"用户之前讨论过什么。
"""

import datetime as dt
import logging
import re
import uuid

from app.core.embedding import encode_dense_async
from app.core.vector_store import add_to_chroma, query_chroma

logger = logging.getLogger(__name__)

MAX_HISTORY_TURNS = 20      # 每会话内存保留的最大轮数（超出丢弃最旧）
INJECT_HISTORY_TURNS = 8    # 注入 Agent 的最近轮数
MEMORY_TOP_K = 3            # 向量召回旧记忆条数
CHAT_MEMORY_COLLECTION = "chat_memory"

_SESSIONS: dict[str, list[dict]] = {}
_TOPICS: dict[str, str] = {}   # 会话 → 当前话题（检索锚定用）

# 指代特征词：明显追问/指代时，检索锚定当前话题而非另起新话题
_REFERENCE_WORDS = ("对此", "这个", "那个", "它", "它们", "那", "怎么样", "怎么看", "如何", "展开", "继续", "还有吗", "为什么", "分析", "解释", "详细说说")


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def get_history(session_id: str, turns: int = INJECT_HISTORY_TURNS) -> list[dict]:
    """取某会话最近的 turns 轮（user/assistant 交替）。"""
    return list(_SESSIONS.get(session_id, [])[-(turns * 2):])


# ---------------- 话题状态锚定 ----------------

# 句首引导词（去掉后才是话题本体，如「聊聊X」「请问X」）
_TOPIC_LEAD_WORDS = ("帮我", "请问", "你知道", "我想问", "查一下", "介绍一下", "说说", "聊聊", "关于")
# 句尾语气词 / 疑问尾（去掉后才是话题本体）
_TOPIC_TAIL_WORDS = ("怎么样", "如何", "怎么办", "吗", "呢", "吧", "啊")


def _extract_topic(message: str) -> str:
    """从消息提取话题：去句首引导词 + 句尾语气词后，整句（≤60 字）即话题；
    过长时退化为「最长中文段 + 最长字母数字段」。
    中英数字混排的新闻标题（如「一加16通过3C认证」）能整句保留，避免拆散。"""
    if not message or not message.strip():
        return ""
    m = message.strip().strip(" ？！?。，,、：:")
    for w in _TOPIC_LEAD_WORDS:
        if m.startswith(w):
            m = m[len(w):].strip()
            break
    for w in _TOPIC_TAIL_WORDS:
        if m.endswith(w):
            m = m[: -len(w)].strip()
            break
    m = m.strip(" ？！?。，,、：:")
    if not m:
        return message.strip()[:60]
    if len(m) <= 60:
        return m
    cn_parts = re.findall(r"[\u4e00-\u9fff]{2,}", m)
    an_parts = re.findall(r"[A-Za-z0-9]{2,}", m)
    cn = max(cn_parts, key=len) if cn_parts else ""
    an = max(an_parts, key=len) if an_parts else ""
    core = (cn or "") + (an or "")
    return (core or m[:60]).strip()[:60]


def _topic_tokens(text: str) -> set[str]:
    """话题 token 集：中文 2+ 字连续段 + 字母词（滤纯数字），用于判定话题是否重叠。"""
    toks = set(re.findall(r"[\u4e00-\u9fff]{2,}", text or ""))
    toks |= {t for t in re.findall(r"[A-Za-z][A-Za-z0-9]*", text or "") if len(t) >= 2 and not t.isdigit()}
    return toks


def get_topic(session_id: str) -> str:
    return _TOPICS.get(session_id, "")


def update_topic(session_id: str, message: str, history: list[dict]) -> str:
    """更新会话当前话题并返回。

    判定：
    - 首问（无历史）→ 提取新话题。
    - 追问（短句含指代词，或与旧话题 token 有交集）→ 保留旧话题，检索锚定不漂移。
    - 否则 → 提取新话题（话题切换时旧话题不污染新检索）。
    """
    m = (message or "").strip()
    if not m:
        return _TOPICS.get(session_id, "")
    old = _TOPICS.get(session_id, "")
    if not old:
        topic = _extract_topic(m)
        _TOPICS[session_id] = topic
        return topic
    has_prior = any(x.get("role") == "user" for x in history)
    if has_prior:
        # 短句 + 指代词 → 明显追问，保留旧话题
        if len(m) <= 8 and any(w in m for w in _REFERENCE_WORDS):
            return old
        # 与旧话题有词交集 → 同一话题的延续
        if _topic_tokens(m) & _topic_tokens(old):
            return old
    topic = _extract_topic(m)
    _TOPICS[session_id] = topic
    return topic


def format_history(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        role = "用户" if m.get("role") == "user" else "助手"
        content = (m.get("content") or "").strip().replace("\n", " ")[:300]
        if content:
            lines.append(f"{role}：{content}")
    return "\n".join(lines)


async def search_memory(query: str, top_k: int = MEMORY_TOP_K) -> list[str]:
    """语义召回与 query 相关的历史对话（跨会话）。"""
    try:
        probe = (await encode_dense_async([query]))[0]
        res = await query_chroma(probe, top_k=top_k, collection=CHAT_MEMORY_COLLECTION)
        docs = (res.get("documents") or [[]])[0]
        return [d for d in docs if d and d.strip()][:top_k]
    except Exception as e:
        logger.warning("向量记忆检索失败: %s", e)
        return []


async def save_exchange(session_id: str, question: str, answer: str):
    """保存一轮问答：内存历史 + 向量记忆。"""
    now = dt.datetime.now().isoformat(sep=" ", timespec="seconds")
    sess = _SESSIONS.setdefault(session_id, [])
    sess.append({"role": "user", "content": question, "ts": now})
    sess.append({"role": "assistant", "content": answer, "ts": now})
    if len(sess) > MAX_HISTORY_TURNS * 2:
        _SESSIONS[session_id] = sess[-(MAX_HISTORY_TURNS * 2):]

    # 向量记忆（失败不影响主流程）
    try:
        if question.strip() and answer.strip():
            text = f"用户问：{question.strip()[:200]}\n助手答：{answer.strip()[:400]}"
            emb = await encode_dense_async([text])
            ts = dt.datetime.now().timestamp()
            await add_to_chroma(
                ids=[f"mem::{session_id}::{ts:.0f}"],
                embeddings=emb,
                metadatas=[{"session_id": session_id, "ts": ts}],
                documents=[text],
                collection=CHAT_MEMORY_COLLECTION,
            )
    except Exception as e:
        logger.warning("向量记忆保存失败: %s", e)


def reset(session_id: str):
    _SESSIONS.pop(session_id, None)
    _TOPICS.pop(session_id, None)


def load_history(session_id: str, messages: list[dict]):
    """加载历史会话：把持久化消息回灌到运行时历史与话题锚定（继续追问时上下文完整）。"""
    msgs = [m for m in messages if m.get("role") in ("user", "assistant")][-(MAX_HISTORY_TURNS * 2):]
    if msgs:
        _SESSIONS[session_id] = msgs
    first_user = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
    if first_user and not _TOPICS.get(session_id):
        _TOPICS[session_id] = _extract_topic(first_user)
