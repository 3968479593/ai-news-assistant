# AI 新闻助手（AI News Assistant）

基于 **LangChain / LangGraph** 的 RAG 新闻智能问答系统：定时抓取科技 / 财经 / 国际新闻入库，用户自然语言提问，系统通过 **向量 + BM25 双路检索、多 Agent 编排**，生成**带引用来源**的回答——配有豆包式的对话体验（流式输出 / 深度思考 / 停止 / 撤回 / 历史会话）和**前端可运行的评测闭环**。

## ✨ 特性

| 模块 | 能力 |
| --- | --- |
| 🧠 多 Agent 编排 | LangGraph 状态图：路由(纯规则) → 检索(自主决策补实时) → 写稿(两步化) → 审核(回流防死循环) |
| 🔍 混合检索 | BGE-M3 向量 + BM25 关键词 → RRF 融合 → 时间衰减 → Cross-encoder 精排 → 全局精排 |
| 📰 数据管线 | RSS 异步并发抓取 · 新鲜度闸门(>3天丢弃) · 标题/语义去重 · 主题过滤 · 容量治理(150条/7天) |
| 💬 对话体验 | SSE 流式输出 · 深度思考模式 · 停止生成 · 消息撤回(同步清记忆缓存) · 历史会话持久化续聊 |
| 📊 评测闭环 | RAGAS 风格三指标，DeepSeek 作 judge，**前端一键运行**（忠实度 0.845 / 相关性 0.933 / top1 命中 93%） |
| ⚡ 工程化 | 单端口一体化(后端托管前端) · 双库一致性治理(SQLite+Chroma) · 幂等启动脚本 |

## 🏗️ 架构

```
👤 Vue3 前端（对话页 · 搜索页·热榜 · 新闻库 · 首页评测界面）
   │
   ▼
[FastAPI · 单端口 8000]
   │
[LangGraph 主图]
   ├─ route_node   规则路由：rag / live / chat
   ├─ 检索子图      多路检索（向量+BM25 → RRF → 时间衰减 → 精排）；自主决策补 Tavily 实时
   ├─ write_node   筛素材 → 复杂问题先提纲再成文 → 带 [1][2] 引用
   └─ review_node  规则审核，缺料回流重检索（AGENT_MAX_STEPS 防死循环）
   │
   ▼
ChromaDB（向量） + SQLite（元数据）双写
```

**入库链路**：RSS 异步抓取 → 新鲜度闸门 + 空正文丢弃 → URL/标题/语义去重 → 主题过滤 → BGE-M3 嵌入 → 双写 → 容量治理（7 天 / 150 条硬上限 / 模块配额 / seen_urls 防重抓）

## 📈 评测结果（RAGAS 风格，前端可复跑）

| 指标 | 分数 | 说明 |
| --- | --- | --- |
| Faithfulness 忠实度 | **0.845** | 回答不编造，逐句可追溯上下文 |
| Answer Relevancy | **0.933** | 回答高度切题 |
| Context Precision AP@5 | 0.200 | 数据稀疏（105 条库）所致，top1 命中 93% 为主指标 |
| Top-1 命中率 | **14/15 (93%)** | 最相关新闻稳定排第一 |

## 🚀 快速开始

环境要求：Python 3.11（3.10-3.12 均可）、Node 18+（仅改前端需要）

```bash
# 1. 安装后端依赖
cd backend
pip install -r requirements.txt

# 2. 配置密钥（复制模板并填入）
cp .env.example .env    # LLM_API_KEY(DeepSeek)、TAVILY_API_KEY、TIANAPI_KEY

# 3. 下载本地模型（BGE-M3 + bge-reranker-v2-m3，约 8.7GB）
python scripts/download_models.py

# 4. 初始化数据库（可选：已有数据则跳过）
python scripts/init_db.py

# 5. 启动（项目根目录，单端口一体化）
python run.py            # → http://127.0.0.1:8000 自动打开
# 或双击 start.bat（一键：杀旧进程 → 启动 → 等就绪 → 开浏览器）
```

前端开发模式（热更新）：`cd frontend && npm run dev`（/api 自动代理到 8000）；构建产物由后端同源托管，改前端后 `npm run build` + 重启后端即可。

## 📁 项目结构

```
backend/
├── app/
│   ├── api/routes/       # chat / search / news / sources / settings / eval 路由
│   ├── core/             # embedding · vector_store · retriever · rrf · reranker · agent · news_fetcher
│   ├── models/           # SQLAlchemy ORM + Pydantic schemas
│   ├── services/         # ingestion · memory · retrieval · news_update(定时刷新)
│   └── utils/
├── scripts/              # 运维脚本（下载模型 / 刷新新闻 / 重建索引 / 修复一致性）
└── tests/                # RAGAS 评测集与脚本
frontend/
└── src/views/            # Home(评测) · Chat(对话) · Search(检索+热榜) · News(新闻库)
```

## ⚙️ 关键配置（.env）

| 变量 | 说明 |
| --- | --- |
| `LLM_API_KEY` | DeepSeek（OpenAI 兼容），`USE_REAL_LLM=true` 时生效 |
| `EMBEDDING_MODEL` / `RERANKER_MODEL` | 本地模型路径（离线可跑） |
| `NEWS_SOURCES` | 7 个稳定 RSS 源（量子位/IT之家/钛媒体/雷峰网 + 中新网 财经/国际/全站） |
| `NEWS_MAX_ITEMS` / `NEWS_RETENTION_DAYS` | 容量治理：150 条上限 / 7 天保留 |
| `NEWS_REFRESH_ENABLED` | 每 6 小时自动刷新 |

## 📄 License

MIT
