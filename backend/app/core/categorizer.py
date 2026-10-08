"""新闻模块（分类）判定：源映射优先 → 关键词打分 → 综合兜底。

模块体系（见 config.NEWS_CATEGORIES）：
    科技 / 商业财经 / 国际 / 体育 / 娱乐 / 健康 / 生活 / 综合
纯规则实现，无外部依赖、无网络请求，入库与检索共用。
"""

from app.config import settings

# 新闻源 → 模块映射（源名匹配 feed.title / 示例来源名）
SOURCE_CATEGORY_MAP: dict[str, str] = {
    # 真实 RSS
    "少数派": "科技",
    "36氪": "商业财经",
    "量子位": "科技",
    "IT之家": "科技",
    "钛媒体": "科技",
    "雷锋网": "科技",
    "cnBeta": "科技",
    "联合早报": "国际",
    "BBC": "国际",
    "体育新闻": "体育",
    "体育频道": "体育",
    "财经新闻": "商业财经",
    "国际新闻": "国际",
    "财经频道": "商业财经",
    "国际频道": "国际",
    "财新": "商业财经",
    "晚点": "科技",
    "深网": "科技",
    "三联": "生活",
    # 示例数据源
    "科技时报": "科技",
    "消费电子": "科技",
    "财经观察网": "商业财经",
    "体育快讯": "体育",
    "民生健康报": "生活",
    "环球产经": "国际",
}

# 模块 → 关键词（标题 + 正文命中计数，取最高分；同分按本表顺序优先）
KEYWORD_CATEGORY_MAP: dict[str, list[str]] = {
    "科技": [
        "芯片", "半导体", "大模型", "AI", "人工智能", "算力", "手机", "折叠屏",
        "软件", "互联网", "航天", "火箭", "空间站", "卫星", "量子", "机器人",
        "无人机", "开源", "操作系统", "云计算", "自动驾驶", "发布会", "数码",
    ],
    "商业财经": [
        "股市", "股价", "A股", "港股", "美股", "黄金", "金价", "基金", "银行",
        "利率", "GDP", "经济", "央行", "保险", "券商", "融资", "上市", "财报",
        "营收", "贸易", "关税", "油价", "涨价", "降价", "销量", "订单", "房地产",
    ],
    "国际": [
        "国际", "全球", "美国", "欧洲", "俄罗斯", "乌克兰", "白宫", "联合国",
        "欧盟", "中东", "北约", "外交", "外长", "使馆", "境外", "海外", "冲突",
    ],
    "体育": [
        "足球", "篮球", "国足", "世界杯", "奥运", "亚运", "联赛", "NBA", "中超",
        "夺冠", "球员", "教练", "比赛", "赛", "冠军", "预选赛",
    ],
    "娱乐": [
        "电影", "电视剧", "明星", "综艺", "音乐", "票房", "演唱会", "颁奖", "艺人",
        "热播", "新片", "专辑",
    ],
    "健康": [
        "医保", "医院", "疾病", "健康", "疫苗", "药品", "临床", "医学", "疫情",
        "养生", "膳食", "患者", "治疗", "体检",
    ],
    "生活": [
        "旅游", "假期", "台风", "天气", "教育", "学校", "就业", "消费", "美食",
        "出行", "交通", "住房", "补贴", "台风预警", "民生",
    ],
}


def _source_category(source: str) -> str | None:
    if not source:
        return None
    for key, cat in SOURCE_CATEGORY_MAP.items():
        if key in source:
            return cat
    return None


def _keyword_category(text: str) -> str | None:
    if not text:
        return None
    best_cat, best_hits = None, 0
    for cat, words in KEYWORD_CATEGORY_MAP.items():
        hits = sum(1 for w in words if w.lower() in text.lower())
        if hits > best_hits:
            best_cat, best_hits = cat, hits
    return best_cat if best_hits >= 1 else None  # 命中 1 个关键词即采信（源映射已兜底常见源）


def classify(title: str, content: str = "", source: str = "") -> str:
    """判定新闻所属模块。优先级：源映射 → 关键词 → 综合。"""
    cat = _source_category(source)
    if cat:
        return cat
    cat = _keyword_category(f"{title} {content}")
    if cat:
        return cat
    return "综合"


def is_valid_category(category: str | None) -> bool:
    """校验模块名是否在体系内。"""
    return category in settings.NEWS_CATEGORIES
