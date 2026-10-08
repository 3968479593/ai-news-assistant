"""下载 BGE-M3 / bge-reranker-v2-m3 到 backend/models/（目录结构与 .env 默认值一致）。

用法：
    cd backend && python scripts/download_models.py
    （若 .env 里 EMBEDDING_MODEL 已指向已有模型绝对路径，可跳过本脚本）
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import settings

if settings.HF_ENDPOINT:
    os.environ["HF_ENDPOINT"] = settings.HF_ENDPOINT


def _model_root() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")


def main():
    from huggingface_hub import snapshot_download

    root = _model_root()
    os.makedirs(root, exist_ok=True)

    print("=" * 50)
    print("1/2 下载嵌入模型 BAAI/bge-m3 ...")
    print("=" * 50)
    snapshot_download(
        repo_id="BAAI/bge-m3",
        local_dir=os.path.join(root, "BAAI", "bge-m3"),
    )
    print("嵌入模型就绪。\n")

    print("=" * 50)
    print("2/2 下载重排序模型 BAAI/bge-reranker-v2-m3 ...")
    print("=" * 50)
    snapshot_download(
        repo_id="BAAI/bge-reranker-v2-m3",
        local_dir=os.path.join(root, "BAAI", "bge-reranker-v2-m3"),
    )
    print("重排序模型就绪。\n")

    print("完成！可在 backend/.env 设置：")
    print("EMBEDDING_MODEL=models/BAAI/bge-m3")
    print("RERANKER_MODEL=models/BAAI/bge-reranker-v2-m3")


if __name__ == "__main__":
    main()
