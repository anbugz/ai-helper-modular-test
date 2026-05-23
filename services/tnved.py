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

RADIO_GROUPS_ALWAYS = {"84", "85", "90", "91", "95"}

def is_radio_electronics(code: str) -> bool:
    """Проверяет по списку + по первым 2 цифрам группы.
    Для коротких шаблонов (≤9 цифр) — startswith (группы/подгруппы).
    Для длинных шаблонов (≥10 цифр) — точное совпадение (полные коды).
    """
    if not code:
        return False
    c = code.replace(" ", "").replace(".", "").strip()

    # Группы 84, 85, 90, 91, 95 — всегда радиоэлектроника
    if len(c) >= 2 and c[:2] in RADIO_GROUPS_ALWAYS:
        return True

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
    """Извлекает коды ТН ВЭД (8-10 цифр) из текста, включая с пробелами (5208 43 000 0).
    Если полных кодов нет — ищет короткие (4-6 цифр) рядом со словом 'код' и подгружает
    первый полный код из БД/кэша по префиксу.
    """
    # Нормализуем: убираем пробелы между цифрами
    normalized = re.sub(r'(\d)\s+(?=\d)', r'', text)
    codes = re.findall(r"\d{8,10}", normalized)

    # Fallback: короткие коды (4-6 цифр) рядом с маркером "код/группа/подгруппа/раздел"
    if not codes:
        short_codes = re.findall(
            r"(?:код|группа|подгруппа|раздел)\s*[:=]?\s*(\d{4,6})",
            text.lower()
        )
        for sc in short_codes:
            # Ищем в памяти
            found = False
            for row in _TNVED_ROWS_CACHE:
                if not row or not isinstance(row[0], str):
                    continue
                full = row[0].replace(" ", "").strip()
                if full.startswith(sc) and len(full) >= 8:
                    codes.append(full)
                    found = True
                    break
            if not found:
                # Ищем в БД с ORDER BY для предсказуемости
                import sqlite3
                from config import DB_PATH
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("SELECT code FROM tnved_cache WHERE code LIKE ? ORDER BY code LIMIT 1", (f"{sc}%",))
                row = c.fetchone()
                conn.close()
                if row:
                    codes.append(row[0])
    return codes


# ------------------------------------------------------------------
# Таможенный сбор по шкале
# ------------------------------------------------------------------

def calculate_customs_fee(value_rub: float) -> int:
    """Рассчитывает таможенный сбор по шкале ПП РФ №1637."""
    from config import CUSTOMS_FEE_RUB

    for threshold, fee in sorted(CUSTOMS_FEE_RUB.items()):
        if value_rub <= threshold:
            return fee
    return 73_860  # максимум по шкале с 01.01.2026


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

    # Процент: "15%", "5 %"
    pct_match = re.search(r'(\d+(?:[.,]\d+)?)\s*%', t)
    if pct_match:
        try:
            val = float(pct_match.group(1).replace(',', '.'))
            return {"type": "percent", "formula": tariff_str, "value": val}
        except ValueError:
            pass

    # Комбинированный: "15%, но не менее 0,2 евро/кг"
    if "не менее" in t:
        eur_match = re.search(r'(\d+(?:[.,]\d+)?)\s*евро', t)
        eur_val = float(eur_match.group(1).replace(',', '.')) if eur_match else 0
        return {"type": "min", "formula": tariff_str, "value": eur_val}

    # Комбинированный с плюсом: "10% + 0,5 евро/кг"
    if "+" in t and "евро" in t:
        eur_match = re.search(r'(\d+(?:[.,]\d+)?)\s*евро', t)
        eur_val = float(eur_match.group(1).replace(',', '.')) if eur_match else 0
        return {"type": "plus", "formula": tariff_str, "value": eur_val}

    # Фиксированный евро: "0,3 евро/кг"
    if "евро" in t:
        eur_match = re.search(r'(\d+(?:[.,]\d+)?)\s*евро', t)
        eur_val = float(eur_match.group(1).replace(',', '.')) if eur_match else 0
        return {"type": "fixed_eur", "formula": tariff_str, "value": eur_val}

    return {"type": "", "formula": tariff_str, "value": 0}
