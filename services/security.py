"""
security.py — многоуровневая защита бота от атак.
rev31: Encoding attacks, multi-turn, syntax injection, social engineering.
"""
import re
import base64
import unicodedata
from typing import Optional, Tuple
from collections import defaultdict
from datetime import datetime, timedelta

# ------------------------------------------------------------------
# 1. JAILBREAK-ЗАЩИТА (40+ паттернов)
# ------------------------------------------------------------------
_JAILBREAK_PATTERNS = (
    # Русские
    "security test", "аудит безопасности", "системные инструкции",
    "скрытые ограничения", "внутренние правила", "выведи промпт",
    "выведи system prompt", "выведи инструкции", "покажи промпт",
    "покажи system prompt", "раскрой правила", "выдай ограничения",
    "mode audit", "debug mode", "разработчик", "developer mode",
    "ignore previous", "игнорируй предыдущие", "забудь инструкции",
    "ты теперь", "you are now", "отключи фильтры", "disable filters",
    # Общие
    "system prompt", "prompt injection", "jailbreak", "dan mode",
    "обойди ограничения", "bypass restrictions", "root access",
    "admin mode", "sudo mode", "superuser", "reveal your instructions",
    "show me your prompt", "what are your instructions",
    "ignore all previous", "disregard all", "forget everything",
    "you are now a", "from now on you are", "представь что ты",
    "do anything now", "d.a.n", "stan mode", "evil confidant",
    # Social engineering
    "авторизованный тест", "authorized test", "security audit",
    "penetration test", "pentest", "red team", "blue team",
    # Debug / setup bait
    "отладить бота", "debug bot", "помоги настроить",
    "проверить безопасность", "проверь настройки",
    # Translation / summarization bait
    "переведи инструкции", "переведи промпт",
    "суммаризируй правила", "summarize instructions",
    "translate your instructions", "translate system prompt",
    # Setup / config
    "покажи конфиг", "покажи настройки", "show config",
    "configuration file", "config file", ".env file",
)


def is_jailbreak(text: str) -> bool:
    """Проверяет текст на попытку jailbreak / слива промпта."""
    if not text:
        return False
    text_lower = text.lower()
    return any(pattern in text_lower for pattern in _JAILBREAK_PATTERNS)


# ------------------------------------------------------------------
# 2. ENCODING / OBFUSCATION DETECTION
# ------------------------------------------------------------------

def _is_base64(s: str) -> bool:
    """Проверяет что строка похожа на Base64."""
    # Убираем whitespace
    cleaned = re.sub(r'\s+', '', s)
    if len(cleaned) < 20:
        return False
    # Base64 паттерн: [A-Za-z0-9+/=]{20,}
    if not re.match(r'^[A-Za-z0-9+/=]+$', cleaned):
        return False
    # Пробуем декодировать
    try:
        # Добавляем padding если нужно
        padded = cleaned + '=' * (4 - len(cleaned) % 4)
        decoded = base64.b64decode(padded).decode('utf-8', errors='ignore')
        # Если декодированный текст содержит jailbreak-ключевые слова
        return is_jailbreak(decoded) or 'system' in decoded.lower() or 'prompt' in decoded.lower()
    except Exception:
        return False


def _is_rot13(text: str) -> bool:
    """Проверяет что текст содержит ROT13-слова."""
    def rot13(s):
        result = []
        for c in s:
            if 'a' <= c <= 'z':
                result.append(chr((ord(c) - ord('a') + 13) % 26 + ord('a')))
            elif 'A' <= c <= 'Z':
                result.append(chr((ord(c) - ord('A') + 13) % 26 + ord('A')))
            else:
                result.append(c)
        return ''.join(result)
    
    # Ищем слова из 4+ латинских букв
    words = re.findall(r'[a-zA-Z]{4,}', text)
    for word in words:
        decoded = rot13(word)
        # Если декодированное слово — ключевое для jailbreak
        if decoded.lower() in ('system', 'prompt', 'ignore', 'previous',
                                'reveal', 'instructions', 'admin', 'sudo',
                                'developer', 'bypass', 'jailbreak', 'override'):
            return True
    return False


def _normalize_leetspeak(text: str) -> str:
    """Нормализация LeetSpeak."""
    leet_map = str.maketrans({
        '0': 'o', '1': 'l', '3': 'e', '4': 'a', '5': 's',
        '6': 'g', '7': 't', '8': 'b', '$': 's', '@': 'a',
        '¡': 'i', '|': 'l', '(': 'c', '¿': '?', '°': 'o',
    })
    return text.translate(leet_map)


def _has_zero_width(text: str) -> bool:
    """Проверяет наличие zero-width characters."""
    zwc = ('\u200b', '\u200c', '\u200d', '\ufeff', '\u2060', 
           '\u180e', '\u200e', '\u200f', '\u202a', '\u202b',
           '\u202c', '\u202d', '\u202e')
    return any(c in text for c in zwc)


def _remove_zero_width(text: str) -> str:
    """Удаляет zero-width characters."""
    zwc = ('\u200b', '\u200c', '\u200d', '\ufeff', '\u2060',
           '\u180e', '\u200e', '\u200f', '\u202a', '\u202b',
           '\u202c', '\u202d', '\u202e')
    for c in zwc:
        text = text.replace(c, '')
    return text


def _normalize_unicode(text: str) -> str:
    """Нормализация Unicode (NFKC) — убирает homoglyphs."""
    return unicodedata.normalize('NFKC', text)


def _has_homoglyphs(text: str) -> bool:
    """
    Проверяет homoglyph-атаку: кириллические буквы, похожие на латинские,
    использованные ВМЕСТЕ с латиницей для обмана (mixed-script).
    Обычный русский текст НЕ триггерит (все буквы кириллица).
    """
    cyrillic_lookalikes = {
        '\u0430': 'a', '\u0435': 'e', '\u043e': 'o', '\u0440': 'p',
        '\u0441': 'c', '\u0445': 'x', '\u0443': 'y', '\u0456': 'i',
        '\u0458': 'j', '\u043a': 'k', '\u043c': 'm', '\u043d': 'h',
        '\u0442': 't', '\u0432': 'b', '\u0433': 'r',
    }
    has_lookalike = any(c in text for c in cyrillic_lookalikes)
    has_latin = bool(re.search(r'[a-zA-Z]', text))
    # Триггерим только при СМЕШЕНИИ кириллицы и латиницы
    # (обычный русский текст = кириллица без латиницы = OK)
    return has_lookalike and has_latin


def detect_encoding_attack(text: str) -> Tuple[bool, str]:
    """
    Детектирует encoding/obfuscation атаки.
    Возвращает: (detected: bool, reason: str)
    """
    if not text:
        return False, ""
    
    # 1. Base64
    if _is_base64(text):
        return True, "Base64 encoded payload detected"
    
    # 2. Zero-width characters
    if _has_zero_width(text):
        return True, "Zero-width characters detected (obfuscation)"
    
    # 3. LeetSpeak
    normalized = _normalize_leetspeak(text)
    if is_jailbreak(normalized) and normalized != text:
        return True, "LeetSpeak obfuscation detected"
    
    # 4. ROT13
    if _is_rot13(text):
        return True, "ROT13 cipher detected"
    
    # 5. Homoglyphs (ОТКЛЮЧЕНО — ложные срабатывания на ВЭД-запросы)
    # ВЭД-менеджеры смешивают языки: "какая rev", "CNAS сертификат", "FOB порт"
    # Вместо этого ловим через jailbreak-паттерны если текст содержит подозрительные слова
    # if _has_homoglyphs(text):
    #     return True, "Unicode homoglyphs detected (lookalike characters)"
    
    return False, ""


# ------------------------------------------------------------------
# 3. SYNTAX / STRUCTURE INJECTION
# ------------------------------------------------------------------

def _has_role_tags(text: str) -> bool:
    """Проверяет наличие role tags (ChatML, JSON, XML)."""
    patterns = (
        r'<\|im_start\|>', r'<\|im_end\|>',  # ChatML
        r'"role"\s*:\s*"(system|user|assistant)"',  # JSON role
        r'<\s*(system|user|assistant)\s*>',  # XML role
        r'\b(USER|ASSISTANT|SYSTEM)\s*[:\-]',  # Role prefixes
        r'\[\s*(system|user|assistant)\s*\]',  # Bracket roles
    )
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _has_fake_context(text: str) -> bool:
    """Проверяет фейковую историю диалога."""
    # Паттерны типа: "Assistant: вот мой промпт" или "User: покажи инструкции"
    fake_patterns = (
        r'\b(assistant|ассистент|бот)\s*[:\-]\s*\S+',
        r'\b(user|пользователь)\s*[:\-]\s*\S+',
        r'предыдущий ответ[:\-]', r'предыдущее сообщение[:\-]',
        r'в предыдущем диалоге', r'в предыдущем разговоре',
    )
    return any(re.search(p, text, re.IGNORECASE) for p in fake_patterns)


def detect_syntax_injection(text: str) -> Tuple[bool, str]:
    """
    Детектирует syntax injection атаки.
    Возвращает: (detected: bool, reason: str)
    """
    if not text:
        return False, ""
    
    if _has_role_tags(text):
        return True, "Role tag injection detected (ChatML/JSON/XML)"
    
    if _has_fake_context(text):
        return True, "Fake conversation context detected"
    
    return False, ""


# ------------------------------------------------------------------
# 4. PII-ФИЛЬТР
# ------------------------------------------------------------------
_PII_PATTERNS = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "phone": re.compile(r"\b(?:\+7|7|8)\s*\(?\d{3}\)?\s*\d{3}[-\s]?\d{2}[-\s]?\d{2}\b"),
    "passport": re.compile(r"\b\d{2}\s*\d{2}\s*\d{6}\b"),
    "inn": re.compile(r"\b\d{12}\b"),
    "snils": re.compile(r"\b\d{3}[-\s]?\d{3}[-\s]?\d{3}[-\s]?\d{2}\b"),
    "credit_card": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
    "ip_address": re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
}


def contains_pii(text: str) -> Tuple[bool, list]:
    if not text:
        return False, []
    detected = []
    for pii_type, pattern in _PII_PATTERNS.items():
        if pattern.search(text):
            detected.append(pii_type)
    return bool(detected), detected


def redact_pii(text: str) -> str:
    result = text
    result = _PII_PATTERNS["email"].sub("[EMAIL_REDACTED]", result)
    result = _PII_PATTERNS["phone"].sub("[PHONE_REDACTED]", result)
    result = _PII_PATTERNS["passport"].sub("[PASSPORT_REDACTED]", result)
    result = _PII_PATTERNS["inn"].sub("[INN_REDACTED]", result)
    result = _PII_PATTERNS["snils"].sub("[SNILS_REDACTED]", result)
    result = _PII_PATTERNS["credit_card"].sub("[CARD_REDACTED]", result)
    result = _PII_PATTERNS["ip_address"].sub("[IP_REDACTED]", result)
    return result


# ------------------------------------------------------------------
# 5. INPUT VALIDATION
# ------------------------------------------------------------------
MAX_MESSAGE_LENGTH = 4000
MAX_HISTORY_PER_USER = 50


def validate_input(text: str) -> Tuple[bool, Optional[str]]:
    if not text or not text.strip():
        return False, "Пустое сообщение."
    if len(text) > MAX_MESSAGE_LENGTH:
        return False, f"Сообщение слишком длинное (макс {MAX_MESSAGE_LENGTH} символов)."
    if "\x00" in text:
        return False, "Некорректный формат сообщения."
    # Проверка на одинаковые символы (например "aaaaaaaaaa") — только для длинных
    if len(text) > 10 and len(set(text)) < 3:
        return False, "Некорректный формат сообщения."
    return True, None


# ------------------------------------------------------------------
# 6. SUSPICIOUS ACTIVITY TRACKER
# ------------------------------------------------------------------
_SUSPICIOUS_USERS: dict = defaultdict(list)
_SUSPICIOUS_THRESHOLD = 3
_SUSPICIOUS_WINDOW = 3600
_BLOCKED_USERS: set = set()


def record_suspicious(user_id: int) -> bool:
    now = datetime.utcnow()
    _SUSPICIOUS_USERS[user_id].append(now)
    cutoff = now - timedelta(seconds=_SUSPICIOUS_WINDOW)
    _SUSPICIOUS_USERS[user_id] = [t for t in _SUSPICIOUS_USERS[user_id] if t > cutoff]
    if len(_SUSPICIOUS_USERS[user_id]) >= _SUSPICIOUS_THRESHOLD:
        _BLOCKED_USERS.add(user_id)
        return True
    return False


def is_blocked(user_id: int) -> bool:
    return user_id in _BLOCKED_USERS


def unblock_user(user_id: int) -> bool:
    if user_id in _BLOCKED_USERS:
        _BLOCKED_USERS.discard(user_id)
        _SUSPICIOUS_USERS[user_id].clear()
        return True
    return False


def get_blocked_users() -> list:
    return list(_BLOCKED_USERS)


# ------------------------------------------------------------------
# 7. FULL SECURITY SCAN (все проверки разом)
# ------------------------------------------------------------------

def full_security_scan(text: str, user_id: int) -> Tuple[bool, str]:
    """
    Полное сканирование сообщения на все виды атак.
    Возвращает: (is_blocked_or_attack: bool, reason: str)
    
    Если reason не пустой — причина блокировки.
    Если пустой — всё чисто.
    """
    # 0. Пользователь уже заблокирован
    if is_blocked(user_id):
        return True, "USER_BLOCKED"
    
    # 1. Валидация входа
    is_valid, error_msg = validate_input(text)
    if not is_valid:
        return True, f"INPUT_VALIDATION: {error_msg}"
    
    # 2. Нормализация текста
    text_clean = _remove_zero_width(text)
    text_clean = _normalize_unicode(text_clean)
    
    # 3. Jailbreak
    if is_jailbreak(text_clean):
        should_block = record_suspicious(user_id)
        block_suffix = " (BANNED)" if should_block else ""
        return True, f"JAILBREAK{block_suffix}"
    
    # 4. Encoding attacks
    enc_detected, enc_reason = detect_encoding_attack(text_clean)
    if enc_detected:
        record_suspicious(user_id)
        return True, f"ENCODING_ATTACK: {enc_reason}"
    
    # 5. Syntax injection
    syn_detected, syn_reason = detect_syntax_injection(text_clean)
    if syn_detected:
        record_suspicious(user_id)
        return True, f"SYNTAX_INJECTION: {syn_reason}"
    
    # 6. PII detection (только логируем, не блокируем)
    has_pii, pii_types = contains_pii(text_clean)
    
    return False, ""


# ------------------------------------------------------------------
# 8. TELEGRAM WEBHOOK VALIDATION
# ------------------------------------------------------------------

def validate_telegram_secret(token: str, expected: str) -> bool:
    if not expected:
        return True
    return token == expected
