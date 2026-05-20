"""
services/calc.py — расчёт таможенных платежей.
Вынесено из calc_engine.py — только core-логика.
"""
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Шкала таможенного сбора (ПП РФ №1637)
FEE_BRACKETS = [
    (200_000, 1_231),
    (450_000, 2_462),
    (1_200_000, 4_924),
    (2_700_000, 13_541),
    (4_200_000, 18_465),
    (5_500_000, 21_344),
    (10_000_000, 49_240),
]

RADIO_FEE = 73_860  # радиосбор фиксированный

def calculate_customs(
    ts: float,
    rate: float,
    duty_type: str,
    duty_eur: float,
    vat_rate: float,
    radio: bool,
    eur_rate: float,
    weight_kg: Optional[float] = None,
    currency: str = "USD"
) -> Dict[str, Any]:
    """
    Расчёт таможенных платежей.
    
    Args:
        ts: таможенная стоимость (в валюте инвойса)
        rate: ставка пошлины (%)
        duty_type: тип тарифа (ad_valorem, min, plus, fixed_eur)
        duty_eur: EUR/кг компонента
        vat_rate: НДС (%)
        radio: радиоэлектроника (True/False)
        eur_rate: курс EUR к валюте инвойса
        weight_kg: вес в кг (для fixed_eur/min/plus)
        currency: валюта инвойса
    
    Returns:
        dict с breakdown по каждому платежу
    """
    result = {
        "ts": ts,
        "currency": currency,
        "duty": 0.0,
        "duty_detail": "",
        "vat": 0.0,
        "vat_rate": vat_rate,
        "fee": 0.0,
        "radio_fee": RADIO_FEE if radio else 0,
        "total": 0.0,
    }
    
    # 1. Пошлина
    duty_ad = ts * rate / 100  # адвалорная часть
    
    if duty_type == "fixed_eur" and duty_eur:
        if weight_kg:
            duty = duty_eur * weight_kg * eur_rate
            result["duty"] = duty
            result["duty_detail"] = f"{duty_eur} EUR/кг × {weight_kg} кг = {duty:.2f} {currency}"
        else:
            result["duty"] = 0
            result["duty_detail"] = f"⚠️ {duty_eur} EUR/кг — укажите вес"
    elif duty_type in ("min", "plus") and duty_eur:
        duty_eur_cur = duty_eur * (weight_kg or 0) * eur_rate
        if duty_type == "min":
            duty = max(duty_ad, duty_eur_cur)
            if duty_eur_cur > duty_ad:
                result["duty_detail"] = f"EUR-компонента ({duty_eur_cur:.2f} > {duty_ad:.2f})"
            else:
                result["duty_detail"] = f"Адвалорная {rate}% ({duty_ad:.2f} ≥ {duty_eur_cur:.2f})"
        else:  # plus
            duty = duty_ad + duty_eur_cur
            result["duty_detail"] = f"{rate}% + {duty_eur} EUR/кг × {weight_kg or 0} кг"
        result["duty"] = duty
    else:
        # ad_valorem
        result["duty"] = duty_ad
        result["duty_detail"] = f"{rate}% от {ts:.2f}"
    
    # 2. НДС
    vat_base = ts + result["duty"]
    result["vat"] = vat_base * vat_rate / 100
    
    # 3. Таможенный сбор
    ts_rub = ts * eur_rate  # примерно, если валюта не RUB
    for threshold, fee in FEE_BRACKETS:
        if ts_rub <= threshold:
            result["fee"] = fee
            break
    else:
        result["fee"] = 73_860  # максимум
    
    # 4. Итого
    result["total"] = result["duty"] + result["vat"] + result["fee"] + result["radio_fee"]
    
    return result


def format_result(calc: Dict[str, Any]) -> str:
    """Форматирование результата расчёта в HTML."""
    lines = [
        f"<b>📊 Таможенные платежи</b>",
        f"",
        f"💰 Таможенная стоимость: {calc['ts']:,.2f} {calc['currency']}",
        f"",
        f"📋 Пошлина: {calc['duty']:,.2f} {calc['currency']}",
        f"   ({calc['duty_detail']})",
        f"",
        f"📋 НДС {calc['vat_rate']}%: {calc['vat']:,.2f} {calc['currency']}",
        f"",
        f"📋 Таможенный сбор: {calc['fee']:,.0f} ₽",
    ]
    
    if calc["radio_fee"]:
        lines.append(f"📋 Радиосбор: <b>{calc['radio_fee']:,.0f} ₽</b>")
    
    lines.extend([
        f"",
        f"<b>💵 ИТОГО: {calc['total']:,.2f} {calc['currency']}</b>",
    ])
    
    return "\n".join(lines)
