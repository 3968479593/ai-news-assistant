"""多 Agent 协作编排（LangGraph）：检索 Agent → 写稿 Agent → 审核 Agent（反馈循环）。

架构：
    route（智能路由）→ research（检索 Agent 子图：rag→按需补 live）→ write（写稿 Agent）
        → review（审核 Agent）→ 通过=END / 未通过且轮次未满=回流 research 补充检索 / 达上限=END

- 检索 Agent 是 LangGraph 子图：先库内 RAG（category 模块定向），命中不足或需实时时自主补 live。
- 审核 Agent 用 LLM 判断回答质量（切题/编造/引用/资料充足性），规则兜底保证离线可跑。
- 整个图最多 AGENT_MAX_STEPS 轮（审核回流上限）。
"""

import logging
from collections.abc import AsyncIterator
from typing_extensions import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph

from app.config import settings
from app.core.llm import CHAT_SYSTEM_PROMPT, SYSTEM_PROMPT, get_chat_model, stream_chat
from app.core.news_fetcher import fetch_live
from app.core.retriever import retrieve, retrieve_multi

logger = logging.getLogger(__name__)

# ---------------- Agent 状态 ----------------

class AgentState(TypedDict):
    question: str
    route: str          # rag / live / chat
    category: str       # 领域模块
    docs: list[dict]    # 检索或抓取的新闻（标准化 dict）
    answer: str
    sources: list[dict]
    review_pass: bool   # 审核是否通过
    review_feedback: str  # 审核意见（未通过时的补充检索方向）
    attempt: int        # 当前审核轮次（1-based）
    steps: list[str]    # 执行轨迹（供前端展示）
    history: str        # 会话内历史（滑动窗口，已格式化）
    memory: str         # 跨会话向量记忆（相关旧对话）
    search_query: str   # 指代消解后的检索 query（无指代时为原问题）
    topic: str          # 会话当前话题（写稿只围绕该话题，防止旧话题/无关素材硬凑）


# ---------------- 工具注册（LangChain tool，供检索 Agent 内部调用） ----------------

@tool
async def search_news_rag(query: str, category: str | None = None) -> list[dict]:
    """从新闻知识库（向量 + BM25 + 时间加权）检索与 query 相关的历史新闻，返回带来源的片段。
    可选 category 参数限定检索模块（科技/商业财经/国际/体育/娱乐/健康/生活/综合）。"""
    return await retrieve(
        query,
        top_k=settings.RERANK_TOP_K if settings.RERANK_ENABLED else settings.RETRIEVAL_TOP_K,
        category=category,
    )


@tool
async def fetch_latest_news(query: str) -> list[dict]:
    """实时抓取与 query 相关的最近 3 天新闻（Tavily 优先，RSS 兜底），返回标题/来源/链接。"""
    return await fetch_live(query)


_TOOLS = {"search_news_rag": search_news_rag, "fetch_latest_news": fetch_latest_news}


# ---------------- 路由 ----------------

_LIVE_KEYWORDS = ["最新", "刚刚", "今天", "今日", "现在", "实时", "突发", "进展", "当前", "新消息", "刚发生"]
_CHAT_KEYWORDS = ["你好", "您好", "谢谢", "再见", "你是谁", "介绍一下自己", "能做什么", "帮忙"]


def _rule_route(question: str) -> str:
    q = question.lower()
    if any(k in q for k in _CHAT_KEYWORDS):
        return "chat"
    if any(k in q for k in _LIVE_KEYWORDS):
        return "live"
    return "rag"


def _question_category(question: str) -> str:
    """按关键词给用户问题判领域模块（命中 1 词即采信，0 命中回综合）。"""
    from app.core.categorizer import KEYWORD_CATEGORY_MAP
    if not question:
        return "综合"
    best, best_hits = "综合", 0
    q = question.lower()
    for cat, words in KEYWORD_CATEGORY_MAP.items():
        hits = sum(1 for w in words if w.lower() in q)
        if hits > best_hits:
            best, best_hits = cat, hits
    return best


def _valid_category(category: str) -> str:
    from app.core.categorizer import is_valid_category
    return category if is_valid_category(category) else "综合"


def route_node(state: AgentState) -> dict:
    """智能路由：纯规则判定（速度快，不调 LLM）。
    chat/live 关键词命中即走对应分支；领域用模块关键词打分。
    """
    question = state["question"]
    route = _rule_route(question)
    category = _question_category(question)
    logger.info("路由(规则): %s/%s <- %s", route, category, question)
    return {"route": route, "category": category, "steps": [f"路由: 判定为{route}，领域={category}"]}


# ---------------- 检索 Agent（子图：rag → 按需 live） ----------------

async def rag_node(state: AgentState) -> dict:
    query = state.get("search_query") or state["question"]
    category = state.get("category") or None
    # top_k=8：前 5 条用于引用回答，后 3 条留作「相关新闻推荐」
    docs = await retrieve_multi(query, top_k=8, category=category)
    steps = list(state.get("steps") or [])
    steps.append(f"检索Agent: 库内检索(领域={category or '全部'}) 命中{len(docs)}条")
    logger.info("检索Agent·rag 命中 %d 条（领域: %s）", len(docs), category)
    return {"docs": docs, "steps": steps}


async def live_node(state: AgentState) -> dict:
    query = state.get("search_query") or state["question"]
    docs = await fetch_live(query)
    # 与已有库内结果合并去重（按 URL）
    merged = list(state.get("docs") or [])
    seen = {d.get("url") for d in merged}
    for d in docs:
        if d.get("url") not in seen:
            merged.append(d)
            seen.add(d.get("url"))
    steps = list(state.get("steps") or [])
    steps.append(f"检索Agent: 实时抓取 补充{len(merged) - len(state.get('docs') or [])}条")
    logger.info("检索Agent·live 命中 %d 条", len(docs))
    return {"docs": merged, "steps": steps}


def _should_live(state: AgentState) -> str:
    """检索 Agent 自主决策：什么情况需要补实时抓取。"""
    # 首轮就是 live 诉求（问"最新/今天"）→ 补
    if state.get("route") == "live":
        return "yes"
    # 库内没查到 → 补
    if not (state.get("docs") or []):
        return "yes"
    # 审核回流要求补实时（feedback 含相关意图）
    feedback = (state.get("review_feedback") or "").lower()
    if state.get("attempt", 0) >= 1 and any(k in feedback for k in ["实时", "最新", "补充", "live"]):
        return "yes"
    return "no"


def _build_research_agent():
    g = StateGraph(AgentState)
    g.add_node("rag", rag_node)
    g.add_node("live", live_node)
    g.add_edge(START, "rag")
    g.add_conditional_edges("rag", _should_live, {"yes": "live", "no": END})
    g.add_edge("live", END)
    return g.compile()


# ---------------- 写稿 Agent ----------------

def _filter_relevant(docs: list[dict], min_sim: float) -> tuple[list[dict], int]:
    """写稿前筛素材：纯向量相似度低于阈值的视为与问题不相关，不进 context。
    无 vector_sim 的（实时抓取补充的）一律保留；全被筛空时返回原列表兜底避免空答。"""
    if not min_sim:
        return docs, 0
    kept = [d for d in docs if d.get("vector_sim") is None or d.get("vector_sim", 0.0) >= min_sim]
    dropped = len(docs) - len(kept)
    if dropped and not kept:
        return docs, 0
    return kept, dropped


def _template_answer(question: str, docs: list[dict]) -> str:
    lines = [f"关于「{question}」，检索到以下相关新闻（演示模式，未调用 LLM）：", ""]
    for i, d in enumerate(docs[:5], 1):
        lines.append(f"[{i}] {d['title']}")
        lines.append(f"    来源：{d['source']} | 时间：{d['published_at']}")
        lines.append(f"    链接：{d['url']}")
        snippet = (d.get("snippet") or d.get("content") or "")[:120]
        if snippet:
            lines.append(f"    摘要：{snippet}...")
        lines.append("")
    lines.append("提示：在 backend/.env 配置 LLM_API_KEY 并设 USE_REAL_LLM=true，即可获得带引用的完整回答。")
    return "\n".join(lines)


# ---------------- 写稿两步化（先列提纲再成文） ----------------

_OUTLINE_STEP_PROMPT = (
    "\n\n【写作步骤 1/2】请先输出回答提纲：3-6 个要点，每点一行，格式「N. [引用序号] 要点内容」。"
    "提纲要覆盖问题核心，引用序号必须来自上方资料。只输出提纲本身，不要展开正文。"
)
_WRITE_STEP_PROMPT = (
    "\n\n【写作步骤 2/2】请严格按以下提纲展开成文，逐点覆盖、不要遗漏，正文连贯自然：\n{outline}\n"
    "【写作要求】先给结论再展开，引用用 [序号] 标注，不编造资料里没有的事实。"
)


_ANALYSIS_WORDS = ("影响", "意义", "前景", "原因", "为什么", "怎么看", "怎么看待", "解读", "意味着", "说明什么", "风险", "值不值得", "价值", "趋势", "预示", "受益", "分析")


def _needs_analysis(question: str) -> bool:
    """问题含分析意图时，回答追加「AI 解读」层（基于事实的推断，显式标注不冒充报道）。"""
    q = question.strip()
    return any(w in q for w in _ANALYSIS_WORDS)


def _build_write_prompt(context: str, topic: str, history: str, memory: str, analysis: bool = False) -> str:
    """公共写稿 prompt：资料 + 当前话题 + 会话历史 + 长期记忆 + 分析意图。"""
    prompt = SYSTEM_PROMPT.format(context=context)
    if analysis:
        prompt += "\n\n【用户期望深度解读】用户的问题含分析意图（影响/意义/原因/前景等）。请在回答完可证实的事实后，追加一段「【AI 解读】」：基于上述资料事实做合理推断与影响分析（可结合行业规律、政策逻辑等常识背景展开），但不得编造资料外的具体事件、人名或精确数字；解读段必须与事实层分开，并显式标注'以下为基于报道的分析推断，非报道原文'。"
    if topic.strip():
        prompt += "\n\n【当前话题】用户正在围绕「" + topic.strip() + "」对话。请只围绕该话题展开回答：与话题相关的资料优先引用；明显无关的素材不要硬凑，直接说明未找到相关信息。"
    if history:
        prompt += "\n\n【对话历史】（用户之前问过，回答时保持连贯，可回应指代）\n" + history
    if memory:
        prompt += "\n\n【与用户的长期记忆】（用户之前讨论过的相关话题，可自然引用）\n" + memory
    return prompt


def _needs_outline(docs: list, question: str) -> bool:
    """复杂场景才走两步：资料 >= 4 条 + 问题较长 + 含复杂意图词。
    简单提问（如「苹果发了什么新品」）即使实时补充到 4+ 条也不走两步，保住速度。"""
    q = question.strip()
    if len(docs) < 4 or len(q) < 12:
        return False
    return any(w in q for w in ("总结", "分析", "对比", "梳理", "盘点", "综述", "影响", "原因", "为什么", "怎么", "详细", "进展", "介绍"))


def _try_outline(base_prompt: str, question: str) -> str:
    """第一步：让 LLM 先列提纲。失败/空提纲返回 ""，调用方回退单次写稿。"""
    try:
        resp = get_chat_model().invoke([
            SystemMessage(content=base_prompt + _OUTLINE_STEP_PROMPT),
            HumanMessage(content=question),
        ])
        outline = (resp.content or "").strip()
        return outline if outline else ""
    except Exception as e:
        logger.warning("提纲生成失败，回退单次写稿: %s", e)
        return ""


async def _stream_outline(base_prompt: str, question: str) -> AsyncIterator[str]:
    """深度思考：流式列思考要点（约 2-4 行），供前端逐字展示。"""
    async for delta in stream_chat([
        SystemMessage(content=base_prompt + _OUTLINE_STEP_PROMPT),
        HumanMessage(content=question),
    ]):
        yield delta


async def write_node(state: AgentState) -> dict:
    question, docs = state["question"], state.get("docs") or []
    steps = list(state.get("steps") or [])

    # 资料为空
    if not docs:
        steps.append("写稿Agent: 无可用资料，输出缺料提示")
        return {
            "answer": "检索到的新闻资料中未找到相关信息，可换个问法，或问『XX 最新消息』触发实时抓取。",
            "sources": [],
            "steps": steps,
        }

    kept, dropped = _filter_relevant(docs, settings.CONTEXT_MIN_SIMILARITY)
    if dropped:
        steps.append(f"写稿Agent: 筛掉{dropped}条不相关素材，保留{len(kept)}条")
    docs = kept
    sources = docs[:5]

    # LLM 模式：带引用生成
    if settings.USE_REAL_LLM and settings.LLM_API_KEY:
        try:
            # 正文截断到 500 字/条：控制 prompt 长度，显著降低 LLM 首 token 延迟
            # 引用取 top-5（评测显示 top-8 中后 3 条弱相关噪声多，收敛更聚焦）
            context = "\n\n".join(
                f"[{i}] 标题：{d['title']}\n来源：{d['source']} | 时间：{d['published_at']}\n链接：{d.get('url', '')}\n{(d.get('content') or d.get('snippet') or '')[:500]}"
                for i, d in enumerate(docs[:5], 1)
            )
            prompt = _build_write_prompt(
                context,
                state.get("topic") or "",
                state.get("history") or "",
                state.get("memory") or "",
                _needs_analysis(question),
            )
            # 复杂场景两步化：先列提纲再成文（提纲失败回退单次，不影响可用性）
            if _needs_outline(docs, question):
                outline = _try_outline(prompt, question)
                if outline:
                    prompt += _WRITE_STEP_PROMPT.format(outline=outline)
                    steps.append(f"写稿Agent: 先列提纲（{len(docs)}条资料）再成文")
            resp = get_chat_model().invoke([
                SystemMessage(content=prompt),
                HumanMessage(content=question),
            ])
            steps.append(f"写稿Agent: 基于{len(docs)}条资料生成带引用回答")
            return {"answer": resp.content, "sources": sources, "steps": steps}
        except Exception as e:
            logger.warning("LLM 生成失败，走模板兜底: %s", e)

    steps.append(f"写稿Agent: 模板模式生成回答（{len(docs)}条资料）")
    return {"answer": _template_answer(question, docs), "sources": sources, "steps": steps}


# ---------------- 审核 Agent ----------------

_REVIEW_PROMPT = (
    "你是新闻回答审核员。检查 AI 的回答是否合格，从四个维度：\n"
    "1) 切题：是否回答了用户问题；\n"
    "2) 编造：是否出现资料正文完全未提及、且无法由资料推断的内容。\n"
    "   注意：资料正文明确写到的数据、细节、时间等一律不算编造，不得因资料简短而苛责；\n"
    "3) 引用：[1][2] 标注是否对应资料编号（编号与【资料】一致）；\n"
    "4) 资料充足：资料是否明显不足以支撑回答。\n"
    "只输出一行 JSON：{\"pass\": true, \"feedback\": \"一句话意见\"}。\n"
    "若资料不足，feedback 里说明需要补充的方向（如：实时/某领域）。"
)


def _rule_review(state: AgentState) -> dict:
    """规则审核（快速，不调 LLM）：只查硬伤——无资料、空回答。

    注意：不能凭回答中"未找到相关信息"字样判缺料——docs 非空时那只是 LLM
    对资料相关度的表达，误判会导致无意义的检索-生成回流死循环（曾实测 5 轮 91s）。
    只要资料非空且回答了问题（非空字符串）即通过。
    """
    answer = state.get("answer") or ""
    docs = state.get("docs") or []
    attempt = state.get("attempt", 0) + 1
    if not docs or not answer.strip():
        return {
            "review_pass": False,
            "review_feedback": "资料不足，请补充检索（实时/更广泛领域）",
            "attempt": attempt,
        }
    return {"review_pass": True, "review_feedback": "", "attempt": attempt}


async def review_node(state: AgentState) -> dict:
    question, answer = state["question"], state.get("answer") or ""
    docs = state.get("docs") or []
    attempt = state.get("attempt", 0) + 1

    # 达审核轮次上限：强制通过并结束（避免死循环），附说明
    if attempt >= settings.AGENT_MAX_STEPS:
        steps = list(state.get("steps") or [])
        steps.append(f"审核Agent: 第{attempt}轮达上限，直接结束")
        return {
            "review_pass": True,
            "review_feedback": f"已达最大轮次({settings.AGENT_MAX_STEPS})，当前回答为准",
            "attempt": attempt,
            "steps": steps,
        }

    # 规则快速审核（不调 LLM，保证回答速度）；资料充足且回答正常即通过
    return _rule_review(state)


def _after_review(state: AgentState) -> str:
    if state.get("review_pass"):
        return "accept"
    if state.get("attempt", 0) < settings.AGENT_MAX_STEPS:
        return "retry"
    return "give_up"


# ---------------- 闲聊节点 ----------------

async def chat_node(state: AgentState) -> dict:
    question = state["question"]
    steps = list(state.get("steps") or [])
    if settings.USE_REAL_LLM and settings.LLM_API_KEY:
        try:
            system = CHAT_SYSTEM_PROMPT
            history = state.get("history") or ""
            if history:
                system += "\n\n【对话历史】保持连贯：\n" + history
            resp = get_chat_model().invoke([
                SystemMessage(content=system),
                HumanMessage(content=question),
            ])
            steps.append("闲聊Agent: 直接回复")
            return {"answer": resp.content, "sources": [], "steps": steps}
        except Exception as e:
            logger.warning("LLM 闲聊失败，走模板: %s", e)
    return {
        "answer": "我是 AI 新闻助手，可以帮你：\n- 查某话题的来龙去脉（如『马斯克星舰进展』）\n- 问最新消息（如『今天有什么科技大新闻』）\n- 对几则新闻做总结对比",
        "sources": [],
        "steps": steps + ["闲聊Agent: 模板回复"],
    }


# ---------------- 主图 ----------------

def _route_mapper(state: AgentState) -> str:
    return state["route"]


def build_graph():
    research_agent = _build_research_agent()

    graph = StateGraph(AgentState)
    graph.add_node("route", route_node)
    graph.add_node("research", research_agent)
    graph.add_node("write", write_node)
    graph.add_node("review", review_node)
    graph.add_node("chat", chat_node)

    graph.add_edge(START, "route")
    graph.add_conditional_edges(
        "route",
        _route_mapper,
        {"rag": "research", "live": "research", "chat": "chat"},
    )
    graph.add_edge("chat", END)
    graph.add_edge("research", "write")
    graph.add_edge("write", "review")
    graph.add_conditional_edges(
        "review",
        _after_review,
        {"accept": END, "retry": "research", "give_up": END},
    )
    return graph.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


async def ask(question: str, history: str = "", memory: str = "", search_query: str | None = None, topic: str = "") -> dict:
    """Agent 入口：返回 {answer, sources, route, category, agent_trace, question}。

    search_query：指代消解后的检索 query（无指代时传 None，用原问题检索）。
    topic：会话当前话题（写稿只围绕该话题，防止无关素材硬凑）。
    """
    result = await get_graph().ainvoke({
        "question": question,
        "steps": [],
        "attempt": 0,
        "history": history,
        "memory": memory,
        "search_query": search_query or question,
        "topic": topic,
    })
    # 达上限结束时的补充说明
    if result.get("review_feedback") and "已达最大轮次" in result.get("review_feedback", ""):
        answer = result.get("answer", "")
        result["answer"] = answer + "\n\n（审核提示：已达最大轮次，资料可能仍不足，建议追问最新消息）"
    # 相关新闻推荐：复用检索结果中未进入引用区（前 5 条）的条目
    related: list[dict] = []
    if result.get("route") == "rag":
        related = [
            {"title": d.get("title", ""), "url": d.get("url", ""), "source": d.get("source", ""), "published_at": str(d.get("published_at", ""))}
            for d in (result.get("docs") or [])[5:8]
        ]
    return {
        "answer": result.get("answer", ""),
        "sources": result.get("sources", []),
        "related": related,
        "route": result.get("route", "rag"),
        "category": result.get("category", "综合"),
        "agent_trace": result.get("steps", []),
        "question": question,
    }


# ---------------- 流式问答（SSE 用） ----------------

async def stream_ask(question: str, history: str = "", memory: str = "", search_query: str | None = None, topic: str = "", deep_think: bool = False) -> AsyncIterator[tuple[str, dict]]:
    """流式问答：复用与主图相同的路由/检索/生成逻辑，但 LLM 部分逐块产出。

    search_query：指代消解后的检索 query（无指代时传 None，用原问题检索）。
    topic：会话当前话题（写稿只围绕该话题，防止无关素材硬凑）。
    deep_think：深度思考模式，先流式列思考要点（thinking_start/delta/end 事件），再流式成文。
    产出事件：
      ("status", {"stage": "retrieving"|"writing", "detail": str})
      ("thinking_start", {})
      ("thinking_delta", {"text": str})          # 思考要点增量
      ("thinking_end",  {"outline": str})        # 思考完成，outline 供前端保留
      ("delta",  {"text": str})                  # 正文文本增量
      ("done",   {answer, sources, route, category, agent_trace, question})
    """
    route = _rule_route(question)
    category = _question_category(question)
    query = search_query or question
    steps = [f"路由: 判定为{route}，领域={category}"]
    answer, sources, related = "", [], []

    if route == "chat":
        yield ("status", {"stage": "writing", "detail": "正在回复…"})
        system = CHAT_SYSTEM_PROMPT
        if history:
            system += "\n\n【对话历史】保持连贯：\n" + history
        full: list[str] = []
        if settings.USE_REAL_LLM and settings.LLM_API_KEY:
            try:
                async for delta in stream_chat([
                    SystemMessage(content=system),
                    HumanMessage(content=question),
                ]):
                    full.append(delta)
                    yield ("delta", {"text": delta})
            except Exception as e:
                logger.warning("LLM 闲聊失败，走模板: %s", e)
        if not full:
            full.append(
                "我是 AI 新闻助手，可以帮你：\n- 查某话题的来龙去脉（如『马斯克星舰进展』）\n"
                "- 问最新消息（如『今天有什么科技大新闻』）\n- 对几则新闻做总结对比"
            )
            yield ("delta", {"text": full[0]})
        answer = "".join(full)
        steps.append("闲聊Agent: 直接回复")
    else:
        # ---- 检索 Agent（rag → 按需 live，与主图同决策） ----
        yield ("status", {"stage": "retrieving", "detail": "正在检索新闻库…"})
        # top_k=8：前 5 条用于引用回答，后 3 条留作「相关新闻推荐」
        docs = await retrieve_multi(query, top_k=8, category=_valid_category(category))
        steps.append(f"检索Agent: 库内检索(领域={_valid_category(category) or '全部'}) 命中{len(docs)}条")
        if not docs or route == "live":
            yield ("status", {"stage": "retrieving", "detail": "正在补充实时新闻…"})
            live_docs = await fetch_live(query)
            merged = list(docs)
            seen = {d.get("url") for d in merged}
            for d in live_docs:
                if d.get("url") not in seen:
                    merged.append(d)
                    seen.add(d.get("url"))
            steps.append(f"检索Agent: 实时抓取 补充{len(merged) - len(docs)}条")
            docs = merged

        if not docs:
            answer = "检索到的新闻资料中未找到相关信息，可换个问法，或问『XX 最新消息』触发实时抓取。"
            steps.append("写稿Agent: 无可用资料，输出缺料提示")
        else:
            kept, dropped = _filter_relevant(docs, settings.CONTEXT_MIN_SIMILARITY)
            if dropped:
                steps.append(f"写稿Agent: 筛掉{dropped}条不相关素材，保留{len(kept)}条")
            docs = kept
            sources = docs[:5]
            # 相关新闻推荐：复用本次检索结果中未进入引用区的条目（零额外耗时）
            related = [
                {"title": d.get("title", ""), "url": d.get("url", ""), "source": d.get("source", ""), "published_at": str(d.get("published_at", ""))}
                for d in docs[5:8]
            ]
            # 正文截断到 500 字/条：控制 prompt 长度，降低 LLM 首 token 延迟
            # 引用取 top-5：评测显示 top-8 中后 3 条弱相关噪声多，收敛到 5 条回答更聚焦
            context = "\n\n".join(
                f"[{i}] 标题：{d['title']}\n来源：{d['source']} | 时间：{d['published_at']}\n链接：{d.get('url', '')}\n{(d.get('content') or d.get('snippet') or '')[:500]}"
                for i, d in enumerate(docs[:5], 1)
            )
            prompt = _build_write_prompt(context, topic, history, memory, _needs_analysis(question))

            full: list[str] = []
            if settings.USE_REAL_LLM and settings.LLM_API_KEY:
                try:
                    # 深度思考：先流式列思考要点，再基于要点流式成文
                    if deep_think:
                        yield ("thinking_start", {})
                        outline_parts: list[str] = []
                        try:
                            async for d in _stream_outline(prompt, question):
                                outline_parts.append(d)
                                yield ("thinking_delta", {"text": d})
                            outline = "".join(outline_parts).strip()
                        except Exception as e:
                            logger.warning("深度思考失败，回退直接成文: %s", e)
                            outline = ""
                        if outline:
                            prompt += _WRITE_STEP_PROMPT.format(outline=outline)
                            steps.append("写稿Agent: 深度思考列要点后成文")
                        yield ("thinking_end", {"outline": outline})
                        yield ("status", {"stage": "writing", "detail": "正在生成回答…"})
                        async for delta in stream_chat([
                            SystemMessage(content=prompt),
                            HumanMessage(content=question),
                        ]):
                            full.append(delta)
                            yield ("delta", {"text": delta})
                    else:
                        # 复杂场景两步化：先列提纲（非流式、约 1-2s），再流式成文；简单问题直接单次
                        if _needs_outline(docs, question):
                            yield ("status", {"stage": "writing", "detail": "正在组织回答思路…"})
                            outline = _try_outline(prompt, question)
                            if outline:
                                prompt += _WRITE_STEP_PROMPT.format(outline=outline)
                                steps.append("写稿Agent: 先列提纲再流式成文")
                        yield ("status", {"stage": "writing", "detail": "正在生成回答…"})
                        async for delta in stream_chat([
                            SystemMessage(content=prompt),
                            HumanMessage(content=question),
                        ]):
                            full.append(delta)
                            yield ("delta", {"text": delta})
                except Exception as e:
                    logger.warning("LLM 生成失败，走模板兜底: %s", e)
            if not full:
                answer = _template_answer(question, docs)
                yield ("delta", {"text": answer})
            else:
                answer = "".join(full)
            steps.append(f"写稿Agent: 基于{len(docs)}条资料生成带引用回答")

    yield ("done", {
        "answer": answer,
        "sources": sources,
        "related": related,
        "route": route,
        "category": category,
        "agent_trace": steps,
        "question": question,
    })
