"""
services/currency.py — курсы ЦБ РФ, конвертация, форматирование.
Перенос из utils.py (get_cbr_rates, format_cross_rates, convert_fee_to_currency).
"""
import asyncio
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict
from config import logger


CBR_URL = "https://www.cbr.ru/scripts/XML_daily.asp"


async def get_cbr_rates() -> Dict[str, str]:
    """Получает курсы ЦБ РФ (CNY, USD, EUR) и дату.
    
    Returns:
        {"CNY": "12.3456", "USD": "90.1234", "EUR": "98.7654", "DATE": "21.05.2026"}
    """
    rates = {"CNY": "н/д", "USD": "н/д", "EUR": "н/д", "DATE": ""}
    try:
        def _fetch():
            with urllib.request.urlopen(CBR_URL, timeout=15) as resp:
                return resp.read().decode("windows-1251")
        xml_text = await asyncio.to_thread(_fetch)
        root = ET.fromstring(xml_text)
        date_attr = root.get("Date", "")
        rates["DATE"] = date_attr
        for valute in root.findall("Valute"):
            char_code = valute.findtext("CharCode", "")
            value = valute.findtext("Value", "").replace(",", ".")
            nominal = int(valute.findtext("Nominal", "1"))
            if char_code in ("CNY", "USD", "EUR"):
                try:
                    rates[char_code] = str(round(float(value) / nominal, 4))
                except ValueError:
                    pass
    except Exception as e:
        logger.error(f"Ошибка получения курсов ЦБ: {e}")
    return rates


def format_cross_rates(rates: Dict[str, str]) -> str:
    """Форматирует кросс-курсы для отображения.
    
    Example: "CNY/USD=0.1370, CNY/EUR=0.1250, USD/EUR=0.9123"
    """
    parts = []
    try:
        cny = float(rates.get("CNY", 0))
        usd = float(rates.get("USD", 0))
        eur = float(rates.get("EUR", 0))
        if cny and usd:
            parts.append(f"CNY/USD={round(cny/usd, 4)}")
        if cny and eur:
            parts.append(f"CNY/EUR={round(cny/eur, 4)}")
        if usd and eur:
            parts.append(f"USD/EUR={round(usd/eur, 4)}")
    except (ValueError, ZeroDivisionError):
        pass
    return ", ".join(parts) if parts else "н/д"


def convert_fee_to_currency(fee_rub: float, currency: str, rates: Dict[str, str]) -> tuple:
    """Конвертирует сбор из рублей в валюту инвойса.
    
    Returns:
        (fee_in_currency, display_string)
    
    Example:
        convert_fee_to_currency(1231, "CNY", rates) -> (13.45, "1 231 ₽ → 13.45 CNY")
    """
    if fee_rub <= 0:
        return 0.0, "0 ₽"
    if currency == "RUB" or not rates:
        return fee_rub, f"{fee_rub:,.0f} ₽"
    if currency in rates:
        try:
            rate_val = float(rates[currency])
            if rate_val > 0:
                fee_cur = round(fee_rub / rate_val, 2)
                return fee_cur, f"{fee_rub:,.0f} ₽ → {fee_cur:,.2f} {currency}"
        except (ValueError, TypeError, ZeroDivisionError):
            pass
    return fee_rub, f"{fee_rub:,.0f} ₽"


def detect_base_currency(text: str) -> str:
    """Определяет базовую валюту из текста запроса.
    
    Returns:
        "CNY", "USD", "EUR" или "RUB" (по умолчанию)
    """
    from config import CURRENCY_SYNONYMS
    
    text_lower = text.lower()
    for synonym, code in CURRENCY_SYNONYMS.items():
        if synonym in text_lower:
            return code
    text_upper = text.upper()
    for c in ("CNY", "USD", "EUR", "RUB"):
        if c in text_upper:
            return c
    if "юан" in text_lower or "китайск" in text_lower or "rmb" in text_lower:
        return "CNY"
    if "доллар" in text_lower or "бакс" in text_lower or "$" in text:
        return "USD"
    if "евро" in text_lower or "€" in text:
        return "EUR"
    return "RUB"
