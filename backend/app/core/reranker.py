"""重排层：bge-reranker-v2-m3（Cross-encoder 精排）。

实现说明：用 transformers 原生加载重排模型（序列分类头 + sigmoid），
绕开 FlagEmbedding 在本机被"应用程序控制策略"阻止的 DLL 依赖。
"""

import asyncio
import threading

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from app.config import settings

_model = None
_tokenizer = None
_load_lock = threading.Lock()


def get_reranker():
    """懒加载 bge-reranker-v2-m3（全局单例）。返回 (model, tokenizer)。

    线程安全：并行检索可能多线程同时首次触发加载，必须加锁+双重检查。
    """
    global _model, _tokenizer
    if _model is None:
        with _load_lock:
            if _model is None:
                _model = AutoModelForSequenceClassification.from_pretrained(settings.RERANKER_MODEL)
                _model.eval()
                _tokenizer = AutoTokenizer.from_pretrained(settings.RERANKER_MODEL)
    return _model, _tokenizer


def _score_pairs(pairs: list[tuple[str, str]]) -> list[float]:
    model, tokenizer = get_reranker()
    inputs = tokenizer(
        pairs, padding=True, truncation=True, max_length=512, return_tensors="pt"
    )
    with torch.no_grad():
        logits = model(**inputs).logits
    return torch.sigmoid(logits.squeeze(-1)).numpy().tolist()


async def rerank(query: str, docs: list[dict], top_k: int | None = None) -> list[dict]:
    """Cross-encoder 精排：分数覆盖 docs 的 score，按分降序返回。

    docs 每项需含 title / content（或 snippet）。
    """
    if not docs:
        return []
    if top_k is None:
        top_k = settings.RERANK_TOP_K

    pairs = [(query, f'{d.get("title", "")} {d.get("content", d.get("snippet", ""))[:300]}') for d in docs]
    try:
        scores = await asyncio.to_thread(_score_pairs, pairs)
        for d, s in zip(docs, scores):
            d["score"] = float(s)
        docs.sort(key=lambda d: d["score"], reverse=True)
    except Exception:
        pass  # 精排失败不阻断主流程，保留融合分排序
    return docs
