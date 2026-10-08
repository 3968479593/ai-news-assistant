from collections import defaultdict

from app.config import settings


def rrf_merge(ranked_lists: list[list[str]], k: int = None) -> list[str]:
    """倒数排名融合（Reciprocal Rank Fusion）。

    参数
    ----
    ranked_lists : 多个按相关性排序的 doc_id 列表（如 向量召回、BM25 召回）
    k            : RRF 常数，默认取 settings.RRF_K

    返回
    ----
    按融合分数降序的 doc_id 列表（去重）
    """
    if k is None:
        k = settings.RRF_K
    scores: dict[str, float] = defaultdict(float)

    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked):
            scores[doc_id] += 1.0 / (k + rank + 1)

    return [doc_id for doc_id, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]
