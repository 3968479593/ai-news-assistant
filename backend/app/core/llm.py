"""LLM 封装：OpenAI 兼容接口（DeepSeek / DashScope / OpenAI），基于 LangChain ChatOpenAI。"""

import logging
from collections.abc import AsyncIterator

from langchain_openai import ChatOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_model = None


def get_chat_model() -> ChatOpenAI:
    """懒加载 ChatOpenAI 单例（OpenAI 兼容，配 DeepSeek 等 base_url 即可）。"""
    global _model
    if _model is None:
        _model = ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_API_BASE,
            temperature=0.3,
            max_retries=settings.LLM_MAX_RETRIES,
            timeout=60,
            max_tokens=1200,  # 限制生成长度，显著加快响应
        )
    return _model


async def stream_chat(messages: list) -> AsyncIterator[str]:
    """流式对话：逐块产出文本增量（SSE 流式输出用）。

    messages 为 langchain 消息列表（SystemMessage / HumanMessage）。
    """
    model = get_chat_model()
    async for chunk in model.astream(messages):
        c = chunk.content
        if isinstance(c, str):
            if c:
                yield c
        elif isinstance(c, list):
            for part in c:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part.get("text") or ""
                    if text:
                        yield text


SYSTEM_PROMPT = (
    "你是 AI 新闻助手，基于检索到的新闻语料回答用户问题。\n"
    "\n"
    "【输出要求】\n"
    "- 用简体中文回答，正式客观，直接给出结论与关键事实。\n"
    "- 每条关键事实末尾用 [1][2] 标注来源序号，引用顺序与【新闻资料】编号一致。\n"
    "- 回答末尾单独输出【参考来源】列表：序号、标题、来源媒体、发布时间、链接。\n"
    "- 只依据【新闻资料】作答；资料不足时明确说'检索到的资料中未找到相关信息'，不要编造。\n"
    "- 【重要】只使用与用户问题直接相关的资料；若资料主题分散（有的跟问题无关），"
    "不要硬凑所有资料，只围绕最相关主题回答，无关资料不要引用、不要展开。\n"
    "- 若资料时间较旧，主动提示'以下信息基于 N 天前的报道，最新进展建议查证'。\n"
    "- 【事实边界】只写上下文/资料中明确提到的细节：未提及的具体日期、法院/机构名、人名职务、数字等一律不得自行补充或推测；资料未覆盖的信息可说明'报道未提及'。\n"
    "- 【新闻解读】当收到「【AI 解读】」指令时：在事实之后追加解读段，基于资料事实做合理推断（可结合常识背景），但不得编造资料外的具体事件/人名/精确数字；解读段与事实层分开，开头必须显式标注'【AI 解读】以下为基于报道的分析推断，非报道原文'。\n"
    "- 若资料明显属于同一领域（如科技/财经/体育），回答开头可点明所属领域，帮助用户定位。\n"
    "- 禁止使用 Markdown 加粗等标记，纯文本输出，每条要点独占一行。\n"
    "\n"
    "【新闻资料】\n"
    "{context}"
)

CHAT_SYSTEM_PROMPT = (
    "你是 AI 新闻助手。用户只是闲聊（问候、感谢、询问能力），简短友好回复即可，"
    "并提示可以问：某话题的最新消息、某事件的来龙去脉、新闻总结对比等。"
)
