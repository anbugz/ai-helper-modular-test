"""
services/tnved.py — работа с ТН ВЭД.
TODO: перенести из tnved_engine.py
"""
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# TODO: перенести кэш, поиск, радиоэлектроника из tnved_engine.py

RADIO_CODES = {
    "8471", "8517", "8521", "8525", "8527", "8528", "8529",
    "8530", "8531", "8532", "8533", "8534", "8535", "8536",
    "8537", "8538", "8539", "8540", "8541", "8542", "8543",
    "8544", "8545", "8546", "8547", "8548", "8549", "9006",
    "9007", "9008", "9009", "9010", "9011", "9012", "9013",
    "9014", "9015", "9016", "9017", "9018", "9019", "9020",
    "9021", "9022", "9023", "9024", "9025", "9026", "9027",
    "9028", "9029", "9030", "9031", "9032", "9033",
}

def is_radio_electronics(code: str) -> bool:
    """Проверяет, относится ли код к радиоэлектронике."""
    prefix = code[:4] if len(code) >= 4 else code
    return prefix in RADIO_CODES


def search_tnved(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Поиск кода ТН ВЭД по запросу.
    TODO: полная реализация из tnved_engine.py
    """
    # TODO: подключить кэш БД, fuzzy search, MATERIAL_MAP
    logger.info(f"TNVED search: {query}")
    return []
