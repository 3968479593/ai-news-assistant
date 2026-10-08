from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""  # 空则服务端新建会话；传同一 id 保持上下文
    deep_think: bool = False  # 深度思考：先流式输出思考要点，再生成正文
    history: list[dict] = Field(default_factory=list)  # 兼容旧参数，服务端以 session 存储为准


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict] = Field(default_factory=list)
    related: list[dict] = Field(default_factory=list)  # 相关新闻推荐（库内，回答之外）
    route: str = "rag"
    category: str = "综合"
    agent_trace: list[str] = Field(default_factory=list)  # 多 Agent 执行轨迹
    session_id: str = ""  # 会话标识（客户端下次对话沿用）


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)
    category: str = ""  # 模块过滤：""=全部，如"科技"


class SearchResultItem(BaseModel):
    id: int
    title: str
    source: str
    published_at: str
    url: str
    trust_level: int
    category: str = "综合"
    snippet: str
    score: float


class NewsOut(BaseModel):
    id: int
    title: str
    source: str
    published_at: str
    url: str
    trust_level: int
    category: str = "综合"
    chunk_count: int
    status: str
    snippet: str = ""  # 正文摘要（前 180 字），供前端卡片展开阅读


class SourceStatus(BaseModel):
    url: str
    ok: bool
    error: str = ""
    item_count: int = 0
