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

# --- Whitelist (доступ к боту) ---
# В .env: ALLOWED_USERS=123456789,987654321
# Если пусто — бот доступен всем (не рекомендуется).
_allowed_raw = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS: set = (
    {int(x.strip()) for x in _allowed_raw.split(",") if x.strip().isdigit()}
    if _allowed_raw else set()
)
if ADMIN_ID:
    ALLOWED_USERS.add(ADMIN_ID)  # Админ всегда в whitelist

# --- Rate limit ---
# Макс. запросов в минуту на пользователя (0 = без ограничений)
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))

# --- Database ---
DB_PATH = os.getenv("DB_PATH", "data/bot.db")

# --- Rate Limit ---
RATE_LIMIT_SECONDS = int(os.getenv("RATE_LIMIT_SECONDS", "3"))
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "20"))

# --- Customs Fees ---
RADIO_FEE = 73860  # Фиксированный сбор за радиоэлектронику
CUSTOMS_FEE_RUB = {
    200_000: 500,
    450_000: 1000,
    1_200_000: 2000,
    2_700_000: 5500,
    4_200_000: 7500,
    5_500_000: 12_000,
    7_000_000: 15_500,
    8_000_000: 20_000,
    9_000_000: 23_000,
    10_000_000: 30_000,
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
