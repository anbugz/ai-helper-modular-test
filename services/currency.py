"""
services/currency.py — работа с курсами ЦБ РФ.
TODO: перенести из utils.py
"""
import logging
from typing import Dict

logger = logging.getLogger(__name__)

async def get_cbr_rates() -> Dict[str, float]:
    """Получение курсов ЦБ РФ."""
    return {"USD": 90.0, "EUR": 98.0, "CNY": 12.5}
