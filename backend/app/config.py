from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "AI新闻助手"
    DEBUG: bool = True

    # 数据库（SQLite 零配置；格式同 ai电商选品助手 的 database.py）
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/news.db"

    # 向量库
    CHROMA_PERSIST_DIR: str = "./data/chroma_db"
    CHROMA_COLLECTION: str = "news_dense"

    # 本地模型（相对 backend/ 工作目录，或用绝对路径复用已有模型）
    MODEL_CACHE_DIR: str = "./models"
    HF_ENDPOINT: str = ""
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DEVICE: str = "cpu"
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"
    RERANK_ENABLED: bool = True

    # LLM（OpenAI 兼容接口，如 DeepSeek / DashScope / OpenAI）
    LLM_API_BASE: str = "https://api.deepseek.com/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "deepseek-chat"
    LLM_MAX_RETRIES: int = 3
    LLM_RETRY_BACKOFF: float = 2.0  # 指数退避基数（秒）

    # 检索参数
    RETRIEVAL_TOP_K: int = 20  # 向量召回候选数
    RERANK_TOP_K: int = 5      # 精排后保留条数
    BM25_TOP_K: int = 20       # BM25 召回候选数
    RRF_K: int = 60            # RRF 融合常数
    TIME_DECAY: float = 0.2    # 时间衰减系数：分 / (1 + TIME_DECAY * 距今天数)
    MAX_NEWS_AGE_DAYS: int = 180  # 超过该天数的新闻不参与检索
    # 向量相似度下限：仅被向量召回、且相似度低于该值（且无 BM25 词重叠）的结果会被剔除
    MIN_VECTOR_SIMILARITY: float = 0.5

    # 新闻源（4 个稳定源，实测多轮出产；36氪/联合早报/BBC/少数派等超时源已剔除）
    NEWS_SOURCES: list[str] = [
        "https://www.qbitai.com/feed",     # 量子位（AI）
        "https://www.ithome.com/rss/",     # IT之家（科技）
        "https://www.tmtpost.com/rss",     # 钛媒体（科技/商业）
        "https://www.leiphone.com/feed",   # 雷锋网（AI/科技）
    ]
    NEWS_FETCH_TIMEOUT: int = 10

    # 模块（分类）体系：主要模块 + 综合兜底
    NEWS_CATEGORIES: list[str] = ["科技", "商业财经", "国际", "体育", "娱乐", "健康", "生活", "综合"]
    # 入库主题过滤白名单：非空时只收标题/正文命中任一关键词的新闻（逗号分隔，运行时可用接口覆盖）
    INGEST_KEYWORDS: list[str] = []
    # 语义去重阈值：入库时新新闻与库内已有新闻的向量相似度 >= 该值则跳过（跨源改写/转载）
    SEMANTIC_DEDUP_THRESHOLD: float = 0.90
    # 写稿前筛素材：与问题纯向量相似度低于此值的素材视为不相关，不进 context（0=不筛）
    CONTEXT_MIN_SIMILARITY: float = 0.45

    # Tavily 实时搜索（可选，兜底"最新消息"类问题）
    TAVILY_API_KEY: str = ""

    # 天聚数行（今日头条热榜）——搜索页热点榜主数据源
    TIANAPI_KEY: str = ""

    # Agent
    USE_REAL_LLM: bool = True  # false = 规则路由 + 模板生成（无需 API Key 可离线演示）
    AGENT_MAX_STEPS: int = 2   # 审核回流上限：最多补 1 轮检索（5 轮实测会让回答时间 15s→90s）

    # 定时新闻刷新
    NEWS_REFRESH_ENABLED: bool = False
    NEWS_REFRESH_INTERVAL_HOURS: int = 6

    # 新闻库容量治理（更新机制）：过期淘汰 + 总量上限
    NEWS_RETENTION_DAYS: int = 7        # 超过 N 天的新闻自动删除（时效性优先）
    NEWS_MAX_ITEMS: int = 150           # 库内保留上限（各模块配额之和；cleanup 时强制兜底）
    NEWS_MODULE_QUOTA: dict[str, int] = {
        "科技": 60,
        "商业财经": 25,
        "国际": 20,
        "综合": 10,
        "体育": 0,
        "娱乐": 0,
        "健康": 0,
        "生活": 0,
    }  # 每模块保留配额；前端已隐藏无源的体育/娱乐/健康/生活，配额置 0 防占库；未列模块默认 10

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
