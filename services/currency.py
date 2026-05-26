"""
services/currency.py — курсы валют через MOEX (Московская биржа).
ЦБ РФ недоступен с VDS — используем MOEX API который отдаёт официальные курсы ЦБ.
"""
import asyncio
import json
import urllib.request
from datetime import datetime
from typing import Dict
from config import logger


MOEX_URL = "https://iss.moex.com/iss/statistics/engines/currency/markets/selt/rates.json"

_rates_cache: Dict[str, str] = {}
_cache_ts: float = 0.0
_CACHE_TTL = 60.0


async def get_cbr_rates() -> Dict[str, str]:
    """Получает курсы валют (CNY, USD, EUR) через MOEX API.
    Возвращает официальные курсы ЦБ РФ. Кеширует на 60 секунд.
    """
    global _rates_cache, _cache_ts
    import time
    now = time.monotonic()
    if _rates_cache and (now - _cache_ts) < _CACHE_TTL:
        return _rates_cache

    rates = {"CNY": "н/д", "USD": "н/д", "EUR": "н/д", "DATE": ""}
    try:
        def _fetch():
            with urllib.request.urlopen(MOEX_URL, timeout=10) as resp:
                return resp.read().decode("utf-8")
        text = await asyncio.to_thread(_fetch)
        data = json.loads(text)

        # USD и EUR из курсов ЦБ
        cbrf = data.get("cbrf", {})
        columns = cbrf.get("columns", [])
        rows = cbrf.get("data", [])
        if rows:
            d = dict(zip(columns, rows[0]))
            if d.get("CBRF_USD_LAST"):
                rates["USD"] = str(round(float(d["CBRF_USD_LAST"]), 4))
            if d.get("CBRF_EUR_LAST"):
                rates["EUR"] = str(round(float(d["CBRF_EUR_LAST"]), 4))
            date_str = d.get("CBRF_USD_TRADEDATE", d.get("TODAY_DATE", ""))
            if date_str:
                try:
                    rates["DATE"] = datetime.strptime(date_str[:10], "%Y-%m-%d").strftime("%d.%m.%Y")
                except ValueError:
                    rates["DATE"] = date_str[:10]

        # CNY из биржевых торгов (CNYRUB_TOM)
        wap = data.get("wap_rates", {})
        wap_cols = wap.get("columns", [])
        for wrow in wap.get("data", []):
            wd = dict(zip(wap_cols, wrow))
            if wd.get("secid") == "CNYRUB_TOM" and wd.get("price"):
                rates["CNY"] = str(round(float(wd["price"]), 4))
                break

        logger.info(f"Курсы MOEX: USD={rates['USD']}, EUR={rates['EUR']}, CNY={rates['CNY']}, DATE={rates['DATE']}")
        _rates_cache = rates
        _cache_ts = now

    except Exception as e:
        logger.error(f"Ошибка получения курсов MOEX: {e}")
        if _rates_cache:
            logger.info("Возвращаем кешированные курсы")
            return _rates_cache

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
