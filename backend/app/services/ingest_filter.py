"""入库主题过滤：关键词白名单（运行时配置文件优先，回落 .env 默认值）。

- 频道源（feed.title 命中"财经频道/国际频道/科技频道…"）→ 直接放行（频道已定位模块，不受关键词闸门限制）
- 关键词为空列表 → 不过滤，全量收录（保持原行为）
- 关键词非空 → 标题或正文命中任一关键词（不区分大小写）才放行入库
- 运行时通过 /api/settings/ingest-filter 读写 data/ingest_filter.json，即时生效
"""

import json
from pathlib import Path

from app.config import settings

_FILTER_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "ingest_filter.json"

# 频道源豁免：feed.title 含这些频道名的源按模块直接放行（人民网财经/国际等）
_CHANNEL_SOURCE_NAMES = (
    "财经频道", "国际频道", "科技频道", "体育频道", "娱乐频道",
    "健康频道", "生活频道", "军事频道", "文化频道",
    "财经新闻", "国际新闻",
)


def _env_keywords() -> list[str]:
    return [k.strip() for k in settings.INGEST_KEYWORDS if k and k.strip()]


def get_keywords() -> list[str]:
    """当前生效的关键词（运行时配置优先）。"""
    try:
        if _FILTER_FILE.exists():
            data = json.loads(_FILTER_FILE.read_text(encoding="utf-8"))
            kws = [k.strip() for k in data.get("keywords", []) if k and k.strip()]
            if kws:
                return kws
    except Exception:
        pass
    return _env_keywords()


def set_keywords(keywords: list[str]) -> list[str]:
    """持久化关键词到运行时配置（写文件）。"""
    kws = [k.strip() for k in keywords if k and k.strip()]
    _FILTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    _FILTER_FILE.write_text(
        json.dumps({"keywords": kws}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return kws


def matches(title: str, content: str, source: str = "") -> bool:
    """入库过滤闸门：
    - 频道源（feed.title 含频道名）→ True（频道已定位模块，全量收录）
    - 未配置关键词 → True（全收）
    - 配置了 → 标题/正文命中任一关键词才 True
    """
    if source and any(k in source for k in _CHANNEL_SOURCE_NAMES):
        return True
    kws = get_keywords()
    if not kws:
        return True
    text = f"{title}\n{content}".lower()
    return any(k.lower() in text for k in kws)
