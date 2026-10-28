"""Векторизация текстов трансформером (шаг 4.2): тексты -> векторы фиксированной длины.

По умолчанию cointegrated/rubert-tiny2 (312 чисел на текст, берётся вектор [CLS], нормируется).
Результат кэшируется на диск, чтобы не пересчитывать при каждом запуске.
"""
from __future__ import annotations

import hashlib
import os

import numpy as np

DEFAULT_MODEL = "cointegrated/rubert-tiny2"


def _cache_path(cache_dir: str, model: str, pooling: str, max_length: int, texts: list[str]) -> str:
    h = hashlib.sha1()
    h.update(f"{model}|{pooling}|{max_length}|{len(texts)}".encode())
    for t in texts:
        h.update(t.encode("utf-8"))
        h.update(b"\x00")
    slug = model.replace("\\", "_").replace("/", "_").replace(":", "_")[-60:]
    return os.path.join(cache_dir, f"emb_{slug}_{h.hexdigest()[:16]}.npy")


def encode_texts(
    texts: list[str],
    model_name: str = DEFAULT_MODEL,
    pooling: str = "cls",
    batch_size: int = 64,
    max_length: int = 128,
    cache_dir: str | None = None,
    device: str | None = None,
) -> np.ndarray:
    """Возвращает матрицу (число текстов x размер вектора), строки нормированы до длины 1."""
    if pooling not in ("cls", "mean"):
        raise ValueError("pooling: 'cls' или 'mean'")
    texts = [str(t) for t in texts]
    path = None
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        path = _cache_path(cache_dir, model_name, pooling, max_length, texts)
        if os.path.exists(path):
            return np.load(path)

    import torch
    from transformers import AutoModel, AutoTokenizer

    dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
    tok = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name).to(dev).eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(texts), batch_size):
            batch = tok(texts[i:i + batch_size], padding=True, truncation=True,
                        max_length=max_length, return_tensors="pt").to(dev)
            hidden = model(**batch).last_hidden_state
            if pooling == "cls":
                emb = hidden[:, 0, :]
            else:
                mask = batch["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                emb = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1)
            emb = torch.nn.functional.normalize(emb, dim=1)
            out.append(emb.cpu().numpy())
    result = np.vstack(out).astype(np.float32) if out else np.zeros((0, 0), dtype=np.float32)
    if path:
        np.save(path, result)
    return result
