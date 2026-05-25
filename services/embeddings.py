"""
services/embeddings.py — векторные embeddings через DeepSeek API.

Используется для семантического поиска по базе знаний:
вместо поиска по ключевым словам ищем по смыслу.

Пример: «кто доставляет самолётом» → найдёт «агенты авиа»
даже если слов «самолёт» в записи нет.
"""
import json
import math
import httpx
from typing import List, Optional
from config import DEEPSEEK_API_KEY, logger

EMBEDDINGS_URL = "https://api.deepseek.com/v1/embeddings"
EMBEDDINGS_MODEL = "text-embedding-ada-002"
TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)


async def get_embedding(text: str) -> Optional[List[float]]:
    """Получает вектор для текста через DeepSeek Embeddings API.

    Args:
        text: текст для векторизации (обрезается до 8000 символов)

    Returns:
        Список float (вектор размерностью 1536) или None при ошибке
    """
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY не задан — embeddings недоступны")
        return None

    # Обрезаем длинный текст — embeddings работают лучше на коротких кусках
    text_clean = text.strip()[:8000]
    if not text_clean:
        return None

    payload = {
        "model": EMBEDDINGS_MODEL,
        "input": text_clean,
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        limits = httpx.Limits(max_keepalive_connections=0, max_connections=5)
        async with httpx.AsyncClient(timeout=TIMEOUT, limits=limits) as client:
            resp = await client.post(EMBEDDINGS_URL, json=payload, headers=headers)

        if resp.status_code != 200:
            logger.error(f"Embeddings HTTP {resp.status_code}: {resp.text[:200]}")
            return None

        data = resp.json()
        vector = data["data"][0]["embedding"]
        return vector

    except Exception as e:
        logger.error(f"Embeddings error: {e}")
        return None


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Косинусное сходство двух векторов. Возвращает значение от -1 до 1.
    Чем ближе к 1 — тем более похожи тексты по смыслу.
    """
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


def embedding_to_blob(vector: List[float]) -> bytes:
    """Сериализует вектор в bytes для хранения в SQLite BLOB."""
    return json.dumps(vector).encode("utf-8")


def blob_to_embedding(blob: bytes) -> Optional[List[float]]:
    """Десериализует вектор из SQLite BLOB."""
    if not blob:
        return None
    try:
        return json.loads(blob.decode("utf-8"))
    except Exception:
        return None
