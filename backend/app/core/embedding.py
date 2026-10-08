"""嵌入层：BGE-M3 768 维归一化稠密向量。

实现说明：用 transformers 原生加载 BGE-M3（Bert 结构，[CLS] 池化），
绕开 sentence-transformers / FlagEmbedding 在本机被"应用程序控制策略"阻止的 DLL 依赖，
模型权重与推理结果等价。
"""

import asyncio
import threading

import torch
from transformers import AutoModel, AutoTokenizer

from app.config import settings

_model = None
_tokenizer = None
_load_lock = threading.Lock()


def get_embedding_model():
    """懒加载 BGE-M3（全局单例，首次加载较慢）。返回 (model, tokenizer)。

    线程安全：并行检索可能多线程同时首次触发加载，必须加锁+双重检查，
    否则 transformers 并发 from_pretrained 会把权重加载到 meta device。
    """
    global _model, _tokenizer
    if _model is None:
        with _load_lock:
            if _model is None:
                _model = AutoModel.from_pretrained(settings.EMBEDDING_MODEL)
                _model.eval()
                _tokenizer = AutoTokenizer.from_pretrained(settings.EMBEDDING_MODEL)
    return _model, _tokenizer


def encode_dense(texts: list[str]) -> list[list[float]]:
    """同步编码：BGE-M3 dense 向量（[CLS] 池化 + L2 归一化）。"""
    model, tokenizer = get_embedding_model()
    inputs = tokenizer(
        texts, padding=True, truncation=True, max_length=2048, return_tensors="pt"
    )
    with torch.no_grad():
        out = model(**inputs)
    vecs = torch.nn.functional.normalize(out.last_hidden_state[:, 0], p=2, dim=-1)
    return vecs.numpy().tolist()


async def encode_dense_async(texts: list[str]) -> list[list[float]]:
    """异步包装：CPU 推理放到线程池，避免阻塞事件循环。"""
    return await asyncio.to_thread(encode_dense, texts)
