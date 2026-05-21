"""
services/calc.py — расчёт ВЭД-платежей, форматирование ответа.
"""
import re
from typing import Dict, Optional
from config import RADIO_FEE, logger
from services.currency import convert_fee_to_currency


def _strip_deepseek_dup(text: str) -> str:
    """Удаляет дублирование ответов DeepSeek (когда модель повторяет свой ответ)."""
    lines = text.split("\n")
    seen = set()
    result = []
    for line in lines:
        key = line.strip().lower()
        if key and key in seen:
            continue
        seen.add(key)
        result.append(line)
    return "\n".join(result)


def _strip_ai_assistant_junk(text: str) -> str:
    """Очищает ответ от markdown-таблиц и служебных фраз."""
    # Удаляем markdown-таблицы
    lines = text.split("\n")
    clean_lines = []
    in_table = False
    for line in lines:
        if "|" in line and "---" in line:
            in_table = True
            continue
        if in_table and "|" in line:
            continue
        if in_table and "|" not in line:
            in_table = False
        clean_lines.append(line)
    
    text = "\n".join(clean_lines)
    
    # Удаляем приписки от AI
    junk_phrases = [
        r"As an AI.*?(\n|$)",
        r"Я — искусственный интеллект.*?(\n|$)",
        r"I apologize, but.*?(\n|$)",
        r"Прошу прощения.*?(\n|$)",
    ]
    for phrase in junk_phrases:
        text = re.sub(phrase, "", text, flags=re.IGNORECASE)
    
    return text.strip()


def format_calculation_fallback(
    code: str,
    name: str,
    currency: str,
    rates: Dict[str, str],
    tariff_info: Optional[Dict],
    is_radio: bool,
    customs_fee_rub: float,
    vat_rate: float,
    ts_fallback: float,
    ts_components: Dict,
    weight_kg: Optional[float] = None,
) -> str:
    """
    Форматирует ВЭД-расчёт в виде чистого текстового ответа.
    
    Args:
        code: Код ТН ВЭД
        name: Наименование товара
        currency: Валюта инвойса (CNY/USD/EUR/RUB)
        rates: Курсы ЦБ
        tariff_info: Информация о тарифе
        is_radio: Радиоэлектроника
        customs_fee_rub: Таможенный сбор в рублях
        vat_rate: Ставка НДС (0.22 или 0.10)
        ts_fallback: Таможенная стоимость
        ts_components: Компоненты ТС
        weight_kg: Вес в кг
    
    Returns:
        Форматированный текст расчёта
    """
    lines = []
    
    # Шапка
    lines.append(f"📋 <b>Код ТН ВЭД:</b> <code>{code}</code>")
    if name:
        lines.append(f"🔧 {name}")
    
    # Тариф
    if tariff_info:
        pt = tariff_info.get("parsed_tariff", {})
        tariff_str = tariff_info.get("tariff", "")
        if pt.get("type") in ("min", "plus", "fixed_eur"):
            lines.append(f"💰 <b>Пошлина:</b> {tariff_str} — комбинированная ({pt.get('formula', '')})")
        elif pt.get("type") == "percent":
            lines.append(f"💰 <b>Пошлина:</b> {tariff_str} — адвалорная")
        else:
            lines.append(f"💰 <b>Пошлина:</b> {tariff_str}")
    
    # НДС
    vat_str = "10% (льготная)" if vat_rate == 0.10 else "22% (базовая)"
    lines.append(f"🧾 <b>НДС:</b> {vat_str}")
    
    # Радиосбор
    if is_radio:
        _, fee_display = convert_fee_to_currency(RADIO_FEE, currency or "RUB", rates)
        lines.append(f"⚡ <b>Радиосбор:</b> {fee_display}")
    
    # Таможенная стоимость
    if ts_fallback:
        lines.append("")
        lines.append(f"📊 <b>Таможенная стоимость:</b> {ts_fallback:,.2f} {currency}")
        
        # Компоненты ТС
        for key, label in [("invoice", "Инвойс"), ("freight", "Фрахт"), ("insurance", "Страховка")]:
            if key in ts_components:
                comp = ts_components[key]
                val = comp.get("value", 0)
                cur = comp.get("currency", currency)
                rate_info = comp.get("rate")
                if rate_info:
                    lines.append(f"   • {label}: {val:,.2f} {cur} ({rate_info})")
                else:
                    lines.append(f"   • {label}: {val:,.2f} {cur}")
        
        if weight_kg:
            lines.append(f"   • Вес: {weight_kg:,.2f} кг")
    
    # Таможенный сбор
    if customs_fee_rub:
        _, fee_display = convert_fee_to_currency(customs_fee_rub, currency or "RUB", rates)
        lines.append("")
        lines.append(f"🏛 <b>Таможенный сбор:</b> {fee_display}")
    
    # Итоговый расчёт (если есть пошлина)
    if tariff_info and ts_fallback:
        pt = tariff_info.get("parsed_tariff", {})
        if pt.get("type") == "percent" and pt.get("value"):
            duty_pct = pt["value"] / 100
            duty_val = ts_fallback * duty_pct
            vat_val = (ts_fallback + duty_val) * vat_rate
            
            duty_conv, duty_disp = convert_fee_to_currency(duty_val, currency or "RUB", rates)
            vat_conv, vat_disp = convert_fee_to_currency(vat_val, currency or "RUB", rates)
            
            lines.append("")
            lines.append(f"📊 <b>Расчёт платежей:</b>")
            lines.append(f"   • Пошлина ({pt['value']}%): {duty_disp}")
            lines.append(f"   • НДС ({int(vat_rate * 100)}%): {vat_disp}")
            
            if customs_fee_rub:
                total = duty_val + vat_val + customs_fee_rub
            else:
                total = duty_val + vat_val
            total_conv, total_disp = convert_fee_to_currency(total, currency or "RUB", rates)
            lines.append(f"   • <b>Итого к оплате:</b> {total_disp}")
    
    lines.append("")
    lines.append("📌 <i>Точную информацию уточняйте у декларанта.</i>")
    
    return "\n".join(lines)


# Aliases для совместимости (публичные — импортируются извне)
strip_ai_assistant_junk = _strip_deepseek_dup
_strip_ai_assistant_junk = _strip_deepseek_dup  # backward compat
_format_calculation_fallback = format_calculation_fallback
