"""
config.py — конфигурация бота, ENV, логгер.
"""
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Загрузка .env
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# Версия
VERSION = "2.1.0"

# --- API Keys ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")

# --- Admin ---
ADMIN_ID = int(os.getenv("ADMIN_ID", "0")) if os.getenv("ADMIN_ID") else 0

# --- Database ---
DB_PATH = os.getenv("DB_PATH", "data/bot.db")

# --- Rate Limit ---
RATE_LIMIT_SECONDS = int(os.getenv("RATE_LIMIT_SECONDS", "3"))
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "20"))

# --- Customs Fees ---
RADIO_FEE = 73860  # Фиксированный сбор за радиоэлектронику (ПП РФ №1637 ред. №1638, с 01.01.2026)
CUSTOMS_FEE_RUB = {
    # Шкала таможенных сборов (ПП РФ №1637 в ред. №1638, действует с 01.01.2026)
    200_000:    1_231,
    450_000:    2_462,
    1_200_000:  4_924,
    2_700_000:  13_541,
    4_200_000:  18_465,
    5_500_000:  21_344,
    10_000_000: 49_240,
    # свыше 10 млн → 73 860 (совпадает с RADIO_FEE, обрабатывается как fallback в calculate_customs_fee)
}

# --- Radio Electronics Groups ---
_RADIO_GROUPS = {"85", "84", "90", "91", "92"}
RADIO_ELECTRONICS_CODES_SET = set()  # Заполняется из БД + custom codes

# --- TNVED Full Names Cache ---
TNVED_FULL_NAMES: dict = {}

# --- Currency ---
CURRENCY_SYNONYMS = {
    "юан": "CNY", "юань": "CNY", "юаней": "CNY", "rmb": "CNY", "yuan": "CNY", "¥": "CNY",
    "доллар": "USD", "бакс": "USD", "usd": "USD", "$": "USD",
    "евро": "EUR", "eur": "EUR", "€": "EUR",
    "рубль": "RUB", "руб": "RUB", "₽": "RUB",
}

# --- Learn Mode State ---
LEARN_MODE: dict = {}

# --- Pending Code Update ---
PENDING_CODE_UPDATE: dict = {}

# --- System Prompt ---
SYSTEM_PROMPT = (
    "Ты — AI-помощник компании West Asia, эксперт по ВЭД и логистике. "
    "Отвечай на русском языке, кратко и по делу. "
    "Используй форматирование (жирный, списки) для удобства чтения."
)

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("wa_bot")
