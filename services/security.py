"""
services/security.py — защита: jailbreak, PII, блокировки.
"""
import re
import time
from typing import Tuple, List, Dict, Optional, Set
from config import ADMIN_ID, logger

# --- Blocked users cache ---
_blocked_users: Dict[int, float] = {}
_block_duration = 3600  # 1 hour

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
    "phone": r"\b\+?7[\s\-]?\d{3}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}\b",
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "passport": r"\b\d{4}\s?\d{6}\b(?!\d)",
    "inn": r"\b\d{12}\b",
    "snils": r"\b\d{3}[-\s]?\d{3}[-\s]?\d{3}[-\s]?\d{2}\b",
}

_SUSPICIOUS_THRESHOLD = 3  # количество подозрительных запросов для бана
_suspicious_counts: Dict[int, int] = {}


def full_security_scan(text: str, user_id: int) -> Tuple[bool, str]:
    """
    Полное сканирование сообщения.

    Returns:
        (is_attack, reason): is_attack=True если сообщение отклонено
        reason: строка с причиной ("JAILBREAK", "SUSPICIOUS", "USER_BLOCKED", "")
    """
    # Проверяем, не заблокирован ли пользователь
    if is_blocked(user_id):
        return True, "USER_BLOCKED"

    text_lower = text.lower()

    # Проверка jailbreak
    for pattern in _JAILBREAK_PATTERNS:
        if re.search(pattern, text_lower):
            _suspicious_counts[user_id] = _suspicious_counts.get(user_id, 0) + 1
            if _suspicious_counts[user_id] >= _SUSPICIOUS_THRESHOLD:
                _blocked_users[user_id] = time.time()
                logger.warning(f"User {user_id} blocked for jailbreak attempts")
                return True, "JAILBREAK_BLOCKED"
            return True, "JAILBREAK"

    return False, ""


def is_blocked(user_id: int) -> bool:
    """Проверяет, заблокирован ли пользователь."""
    if user_id == ADMIN_ID:
        return False
    blocked_at = _blocked_users.get(user_id)
    if blocked_at:
        if time.time() - blocked_at < _block_duration:
            return True
        # Разблокируем автоматически
        del _blocked_users[user_id]
    return False


def unblock_user(user_id: int) -> bool:
    """Разблокирует пользователя. Возвращает True если был заблокирован."""
    if user_id in _blocked_users:
        del _blocked_users[user_id]
        _suspicious_counts.pop(user_id, None)
        logger.info(f"User {user_id} unblocked")
        return True
    _suspicious_counts.pop(user_id, None)
    return False


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
