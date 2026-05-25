"""
services/security.py — защита: jailbreak, PII, блокировки.
Блокировки хранятся в SQLite через database.py (переживают рестарт).
"""
import re
from typing import Tuple, List
from config import ADMIN_ID, logger

# --- Suspicious patterns ---
_JAILBREAK_PATTERNS = [
    r"ignore previous instructions",
    r"игнорируй (предыдущие|все) инструкции",
    r"ты теперь .{0,50}?(не|без).{0,30}?(ограничений|лимитов|правил)",
    r"pretend to be",
    r"притворись",
    r"отойди от роли",
    r"забудь (про|что ты)",
    r"ты .{0,30}? не .{0,30}? бот",
    r"DAN mode",
    r"jailbreak",
    r"обход",
    r"взлом",
]

_PII_PATTERNS = {
    "phone":    r"\+?7[\s\-]?\d{3}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}",
    "email":    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    "passport": r"\d{4}\s?\d{6}",
    "inn":      r"\d{12}",
    "snils":    r"\d{3}\s?\d{3}\s?\d{3}\s?\d{2}",
}

_SUSPICIOUS_THRESHOLD = 3
_BLOCK_DURATION = 3600.0  # секунды


def full_security_scan(text: str, user_id: int) -> Tuple[bool, str]:
    """
    Полное сканирование сообщения.

    Returns:
        (is_attack, reason): is_attack=True если сообщение отклонено.
        reason: "JAILBREAK", "JAILBREAK_BLOCKED", "USER_BLOCKED" или "".
    """
    from database import db_is_blocked, db_block_user, db_increment_suspicious

    # Администратор никогда не блокируется
    if user_id == ADMIN_ID:
        return False, ""

    if db_is_blocked(user_id, _BLOCK_DURATION):
        return True, "USER_BLOCKED"

    text_lower = text.lower()
    for pattern in _JAILBREAK_PATTERNS:
        if re.search(pattern, text_lower):
            new_count = db_increment_suspicious(user_id)
            if new_count >= _SUSPICIOUS_THRESHOLD:
                db_block_user(user_id, reason="jailbreak")
                return True, "JAILBREAK_BLOCKED"
            return True, "JAILBREAK"

    return False, ""


def is_blocked(user_id: int) -> bool:
    """Публичная проверка блокировки (используется в хендлерах)."""
    if user_id == ADMIN_ID:
        return False
    from database import db_is_blocked
    return db_is_blocked(user_id, _BLOCK_DURATION)


def unblock_user(user_id: int) -> bool:
    """Разблокирует пользователя. Возвращает True если был заблокирован."""
    from database import db_unblock_user
    return db_unblock_user(user_id)


def contains_pii(text: str) -> Tuple[bool, List[str]]:
    """Проверяет наличие персональных данных в тексте."""
    found_types = []
    for pii_type, pattern in _PII_PATTERNS.items():
        if re.search(pattern, text):
            found_types.append(pii_type)
    return bool(found_types), found_types


def redact_pii(text: str) -> str:
    """Заменяет PII на [REDACTED]."""
    result = text
    for pii_type, pattern in _PII_PATTERNS.items():
        result = re.sub(pattern, f"[{pii_type.upper()}_REDACTED]", result)
    return result
