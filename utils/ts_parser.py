"""
utils/ts_parser.py — извлечение компонентов таможенной стоимости.
Перенос из utils.py: extract_ts_components, extract_ts_components_with_currency,
_detect_currency_near, _extract_component.
"""
import re
from typing import Dict, Optional
from utils.text import words_to_number


def _parse_num(s: str) -> float:
    """Парсит число из строки (с пробелами и запятыми)."""
    s = s.strip().replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _detect_currency_near(text: str, pos: int) -> str:
    """Определяет валюту по контексту вокруг позиции числа.
    Приоритет: ВПЕРЁД (прилепленные валюты: 900дол, 2500р), потом ВОКРУГ.
    """
    text_lower = text.lower()
    # Смотрим вперёд (до 10 символов) — приоритет для прилепленных валют
    fwd = text_lower[pos:pos + 10]
    # Смотрим назад (до 10 символов)
    bwd = text_lower[max(0, pos - 10):pos]
    # Объединяем
    combined = bwd + " " + fwd

    # === ПРИОРИТЕТ 1: прилепленные валюты ВПЕРЕДИ числа ===
    # CNY прилепленный (100000ю, 100000юан)
    if re.search(r'^\s*ю(?:аней|ани|ань|ан|а|$|[^а-я])', fwd):
        return "CNY"
    # USD прилепленный (900дол, 900долл)
    if re.search(r'^\s*дол(?:лар|л|$|[^а-я])', fwd):
        return "USD"
    # EUR прилепленный (300евр, 300евро)
    if re.search(r'^\s*евр(?:о|$|[^а-я])', fwd):
        return "EUR"
    # RUB прилепленный (2500р, 2500руб)
    if re.search(r'^\s*руб(?:ль|ли|лей|лях|л|$|[^а-я])', fwd):
        return "RUB"
    if re.search(r'^\s*р(?:$|[^а-я])', fwd):
        return "RUB"

    # === ПРИОРИТЕТ 2: валюты ВО ВСЕМ ТЕКСТЕ (до 30 символов) ===
    full_fwd = text_lower[pos:pos + 30]
    full_bwd = text_lower[max(0, pos - 30):pos]
    full_combined = full_bwd + " " + full_fwd
    if 'eur' in full_combined or 'евро' in full_combined or '€' in full_combined:
        return "EUR"
    if 'usd' in full_combined or 'доллар' in full_combined or '$' in full_combined:
        return "USD"
    if 'cny' in full_combined or 'юан' in full_combined or '¥' in full_combined:
        return "CNY"
    if 'руб' in full_combined or '₽' in full_combined:
        return "RUB"

    # === ПРИОРИТЕТ 3: символы валют В БЛИЖАЙШЕЙ ОКРЕСТНОСТИ ===
    if '$' in combined or 'usd' in combined or 'доллар' in combined:
        return "USD"
    if '€' in combined or 'eur' in combined or 'евро' in combined:
        return "EUR"
    if '¥' in combined or ('юан' in combined and 'ю' in combined):
        return "CNY"
    if '₽' in combined or 'руб' in combined:
        return "RUB"

    # === ПРИОРИТЕТ 4: валюты ВОКРУГ (отдельные слова) ===
    if any(x in combined for x in ("юаней", "юани", "юанях", "юанями", "юань", "юаны", "китайск", "rmb", "yuan")):
        return "CNY"
    if "¥" in combined or "cny" in combined:
        return "CNY"
    if any(x in combined for x in ("доллар", "доллары", "доллара", "долларов", "greenback", "американск")):
        return "USD"
    if any(x in combined for x in ("бакс", "баксы", "бакса", "баксов")):
        return "USD"
    if any(x in combined for x in ("евро", "евров", "европейск")):
        return "EUR"
    if "€" in combined or "eur" in combined:
        return "EUR"
    if any(x in combined for x in ("рубль", "рубли", "рублей", "рублях", "рублями", "российск")):
        return "RUB"
    if "₽" in combined or "rub" in combined:
        return "RUB"

    return "RUB"


def _extract_component(text_clean: str, keywords: tuple) -> Optional[Dict]:
    """Извлекает число и валюту по ключевым словам.
    Валюта ищется с позиции конца числа (учитывает прилепленные: 100000юаней, 900дол, 2500р).
    """
    pattern = "|".join(keywords)
    m = re.search(rf"(?:{pattern})[^\d]*(\d[\d\s,.]+)", text_clean)
    if m:
        raw_num = m.group(1)
        val = _parse_num(raw_num)
        # Находим длину числовой части в raw_num
        num_len = len(re.match(r"[\d\s,.]+", raw_num).group())
        # Валюта ищется с позиции КОНЦА числа
        cur = _detect_currency_near(text_clean, m.start(1) + num_len)
        return {"value": val, "currency": cur}
    return None


def extract_ts_components_with_currency(text: str) -> Dict[str, Dict]:
    """Извлекает компоненты ТС с валютами.
    
    Returns:
        {"invoice": {"value": 100000.0, "currency": "CNY"}, 
         "freight": {"value": 5000.0, "currency": "CNY"},
         "insurance": {"value": 1000.0, "currency": "CNY"},
         "weight_kg": 100.0}
    """
    res: Dict[str, Dict] = {}
    text_lower = text.lower()
    # Конвертируем числительные в цифры (голосовые: "пять тысяч" → 5000)
    text_lower = words_to_number(text_lower)
    text_clean = re.sub(r"\d{8,10}", "", text_lower)

    # Инвойс — по ключевым словам
    inv = _extract_component(text_clean, ("инвойс", "сумма", "стоимость", "цена"))
    if inv:
        res["invoice"] = inv

    # Фрахт
    fr = _extract_component(text_clean, ("фрахт", "доставка", "перевозка"))
    if fr:
        res["freight"] = fr

    # Страховка
    ins = _extract_component(text_clean, ("страховка", "страхование"))
    if ins:
        res["insurance"] = ins

    # Вес (кг или тонны → кг)
    weight_patterns = [
        (r"(\d[\d\s,.]*)\s*(?:тонн|тонны|tons?|т\b)", 1000),   # тонны × 1000
        (r"(\d[\d\s,.]*)\s*(?:кг|kg|килограмм|килограммов|кило)", 1),  # кг
    ]
    for pattern, multiplier in weight_patterns:
        weight_m = re.search(pattern, text_clean)
        if weight_m:
            res["weight_kg"] = _parse_num(weight_m.group(1)) * multiplier
            break

    # Fallback invoice — первое число ≥ 1000
    if "invoice" not in res:
        for m in re.finditer(r"(\d[\d\s,.]{2,})", text_clean):
            val = _parse_num(m.group(1))
            if val < 1000:
                continue
            num_len = len(re.match(r"[\d\s,.]+", m.group(1)).group())
            pos_after = m.start(1) + num_len

            # Пропускаем если перед числом ключевое слово фрахта/страховки/кода
            before = text_clean[max(0, m.start() - 30):m.start()]
            if any(kw in before for kw in ("фрахт", "доставк", "перевозк", "страховк", "страхан", "код", "группа", "подгруппа", "раздел")):
                continue

            # Проверяем что после числа (первые 2 токена)
            after = text_clean[pos_after:pos_after + 20]
            after_tokens = after.split()[:2]
            after_str = " ".join(after_tokens)

            # Число в начале строки (после кода ТН ВЭД) = инвойс
            is_at_start = m.start() <= 2

            # Если валютный маркер сразу после числа, а потом фрахт — это инвойс
            has_currency_marker = any(x in after_str for x in ("ю", "дол", "евр", "руб", "р.", "$", "€", "¥"))

            # Пропускаем только если фрахт/страховка идёт СРАЗУ после числа (без валютного маркера)
            if any(kw in after_str for kw in ("фрахт", "доставк", "перевозк", "страховк", "страхан")):
                if not is_at_start and not has_currency_marker:
                    continue

            cur = _detect_currency_near(text_clean, pos_after)
            res["invoice"] = {"value": val, "currency": cur}
            break

    return res
