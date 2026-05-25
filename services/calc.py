"""
services/calc.py — расчёт ВЭД-платежей, форматирование ответа.
"""
import re
from typing import Dict, Optional
from config import RADIO_FEE, logger
from services.currency import convert_fee_to_currency


def _strip_deepseek_dup(text: str) -> str:
    """Удаляет дублирование ответов DeepSeek."""
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
    Формат как в legacy-боте:
    1. Шапка (код, пошлина, НДС, сбор в ₽)
    2. Конвертация в валюту инвойса
    3. Итоговая таблица с ИТОГО
    """
    lines = []
    
    # === 1. ШАПКА ===
    lines.append(f"📋 Код: <code>{code}</code>")
    if name:
        lines.append(f"🔧 {name}")
    
    if tariff_info:
        pt = tariff_info.get("parsed_tariff", {})
        tariff_str = tariff_info.get("tariff", "")
        if pt.get("type") == "percent":
            lines.append(f"💰 <b>Пошлина:</b> {tariff_str} — адвалорная")
        elif pt.get("type") in ("min", "plus", "fixed_eur"):
            lines.append(f"💰 <b>Пошлина:</b> {tariff_str} — комбинированная ({pt.get('formula', '')})")
        else:
            lines.append(f"💰 <b>Пошлина:</b> {tariff_str}")
    
    vat_pct = int(vat_rate * 100)
    lines.append(f"🧾 <b>НДС:</b> {vat_pct}% (базовая)")
    
    # Сбор в рублях (как в старом боте)
    if customs_fee_rub:
        if is_radio:
            lines.append(f"⚡ <b>РАДИОСБОР:</b> {customs_fee_rub:,.0f} ₽ (фиксированный)")
        else:
            lines.append(f"⚡ <b>Сбор:</b> {customs_fee_rub:,.0f} ₽ (по шкале ПП РФ №1637)")
    
    lines.append("")
    
    # === 2. КОНВЕРТАЦИЯ В ВАЛЮТУ ИНВОЙСА ===
    lines.append(f"🔄 <b>Конвертация в валюту инвойса ({currency}):</b>")
    
    # Инвойс
    if "invoice" in ts_components:
        inv = ts_components["invoice"]
        val = inv.get("value", 0)
        cur = inv.get("currency", currency)
        if cur == currency:
            lines.append(f"• Инвойс: {val:,.2f} {currency} — уже в валюте инвойса")
        else:
            conv = inv.get("converted", val)
            rate_info = inv.get("rate", "")
            lines.append(f"• Инвойс: {val:,.2f} {cur} → {conv:,.2f} {currency} {rate_info}")
    
    # Фрахт
    if "freight" in ts_components:
        fr = ts_components["freight"]
        val = fr.get("value", 0)
        cur = fr.get("currency", currency)
        conv = fr.get("converted", val)
        rate_info = fr.get("rate", "")
        if cur == currency:
            lines.append(f"• Фрахт: {val:,.2f} {currency}")
        else:
            lines.append(f"• Фрахт: {val:,.2f} {cur} → {conv:,.2f} {currency} {rate_info}")
    
    # Страховка
    if "insurance" in ts_components:
        ins = ts_components["insurance"]
        val = ins.get("value", 0)
        cur = ins.get("currency", currency)
        conv = ins.get("converted", val)
        rate_info = ins.get("rate", "")
        if cur == currency:
            lines.append(f"• Страховка: {val:,.2f} {currency}")
        else:
            lines.append(f"• Страховка: {val:,.2f} {cur} → {conv:,.2f} {currency} {rate_info}")
    
    lines.append("")
    
    # === 3. ИТОГОВЫЙ РАСЧЁТ (таблица) ===
    if ts_fallback and tariff_info:
        pt = tariff_info.get("parsed_tariff", {})
        tariff_type = pt.get("type", "")
        ad_val_pct = pt.get("value", 0) / 100   # адвалорный % (всегда проценты)
        eur_per_kg = pt.get("eur_per_kg", 0)     # евро/кг (для min/plus/fixed_eur)

        # Адвалорная часть (% от ТС)
        duty_adval = ts_fallback * ad_val_pct

        # Евро-составляющая: переводим EUR → валюта инвойса
        duty_eur_component = 0.0
        eur_in_cur_str = ""
        if eur_per_kg and weight_kg:
            eur_amount = eur_per_kg * weight_kg  # итого EUR
            if currency == "EUR":
                duty_eur_component = eur_amount
            elif "EUR" in rates and currency in rates:
                try:
                    eur_rub = eur_amount * float(rates["EUR"])
                    duty_eur_component = round(eur_rub / float(rates[currency]), 2)
                except (ValueError, TypeError, ZeroDivisionError):
                    duty_eur_component = eur_amount
            elif "EUR" in rates:
                try:
                    duty_eur_component = eur_amount * float(rates["EUR"])
                except (ValueError, TypeError):
                    duty_eur_component = eur_amount
            eur_in_cur_str = f"{eur_per_kg} €/кг × {weight_kg:.0f} кг = {eur_amount:.2f} EUR → {duty_eur_component:,.2f} {currency}"

        # Итоговая пошлина зависит от типа ставки
        if tariff_type == "min":
            # MAX(адвалорная, евро/кг × вес)
            duty_val = max(duty_adval, duty_eur_component)
            duty_method = "адвалорная" if duty_adval >= duty_eur_component else "минимальная (евро/кг)"
        elif tariff_type == "plus":
            # адвалорная + евро/кг × вес
            duty_val = duty_adval + duty_eur_component
            duty_method = "адвалорная + евро/кг"
        elif tariff_type == "fixed_eur":
            # только евро/кг × вес
            duty_val = duty_eur_component
            duty_method = "фиксированная (евро/кг)"
        else:
            # простой процент
            duty_val = duty_adval
            duty_method = "адвалорная"
        vat_val = (ts_fallback + duty_val) * vat_rate
        
        # Сбор сконвертированный в валюту инвойса
        fee_in_cur = 0.0
        fee_display = ""
        if customs_fee_rub:
            fee_in_cur, fee_display = convert_fee_to_currency(
                customs_fee_rub, currency or "RUB", rates
            )
        
        total_cur = duty_val + vat_val + fee_in_cur
        
        # Итого в рублях
        total_rub = 0.0
        if currency in rates:
            try:
                rate_val = float(rates[currency])
                total_rub = total_cur * rate_val
            except (ValueError, TypeError):
                pass
        
        lines.append("📊 <b>Итоговый расчёт</b>")
        lines.append(f"💰 Таможенная стоимость:  {ts_fallback:>12,.2f} {currency}")
        duty_pct_display = int(ad_val_pct * 100) if ad_val_pct else 0
        lines.append(f"💰 Пошлина ({duty_method}):")
        if tariff_type in ("min", "plus") and eur_per_kg and weight_kg:
            lines.append(f"   • адвалорная {duty_pct_display}%: {duty_adval:>10,.2f} {currency}")
            lines.append(f"   • евро/кг:  {eur_in_cur_str}")
            if tariff_type == "min":
                lines.append(f"   • итого (MAX): {duty_val:>10,.2f} {currency}")
            else:
                lines.append(f"   • итого (+): {duty_val:>12,.2f} {currency}")
        elif tariff_type == "fixed_eur" and eur_per_kg and weight_kg:
            lines.append(f"   • {eur_in_cur_str}")
            lines.append(f"   • итого: {duty_val:>16,.2f} {currency}")
        else:
            lines.append(f"{'':>26} {duty_val:>12,.2f} {currency}")
        lines.append(f"🧾 НДС {vat_pct}%:{'':>17} {vat_val:>12,.2f} {currency}")
        
        if fee_in_cur > 0:
            fee_str = f"{fee_in_cur:>12,.2f} {currency}"
            if "→" in fee_display:
                rub_part = fee_display.split("→")[0].strip()
                fee_str += f" ({rub_part} → {fee_in_cur:,.2f} {currency})"
            fee_label = "РАДИОСБОР" if is_radio else "Сбор"
            padding = 22 - len(fee_label)
            lines.append(f"⚡ {fee_label}:{'':>{padding}} {fee_str}")
        
        lines.append("—" * 35)
        
        row_total = f"<b>ИТОГО:</b>{'':>18} {total_cur:>12,.2f} {currency}"
        if total_rub > 0:
            row_total += f" (~ {total_rub:>12,.2f} ₽)"
        lines.append(f"💰 {row_total}")
    
    lines.append("")
    lines.append("📌 <i>Точную информацию уточняйте у декларанта.</i>")
    
    return "\n".join(lines)


# Aliases для совместимости
strip_ai_assistant_junk = _strip_deepseek_dup
_strip_ai_assistant_junk = _strip_deepseek_dup
_format_calculation_fallback = format_calculation_fallback
