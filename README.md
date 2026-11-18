# AI 新闻助手（AI News Assistant）

基于 **LangChain / LangGraph** 的 RAG 新闻问答系统：定时抓取科技 / 财经 / 国际新闻入库，用户用自然语言提问，系统经**向量 + BM25 双路检索、多 Agent 编排**生成**带引用来源**的回答。

前端提供类豆包式的对话体验（流式输出 / 深度思考 / 停止 / 撤回 / 历史会话），并内置**可一键复跑的评测闭环**。

## 特性

| 模块 | 能力 |
| --- | --- |
| 多 Agent 编排 | LangGraph 状态图：规则路由（`rag` / `live` / `chat`）→ 检索子图（自主决策是否补 Tavily 实时）→ 写稿节点（复杂问题先出提纲再成文）→ 规则审核（缺料回流重检索，`AGENT_MAX_STEPS` 防死循环） |
| 混合检索 | BGE-M3 向量 + BM25 关键词 → RRF 融合 → 时间衰减 → Cross-encoder 精排 → 全局精排，回答附 `[1][2]` 引用 |
| 数据管线 | RSS 异步并发抓取 · 新鲜度闸门（超过 3 天丢弃）· URL / 标题 / 语义三重去重 · 主题分类过滤 · 容量治理（150 条上限 / 7 天保留 / 模块配额 / `seen_urls` 防重抓） |
| 对话体验 | SSE 流式输出 · 深度思考模式 · 停止生成 · 消息撤回（同步清理记忆缓存）· 历史会话持久化续聊 |
| 评测闭环 | RAGAS 风格三指标，DeepSeek 作 judge，**前端一键运行**（忠实度 0.845 / 相关性 0.933 / top1 命中 93%） |
| 工程化 | 单端口一体化（后端同源托管前端）· SQLite + Chroma 双库一致性治理（含孤儿修复脚本）· 幂等启停脚本 · 依赖版本锁定（`requirements.lock.txt`）· CORS 白名单化 + 调试开关默认关闭 |

## 架构

```
👤 Vue3 前端（Chat 对话 · Search 检索+热榜 · News 新闻库 · Home 评测）
   │
   ▼
[FastAPI · 单端口 8000]
   │
[LangGraph 主图]
   ├─ route_node    规则路由：rag / live / chat
   ├─ 检索子图       多路检索（向量 + BM25 → RRF → 时间衰减 → 精排）
   │                自主决策是否补 Tavily 实时
   ├─ write_node    筛素材 → 复杂问题先提纲再成文 → 带 [1][2] 引用
   └─ review_node   规则审核，缺料回流重检索（AGENT_MAX_STEPS 防死循环）
   │
   ▼
ChromaDB（向量） + SQLite（元数据）双写
```

**入库链路**：RSS 异步抓取 → 新鲜度闸门 + 空正文丢弃 → URL / 标题 / 语义去重 → 主题分类过滤 → BGE-M3 嵌入 → 双写入库 → 容量治理（7 天 / 150 条硬上限 / 模块配额 / `seen_urls` 防重抓）。

## 评测结果

RAGAS 风格，DeepSeek 作 judge，可在前端「评测」页一键复跑：

| 指标 | 分数 | 说明 |
| --- | --- | --- |
| Faithfulness 忠实度 | **0.845** | 回答不编造，逐句可追溯上下文 |
| Answer Relevancy 相关性 | **0.933** | 回答高度切题 |
| Context Precision AP@5 | 0.200 | 受限于数据稀疏（105 条库），以 top1 命中为主要观察指标 |
| Top-1 命中率 | **14/15（93%）** | 最相关新闻稳定排在第一位 |

## 快速开始

环境要求：Python 3.11（3.10–3.12 均可）、Node 18+（仅修改前端时需要）。

```bash
# 1. 安装后端依赖（锁定版本）
cd backend
pip install -r requirements.txt        # 或 requirements.lock.txt 复现精确版本

# 2. 配置密钥：复制模板并填入
cp .env.example .env                   # LLM_API_KEY(DeepSeek)、TAVILY_API_KEY、TIANAPI_KEY

# 3. 下载本地模型（BGE-M3 + bge-reranker-v2-m3，约 8.7 GB）
python scripts/download_models.py

# 4. 初始化数据库（已有数据则跳过）
python scripts/init_db.py

# 5. 启动（回到项目根目录，单端口一体化）
cd ..
python run.py                          # → http://127.0.0.1:8000，自动打开浏览器
```

也可以直接双击 `start.bat`：一键完成「清理旧进程 → 启动 → 等待就绪 → 打开浏览器」，重复执行不会残留进程（`stop.bat` 用于停止，`refresh.bat` 用于刷新新闻）。

前端开发模式（热更新）：

```bash
cd frontend
npm run dev      # /api 自动代理到 8000
```

构建产物由后端同源托管，改完前端执行 `npm run build` 后重启后端即可。

## 项目结构

```
backend/
├── app/
│   ├── api/routes/        # chat · search · news · sources · settings · eval
│   ├── core/              # agent(LangGraph 主图) · retriever · rrf · reranker
│   │                      # embedding · llm · vector_store · news_fetcher · categorizer
│   ├── models/            # SQLAlchemy ORM + Pydantic schemas
│   ├── services/          # ingestion · memory · retrieval · news_update(定时刷新)
│   └── utils/
├── scripts/               # download_models · init_db · fetch_news · refresh_news
│                          # rebuild_chroma · fix_orphans · reclassify_news
│                          # offline_ingest · reset_rebuild · tag_sample
└── tests/                 # RAGAS 评测集与脚本
frontend/
└── src/views/             # Chat(对话) · Search(检索+热榜) · News(新闻库) · Home(评测)
```

根目录：`run.py`（单端口启动）、`start.bat` / `stop.bat` / `refresh.bat`（Windows 一键脚本）。

## 关键配置（`.env`）

| 变量 | 说明 |
| --- | --- |
| `LLM_API_KEY` | DeepSeek（OpenAI 兼容接口），`USE_REAL_LLM=true` 时生效 |
| `EMBEDDING_MODEL` / `RERANKER_MODEL` | 本地模型路径，离线即可运行 |
| `NEWS_SOURCES` | 7 个稳定 RSS 源（量子位 / IT之家 / 钛媒体 / 雷峰网 + 中新网财经 / 国际 / 全站） |
| `NEWS_MAX_ITEMS` / `NEWS_RETENTION_DAYS` | 容量治理：150 条上限 / 7 天保留 |
| `NEWS_REFRESH_ENABLED` | 每 6 小时自动刷新 |
| `DEBUG` | 默认 `False`，线上不暴露详细报错 |
| `HF_ENDPOINT` | 可选，模型下载镜像地址 |

CORS 采用白名单（仅 `http://localhost:8000`、`http://127.0.0.1:8000`），不使用 `["*"]` + credentials 的放开写法。

## 近期改动

- **配置层**：路径锚定到 `backend` 目录，CORS 收紧为白名单，`DEBUG` 默认关闭
- **依赖可复现**：新增 `requirements.lock.txt`
- **启停脚本重写**：`start.bat` / `stop.bat` / `refresh.bat` 改为幂等实现
- **深度思考流式渲染修复**：前端解决 `reactive()` 响应式陷阱并重做打字机引擎，后端优化异步产出
- **仓库规范**：`.gitignore` 补充虚拟环境、日志与 `.env` 备份文件
