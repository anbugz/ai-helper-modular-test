"""
services/tnved.py — кэш данных ТН ВЭД, поиск, проверка радиоэлектроники.
Полный перенос из tnved_engine.py.
"""
import re
from typing import List, Dict, Optional
from config import RADIO_ELECTRONICS_CODES_SET, _RADIO_GROUPS, TNVED_FULL_NAMES, logger
from database import save_tnved_batch, get_tnved_from_db, get_all_tnved_from_db

# ------------------------------------------------------------------
# Кэш (в памяти, не в SQLite)
# ------------------------------------------------------------------
_TNVED_ROWS_CACHE: List[List[str]] = []
_TNVED_INDEX: Dict[str, int] = {}  # code -> row_index


def _build_tnved_index(rows: List[List[str]]) -> None:
    """Строит индекс для быстрого поиска кодов ТН ВЭД."""
    global _TNVED_INDEX
    _TNVED_INDEX = {}
    for i, row in enumerate(rows):
        if not row or not isinstance(row[0], str):
            continue
        code = row[0].replace(" ", "").strip()
        if len(code) >= 6 and code.isdigit():
            _TNVED_INDEX[code] = i


def load_tnved_rows(rows: List[List[str]], persist: bool = True) -> None:
    """Загружает строки ТН ВЭД в кэш, строит индекс, сохраняет в SQLite, заполняет TNVED_FULL_NAMES."""
    global _TNVED_ROWS_CACHE
    _TNVED_ROWS_CACHE = [r for r in rows if r and any(str(c).strip() for c in r)]
    _build_tnved_index(_TNVED_ROWS_CACHE)
    # Заполняем полные наименования из загруженных данных
    TNVED_FULL_NAMES.clear()
    for row in _TNVED_ROWS_CACHE:
        if not row or not isinstance(row[0], str):
            continue
        code = row[0].replace(" ", "").strip()
        name = row[1] if len(row) > 1 else ""
        if len(code) >= 6 and code.isdigit() and name:
            prefix = code[:6]
            # Сохраняем самое длинное наименование для префикса
            if prefix not in TNVED_FULL_NAMES or len(name) > len(TNVED_FULL_NAMES[prefix]):
                TNVED_FULL_NAMES[prefix] = name
    logger.info(
        f"TNVED кэш: {len(_TNVED_ROWS_CACHE)} строк, {len(_TNVED_INDEX)} кодов, "
        f"{len(TNVED_FULL_NAMES)} полных наименований"
    )
    if persist:
        parsed_rows = [
            parse_tnved_tariff(row[2] if len(row) > 2 else "") for row in _TNVED_ROWS_CACHE
        ]
        save_tnved_batch(_TNVED_ROWS_CACHE, parsed_rows)


def restore_tnved_from_db() -> bool:
    """Восстанавливает кэш ТН ВЭД из SQLite при старте бота, включая полные наименования."""
    global _TNVED_ROWS_CACHE
    rows = get_all_tnved_from_db()
    if not rows:
        logger.info("TNVED кэш в БД пуст — жду загрузки .xlsx")
        return False
    _TNVED_ROWS_CACHE = rows
    _build_tnved_index(_TNVED_ROWS_CACHE)
    # Восстанавливаем полные наименования
    TNVED_FULL_NAMES.clear()
    for row in rows:
        if not row or not isinstance(row[0], str):
            continue
        code = row[0].replace(" ", "").strip()
        name = row[1] if len(row) > 1 else ""
        if len(code) >= 6 and code.isdigit() and name:
            prefix = code[:6]
            if prefix not in TNVED_FULL_NAMES or len(name) > len(TNVED_FULL_NAMES[prefix]):
                TNVED_FULL_NAMES[prefix] = name
    logger.info(
        f"TNVED кэш восстановлен из БД: {len(_TNVED_ROWS_CACHE)} строк, "
        f"{len(TNVED_FULL_NAMES)} полных наименований"
    )
    return True


def get_tnved_from_cache(code: str) -> Optional[dict]:
    """Быстрый поиск кода ТН ВЭД: сначала память (O(1)), потом SQLite."""
    if not code:
        return None
    if _TNVED_INDEX:
        search_code = code.replace(" ", "").replace(".", "").strip()
        idx = _TNVED_INDEX.get(search_code)
        if idx is not None and idx < len(_TNVED_ROWS_CACHE):
            return _row_to_tnved_dict(_TNVED_ROWS_CACHE[idx])
        if len(search_code) >= 6:
            for full_code, i in _TNVED_INDEX.items():
                if full_code.startswith(search_code) and i < len(_TNVED_ROWS_CACHE):
                    return _row_to_tnved_dict(_TNVED_ROWS_CACHE[i])
    return get_tnved_from_db(code)


def _row_to_tnved_dict(row: List[str]) -> dict:
    """Преобразует строку Excel в словарь с данными ТН ВЭД."""
    tariff = row[2] if len(row) > 2 else ""
    parsed = parse_tnved_tariff(tariff)
    return {
        "code": row[0] if row else "",
        "name": row[1] if len(row) > 1 else "",
        "tariff": tariff,
        "parsed_tariff": parsed,
        "has_euro_component": parsed.get("type") in ("min", "plus", "fixed_eur"),
        "needs_weight": parsed.get("type") in ("min", "plus", "fixed_eur"),
    }


# ------------------------------------------------------------------
# Радиоэлектроника
# ------------------------------------------------------------------

def is_radio_electronics(code: str) -> bool:
    """Проверяет по списку + по первым 2 цифрам группы.
    Для коротких шаблонов (≤9 цифр) — startswith (группы/подгруппы).
    Для длинных шаблонов (≥10 цифр) — точное совпадение (полные коды).
    """
    if not code:
        return False
    c = code.replace(" ", "").replace(".", "").strip()
    # Группа 85 (телефоны, смартфоны) — всегда радиоэлектроника
    if len(c) >= 2 and c[:2] == "85":
        return True
    if len(c) >= 2 and c[:2] not in _RADIO_GROUPS:
        return False
    for pattern in RADIO_ELECTRONICS_CODES_SET:
        if len(pattern) <= 9:
            # Короткие паттерны (4-9 знаков) = группа/подгруппа/позиция → startswith
            if c.startswith(pattern):
                return True
        else:
            # 10-значные паттерны = конкретный товар → точное совпадение
            if c == pattern:
                return True
    return False


# ------------------------------------------------------------------
# Извлечение кодов из текста
# ------------------------------------------------------------------

def extract_tnved_codes(text: str) -> List[str]:
    """Извлекает коды ТН ВЭД (8-10 цифр) из текста, включая с пробелами (5208 43 000 0)."""
    # Нормализуем: убираем пробелы между цифрами
    normalized = re.sub(r'(\d)\s+(?=\d)', r'\1', text)
    return re.findall(r"\d{8,10}", normalized)


# ------------------------------------------------------------------
# Таможенный сбор по шкале
# ------------------------------------------------------------------

def calculate_customs_fee(value_rub: float) -> int:
    """Рассчитывает таможенный сбор по шкале ПП РФ №1637."""
    from config import CUSTOMS_FEE_RUB, RADIO_FEE
    
    for threshold, fee in sorted(CUSTOMS_FEE_RUB.items()):
        if value_rub <= threshold:
            return fee
    return RADIO_FEE


# ------------------------------------------------------------------
# Парсинг тарифа
# ------------------------------------------------------------------

def parse_tnved_tariff(tariff_str: str) -> dict:
    """Парсит строку тарифа ТН ВЭД в структурированный формат.
    
    Returns:
        {"type": "percent"/"min"/"plus"/"fixed_eur"/"", 
         "formula": "оригинальная строка",
         "value": числовое значение для percent}
    """
    t = (tariff_str or "").strip().lower()
    if not t:
        return {"type": "", "formula": "", "value": 0}
    
    # Извлекаем процент (если есть)
    pct_match = re.search(r'(\d+(?:[.,]\d+)?)\s*%', t)
    pct_val = float(pct_match.group(1).replace(',', '.')) if pct_match else 0

    # Извлекаем евро/кг (если есть)
    eur_match = re.search(r'(\d+(?:[.,]\d+)?)\s*евро', t)
    eur_val = float(eur_match.group(1).replace(',', '.')) if eur_match else 0

    # Комбинированный: "15%, но не менее 0,2 евро/кг"
    # ВАЖНО: проверяем ДО простого процента, иначе евро-компонент теряется
    if ("не менее" in t or "но менее" in t) and pct_val and eur_val:
        return {
            "type": "min",
            "formula": tariff_str,
            "value": pct_val,       # адвалорный % (для расчёта адвалорной части)
            "eur_per_kg": eur_val,  # минимальная ставка евро/кг
        }

    # Комбинированный с плюсом: "10% + 0,5 евро/кг"
    if "+" in t and pct_val and eur_val:
        return {
            "type": "plus",
            "formula": tariff_str,
            "value": pct_val,       # адвалорный %
            "eur_per_kg": eur_val,  # фиксированная добавка евро/кг
        }

    # Простой процент: "15%"
    if pct_val:
        return {"type": "percent", "formula": tariff_str, "value": pct_val, "eur_per_kg": 0}

    # Фиксированный евро: "0,3 евро/кг"
    if eur_val:
        return {"type": "fixed_eur", "formula": tariff_str, "value": 0, "eur_per_kg": eur_val}

    return {"type": "", "formula": tariff_str, "value": 0, "eur_per_kg": 0}
