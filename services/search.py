"""
services/search.py — TF-IDF поиск по базе знаний.

Работает полностью на stdlib (math, re, json) — без pip, без API.
Точность значительно лучше keyword-поиска: редкие специфичные слова
(«qtavia», «rusmarine») получают высокий вес, частые («агент», «доставка») — низкий.

Пример: запрос «кто занимается авиа доставкой»
  → keyword найдёт все 5 записей где есть «агент»
  → TF-IDF найдёт именно «агенты авиа» т.к. «авиа» редкое слово в корпусе

Индекс строится в памяти при первом обращении и кешируется.
При добавлении новых записей (/learn → /done) индекс сбрасывается.
"""
import re
import math
import json
from typing import List, Dict, Optional, Set

# Кеш индекса: список (doc_id, topic, content, tfidf_vector)
_index: Optional[List[Dict]] = None
_index_version: int = 0  # инкрементируется при invalidate

# Стоп-слова для русского языка
_STOP_WORDS: Set[str] = {
    "и", "в", "на", "с", "по", "из", "для", "от", "до", "как", "что", "это",
    "так", "или", "но", "же", "бы", "не", "при", "под", "над", "без", "через",
    "также", "если", "то", "все", "всё", "его", "её", "их", "нет", "да", "вот",
    "тел", "email", "сайт", "тоже", "также",
}


def _tokenize(text: str) -> List[str]:
    """Токенизирует текст: lowercase, только кириллица/латиница 3+ букв.
    Применяет базовое усечение окончаний для русского языка.
    """
    tokens = re.findall(r'[а-яёa-z]{3,}', text.lower())
    result = []
    for t in tokens:
        if t in _STOP_WORDS:
            continue
        result.append(t)
        # Базовое усечение русских падежных окончаний — добавляем основу
        for ending in ("ом", "ём", "ем", "ых", "ий", "ая", "ое", "ую", "ой", "ам", "ами", "ах"):
            if t.endswith(ending) and len(t) - len(ending) >= 3:
                stem = t[:-len(ending)]
                if stem not in _STOP_WORDS and stem != t:
                    result.append(stem)
                break
    return result


def _compute_tf(tokens: List[str]) -> Dict[str, float]:
    """Term Frequency: частота каждого слова в документе."""
    if not tokens:
        return {}
    counts: Dict[str, int] = {}
    for t in tokens:
        counts[t] = counts.get(t, 0) + 1
    total = len(tokens)
    return {word: count / total for word, count in counts.items()}


def _build_index(records: List[Dict]) -> List[Dict]:
    """Строит TF-IDF индекс из списка записей БЗ.

    Args:
        records: [{"id": int, "topic": str, "content": str}, ...]

    Returns:
        Список документов с вычисленными TF-IDF векторами
    """
    # Шаг 1: токенизируем все документы
    docs = []
    for rec in records:
        text = f"{rec['topic']} {rec['topic']} {rec['content']}"  # тема x2 — выше вес
        tokens = _tokenize(text)
        tf = _compute_tf(tokens)
        docs.append({
            "id": rec["id"],
            "topic": rec["topic"],
            "content": rec["content"],
            "tokens_set": set(tokens),
            "tf": tf,
        })

    if not docs:
        return []

    # Шаг 2: IDF — обратная частота документов
    n_docs = len(docs)
    df: Dict[str, int] = {}  # сколько документов содержат слово
    for doc in docs:
        for word in doc["tokens_set"]:
            df[word] = df.get(word, 0) + 1

    idf: Dict[str, float] = {
        word: math.log((n_docs + 1) / (count + 1)) + 1.0
        for word, count in df.items()
    }

    # Шаг 3: TF-IDF вектор для каждого документа
    for doc in docs:
        tfidf = {word: tf_val * idf.get(word, 1.0) for word, tf_val in doc["tf"].items()}
        doc["tfidf"] = tfidf

    return docs


def _cosine(vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
    """Косинусное сходство двух TF-IDF словарей."""
    common = set(vec_a) & set(vec_b)
    if not common:
        return 0.0

    dot = sum(vec_a[w] * vec_b[w] for w in common)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


def invalidate_index() -> None:
    """Сбрасывает кеш индекса. Вызывать после добавления/удаления записей в БЗ."""
    global _index, _index_version
    _index = None
    _index_version += 1


def tfidf_search(query: str, top_n: int = 3, min_score: float = 0.05) -> List[Dict]:
    """Семантический TF-IDF поиск по базе знаний.

    Args:
        query: поисковый запрос пользователя
        top_n: сколько записей вернуть
        min_score: минимальный порог сходства

    Returns:
        Список записей, отсортированных по релевантности
    """
    global _index

    # Загружаем/обновляем индекс
    if _index is None:
        from database import get_all_knowledge_with_ids
        records = get_all_knowledge_with_ids()
        _index = _build_index(records)

    if not _index:
        return []

    # Расширяем запрос синонимами — компенсируем отсутствие векторов
    # Используем точное совпадение И совпадение по префиксу (для падежных форм)
    SYNONYMS = {
        "авиа": ["авиа", "авиадоставка", "самолёт", "воздух", "air", "авиаперевозка"],
        "авиадоставк": ["авиа", "авиадоставка"],
        "авиаперевозк": ["авиа", "авиадоставка"],
        "самолёт": ["авиа", "авиадоставка", "авиаперевозка"],
        "самолет": ["авиа", "авиадоставка", "авиаперевозка"],
        "самолёт": ["авиа", "авиадоставка"],
        "самолём": ["авиа", "авиадоставка"],  # творительный: самолётом
        "воздуш": ["авиа", "авиадоставка"],
        "летит": ["авиа", "авиадоставка"],
        "летел": ["авиа", "авиадоставка"],
        "воздуш": ["авиа", "авиадоставка"],
        "авто": ["авто", "автодоставка", "машина", "фура", "грузовик", "truck"],
        "автодоставк": ["авто", "автодоставка", "фура"],
        "фура": ["авто", "автодоставка"],
        "машина": ["авто", "автодоставка"],
        "грузовик": ["авто", "автодоставка"],
        "жд": ["жд", "железная", "дорога", "поезд", "rail", "прямое"],
        "железн": ["жд", "дорога", "поезд"],
        "поезд": ["жд", "железная", "дорога"],
        "море": ["море", "морской", "sea", "ocean"],
        "морск": ["море", "sea"],
        "агент": ["агент", "экспедитор", "партнёр"],
        "экспедитор": ["экспедитор", "агент", "партнёр"],
        "партнёр": ["партнёр", "агент", "экспедитор"],
        "контакт": ["контакт", "телефон", "email", "связь"],
        "декларант": ["декларант", "декларанты", "анна", "михаил", "александра", "контакты декларант"],
    }

    # Расширяем запрос: точное + префиксное совпадение
    base_tokens = _tokenize(query)
    expanded_tokens = list(base_tokens)
    for token in base_tokens:
        # Точное совпадение
        if token in SYNONYMS:
            expanded_tokens.extend(SYNONYMS[token])
        else:
            # Префиксное совпадение (до 6 символов)
            for prefix, synonyms in SYNONYMS.items():
                if len(prefix) >= 5 and token.startswith(prefix):
                    expanded_tokens.extend(synonyms)
                    break

    if not expanded_tokens:
        return []

    # Вектор запроса с учётом расширения
    query_tf = _compute_tf(expanded_tokens)

    # IDF из индекса
    n_docs = len(_index)
    df: Dict[str, int] = {}
    for doc in _index:
        for word in doc["tokens_set"]:
            df[word] = df.get(word, 0) + 1

    query_tfidf: Dict[str, float] = {}
    for word, tf_val in query_tf.items():
        idf_val = math.log((n_docs + 1) / (df.get(word, 0) + 1)) + 1.0
        query_tfidf[word] = tf_val * idf_val

    # Считаем сходство с каждым документом
    scored = []
    for doc in _index:
        score = _cosine(query_tfidf, doc["tfidf"])
        if score >= min_score:
            scored.append((score, doc))

    scored.sort(key=lambda x: -x[0])
    return [
        {"id": d["id"], "topic": d["topic"], "content": d["content"]}
        for _, d in scored[:top_n]
    ]
