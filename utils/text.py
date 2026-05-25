"""
utils/text.py — работа с текстом: числительные, транслит, лемматизация.
Перенос из utils.py.
"""
import re
from typing import Dict, Optional


# ------------------------------------------------------------------
# WORDS TO NUMBER (для голосовых: "пять тысяч" → 5000)
# ------------------------------------------------------------------
_NUM_WORDS = {
    'ноль': 0, 'один': 1, 'два': 2, 'три': 3, 'четыре': 4,
    'пять': 5, 'шесть': 6, 'семь': 7, 'восемь': 8, 'девять': 9,
    'десять': 10, 'одиннадцать': 11, 'двенадцать': 12,
    'тринадцать': 13, 'четырнадцать': 14, 'пятнадцать': 15,
    'шестнадцать': 16, 'семнадцать': 17, 'восемнадцать': 18,
    'девятнадцать': 19, 'двадцать': 20, 'тридцать': 30,
    'сорок': 40, 'пятьдесят': 50, 'шестьдесят': 60,
    'семьдесят': 70, 'восемьдесят': 80, 'девяносто': 90,
    'сто': 100, 'двести': 200, 'триста': 300, 'четыреста': 400,
    'пятьсот': 500, 'шестьсот': 600, 'семьсот': 700,
    'восемьсот': 800, 'девятьсот': 900, 'тысяча': 1000,
    'тысячи': 1000, 'тысяч': 1000, 'миллион': 1000000,
    'миллиона': 1000000, 'миллионов': 1000000,
}


def words_to_number(text: str) -> str:
    """
    Заменяет русские числительные на цифры в тексте.
    Пример: "пять тысяч" → "5000"
    Возвращает: текст с заменёнными числами
    """
    words = text.lower().split()
    result = []
    i = 0
    while i < len(words):
        # Ищем числительные подряд (например "пять тысяч")
        group = []
        j = i
        while j < len(words) and words[j].rstrip(',.;:') in _NUM_WORDS:
            group.append(words[j].rstrip(',.;:'))
            j += 1
        
        if len(group) >= 2:
            # Конвертируем группу в число
            total = 0
            current = 0
            for w in group:
                val = _NUM_WORDS[w]
                if val >= 1000:
                    if current == 0:
                        current = 1
                    total += current * val
                    current = 0
                else:
                    current += val
            total += current
            result.append(str(total))
            i = j
        else:
            result.append(words[i])
            i += 1
    
    # Объединяем соседние числа (для кодов ТН ВЭД: "6 1 0 9" → "6109")
    final = []
    i = 0
    while i < len(result):
        if result[i].isdigit():
            # Собираем группу соседних чисел
            num_group = [result[i]]
            j = i + 1
            while j < len(result) and result[j].isdigit():
                num_group.append(result[j])
                j += 1
            if len(num_group) > 1:
                final.append(''.join(num_group))
            else:
                final.append(result[i])
            i = j
        else:
            final.append(result[i])
            i += 1
    
    return ' '.join(final)


# ------------------------------------------------------------------
# TRANSLITERATION (латиница → кириллица)
# ------------------------------------------------------------------

TRANSLIT_MAP = {
    'a': 'а', 'b': 'б', 'v': 'в', 'g': 'г', 'd': 'д', 'e': 'е',
    'z': 'з', 'i': 'и', 'y': 'й', 'k': 'к', 'l': 'л', 'm': 'м',
    'n': 'н', 'o': 'о', 'p': 'п', 'r': 'р', 's': 'с', 't': 'т',
    'u': 'у', 'f': 'ф', 'h': 'х', "'": 'э', 'c': 'ч',
    'ch': 'ч', 'sh': 'ш', 'ya': 'я', 'ye': 'е', 'yu': 'ю',
    'yo': 'ё', 'zh': 'ж', 'kh': 'х', 'ts': 'ц',
}


def transliterate_latin_to_cyrillic(text: str) -> str:
    """Транслитерирует латиницу в кириллицу (для поиска ТН ВЭД).
    Пример: "vatnye volokna" → "ватные волокна"
    """
    text_lower = text.lower()
    # Сначала многосимвольные комбинации (от длинных к коротким)
    for lat, cyr in sorted(TRANSLIT_MAP.items(), key=lambda x: -len(x[0])):
        text_lower = text_lower.replace(lat, cyr)
    return text_lower


# ------------------------------------------------------------------
# LEMMATIZATION (простая русская лемматизация)
# ------------------------------------------------------------------

def lemmatize_russian(word: str) -> str:
    """Простая лемматизация: отрезаем типичные русские окончания.
    Пример: "хлопковой" → "хлопков", "ткани" → "ткан"
    """
    suffixes = (
        # Прилагательные
        "овой", "овая", "овое", "овые", "овый", "ового", "овому",
        "евой", "евая", "евое", "евые", "евый",
        "ной", "ная", "ное", "ные", "ный", "ного", "ному",
        "еной", "еная", "еное", "еные",
        # Существительные
        "ов", "ев", "ей", "ям", "ях", "ами", "ой", "ий",
        "ие", "ии", "иям", "иях", "иями",
        # Глаголы/причастия
        "ешь", "ете", "ут", "ют", "ить", "ать", "ять",
        # Родительный падеж
        "ы", "и", "ов", "ей", "ей", 
    )
    w = word.lower()
    for suffix in sorted(suffixes, key=len, reverse=True):
        if w.endswith(suffix) and len(w) > len(suffix) + 2:
            return w[:-len(suffix)]
    return w


# ------------------------------------------------------------------
# SPLIT DOCUMENT TO SECTIONS (разбивка документа по заголовкам)
# ------------------------------------------------------------------

# Паттерны заголовков: "1. Текст", "# Заголовок", "=== Заголовок ===", "ЗАГОЛОВОК ЗАГЛАВНЫМИ"
_SECTION_HEADER_RE = re.compile(
    r'^(?:'
    r'\d+[\.\)]\s+.+?'          # 1. Заголовок  или  1) Заголовок
    r'|#{1,4}\s+.+?'             # # Заголовок  или  ## Заголовок
    r'|\s*=+\s*.+?\s*=+\s*'     # === Заголовок ===
    r'|[А-ЯЁ][А-ЯЁ\s\d]{3,}'    # ЗАГЛАВНЫМИ БУКВАМИ (4+ символа)
    r')$',
    re.MULTILINE
)


def split_document_to_sections(text: str, default_topic: str = "Документ") -> list:
    """Разбивает текст на секции по заголовкам.
    
    Returns:
        [(topic, content), ...] — список секций
    """
    if not text or not text.strip():
        return []
    
    lines = text.split('\n')
    sections = []
    current_topic = default_topic
    current_lines = []
    
    for line in lines:
        stripped = line.strip()
        # Проверяем — это заголовок?
        is_header = bool(_SECTION_HEADER_RE.match(stripped))
        # Дополнительная проверка: Заголовок: (с двоеточием, не длиннее 80 символов)
        if not is_header and stripped and len(stripped) < 80:
            if stripped.endswith(':') and stripped[0].isupper():
                is_header = True
        
        if is_header:
            # Сохраняем предыдущую секцию если есть контент
            if current_lines and len('\n'.join(current_lines).strip()) > 20:
                sections.append((
                    current_topic,
                    '\n'.join(current_lines).strip()
                ))
            current_topic = stripped.strip('#= ').strip()
            current_lines = []
        else:
            current_lines.append(line)
    
    # Последняя секция
    if current_lines and len('\n'.join(current_lines).strip()) > 20:
        sections.append((
            current_topic,
            '\n'.join(current_lines).strip()
        ))
    
    # Если ничего не разбилось — сохраняем целиком
    if not sections:
        sections.append((default_topic, text.strip()))
    
    return sections


# ------------------------------------------------------------------
# MARKDOWN → HTML (DeepSeek отдаёт Markdown, Telegram у нас в HTML)
# ------------------------------------------------------------------

def markdown_to_html(text: str) -> str:
    """Конвертирует базовый Markdown в Telegram-HTML.

    Поддерживает:
      **жирный** / __жирный__   → <b>…</b>
      *курсив* / _курсив_       → <i>…</i>
      `код`                     → <code>…</code>
      ```блок```                → <pre>…</pre>
      * пункт / - пункт         → • пункт
      ### Заголовок             → <b>Заголовок</b>

    HTML-спецсимволы экранируются ДО вставки тегов, чтобы не сломать разметку.
    """
    if not text:
        return text

    # 1. Защищаем уже существующие HTML-теги бота (<b>, <i>, <code>, <pre>, <a>)
    #    — чтобы не экранировать их. Временно заменяем на плейсхолдеры.
    placeholders = []
    def _stash(m):
        placeholders.append(m.group(0))
        return f"\x00{len(placeholders) - 1}\x00"
    text = re.sub(r"</?(?:b|i|code|pre|a)(?:\s[^>]*)?>", _stash, text)

    # 2. Экранируем HTML-спецсимволы
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 3. Блоки кода ```...``` → <pre>
    text = re.sub(r"```[a-zA-Z]*\n?(.*?)```", r"<pre>\1</pre>", text, flags=re.DOTALL)

    # 4. Инлайн-код `...` → <code>
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)

    # 5. Заголовки ### / ## / # → жирный
    text = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # 6. Жирный **...** и __...__
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__([^_]+)__", r"<b>\1</b>", text)

    # 7. Курсив *...* и _..._ (одиночные, не задевая уже обработанные)
    text = re.sub(r"(?<!\*)\*(?!\*)([^*\n]+?)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!_)_(?!_)([^_\n]+?)_(?!_)", r"<i>\1</i>", text)

    # 8. Маркеры списка в начале строки: "* " / "- " / "+ " → "• "
    text = re.sub(r"^[ \t]*[\*\-\+]\s+", "• ", text, flags=re.MULTILINE)

    # 9. Возвращаем сохранённые HTML-теги
    def _unstash(m):
        return placeholders[int(m.group(1))]
    text = re.sub(r"\x00(\d+)\x00", _unstash, text)

    return text
