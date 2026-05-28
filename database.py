"""
database.py — все операции с SQLite.
Импортирует только config (DB_PATH, logger, VERSION).
"""
import sqlite3
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from io import BytesIO
from config import DB_PATH, logger


# ------------------------------------------------------------------
# Инициализация
# ------------------------------------------------------------------

def init_db() -> None:
    """Создаёт директорию и таблицы, если их нет."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    logger.info(f"[DB] Using database at: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript("""
        CREATE TABLE IF NOT EXISTS dialogs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            role TEXT,
            content TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            original TEXT,
            correction TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS custom_radio_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            added_at TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS user_blocks (
            user_id     INTEGER PRIMARY KEY,
            blocked_at  REAL NOT NULL,
            reason      TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS suspicious_counts (
            user_id  INTEGER PRIMARY KEY,
            count    INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS knowledge_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT,
            content TEXT,
            questions TEXT,
            added_by TEXT,
            created_at TEXT,
            embedding BLOB DEFAULT NULL,
            source_doc TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS tnved_cache (
            code TEXT PRIMARY KEY,
            name TEXT,
            tariff TEXT,
            parsed_type TEXT,
            parsed_formula TEXT,
            loaded_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_tnved_name ON tnved_cache(name);
        CREATE TABLE IF NOT EXISTS scheduled_reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER UNIQUE,
            chat_id INTEGER NOT NULL,
            task_text TEXT NOT NULL,
            deal_name TEXT DEFAULT '',
            due_ts INTEGER NOT NULL,
            explicit_time INTEGER DEFAULT 0,
            created_at TEXT
        );
    """)
    # Миграция: добавляем колонки если их нет (для существующих БД)
    for col, definition in [
        ("embedding", "BLOB DEFAULT NULL"),
        ("source_doc", "TEXT DEFAULT NULL"),
    ]:
        try:
            c.execute(f"ALTER TABLE knowledge_base ADD COLUMN {col} {definition}")
            logger.info(f"[DB] Добавлена колонка {col} в knowledge_base")
        except Exception:
            pass  # Колонка уже есть
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована.")


# ------------------------------------------------------------------
# Диалоги
# ------------------------------------------------------------------

def save_message(user_id: int, username: str, role: str, content: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO dialogs (user_id, username, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, username, role, content, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    conn.close()


def get_dialog_history(user_id: int, limit: int = 20) -> List[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT role, content FROM dialogs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    )
    rows = c.fetchall()
    conn.close()
    return [{"role": r, "content": c} for r, c in reversed(rows)]


def clear_history(user_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM dialogs WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def get_dialogs_for_export(
    date_from: Optional[str] = None, date_to: Optional[str] = None
) -> List[Tuple]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    query = "SELECT user_id, username, role, content, created_at FROM dialogs WHERE 1=1"
    params = []
    if date_from:
        query += " AND created_at >= ?"
        params.append(f"{date_from} 00:00:00")
    if date_to:
        query += " AND created_at <= ?"
        params.append(f"{date_to} 23:59:59")
    query += " ORDER BY created_at"
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows


# ------------------------------------------------------------------
# Исправления / замечания
# ------------------------------------------------------------------

def save_correction(
    user_id: int, username: str, original: str, correction: str
) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO corrections (user_id, username, original, correction, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, username, original, correction, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    conn.close()


def get_all_corrections() -> List[Tuple]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT user_id, username, original, correction, created_at FROM corrections ORDER BY created_at DESC"
    )
    rows = c.fetchall()
    conn.close()
    return rows


# ------------------------------------------------------------------
# База знаний
# ------------------------------------------------------------------

def save_knowledge(topic: str, content: str, questions: str, added_by: str, embedding: bytes = None, source_doc: str = None) -> int:
    """Сохраняет запись в БЗ. Возвращает ID новой записи."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO knowledge_base (topic, content, questions, added_by, created_at, embedding, source_doc) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (topic, content, questions, added_by, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), embedding, source_doc),
    )
    record_id = c.lastrowid
    conn.commit()
    conn.close()
    return record_id


def update_knowledge_embedding(record_id: int, embedding: bytes) -> None:
    """Обновляет embedding для существующей записи."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE knowledge_base SET embedding = ? WHERE id = ?", (embedding, record_id))
    conn.commit()
    conn.close()


def save_knowledge_sections(sections: list, added_by: str, embeddings: list = None, source_doc: str = None) -> int:
    """Сохраняет список секций (topic, content) в БЗ. Возвращает количество сохранённых."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    count = 0
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    for i, (topic, content) in enumerate(sections):
        if content.strip():
            emb = embeddings[i] if embeddings and i < len(embeddings) else None
            c.execute(
                "INSERT INTO knowledge_base (topic, content, questions, added_by, created_at, embedding, source_doc) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (topic[:255], content, "", added_by, now, emb, source_doc),
            )
            count += 1
    conn.commit()
    conn.close()
    return count


def get_all_knowledge() -> List[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT topic, content, questions, added_by, created_at FROM knowledge_base")
    rows = c.fetchall()
    conn.close()
    return [
        {
            "topic": r[0],
            "content": r[1],
            "questions": r[2],
            "added_by": r[3],
            "created_at": r[4],
        }
        for r in rows
    ]


# Alias для совместимости
get_knowledge = get_all_knowledge


def get_knowledge_by_topic(topic: str) -> Optional[Dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT topic, content, questions, added_by, created_at FROM knowledge_base WHERE topic = ?", (topic,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "topic": row[0],
        "content": row[1],
        "questions": row[2],
        "added_by": row[3],
        "created_at": row[4],
    }


# ------------------------------------------------------------------
# Settings
# ------------------------------------------------------------------

def get_setting(key: str) -> Optional[str]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def set_setting(key: str, value: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, value),
    )
    conn.commit()
    conn.close()


# ------------------------------------------------------------------
# Радиоэлектроника — кастомные коды
# ------------------------------------------------------------------

def add_custom_radio_code(code: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO custom_radio_codes (code, added_at) VALUES (?, ?)",
            (code, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()


def save_custom_codes(codes: List[str]) -> int:
    """Сохраняет список кодов радиоэлектроники в таблицу custom_radio_codes.
    Возвращает количество добавленных кодов.
    """
    if not codes:
        return 0
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    added = 0
    for code in codes:
        try:
            c.execute(
                "INSERT OR IGNORE INTO custom_radio_codes (code, added_at) VALUES (?, ?)",
                (code, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")),
            )
            if c.rowcount > 0:
                added += 1
        except sqlite3.Error:
            continue
    conn.commit()
    conn.close()
    logger.info(f"Сохранено {added} новых кодов радиоэлектроники")
    return added


def get_all_custom_radio_codes() -> List[str]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT code FROM custom_radio_codes")
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows


# ------------------------------------------------------------------
# ТН ВЭД — кэш
# ------------------------------------------------------------------

def save_tnved_batch(raw_rows: List, parsed_rows: List) -> None:
    """Сохраняет или обновляет коды ТН ВЭД в SQLite-кэше."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for raw, parsed in zip(raw_rows, parsed_rows):
        code = raw[0] if raw else ""
        name = raw[1] if len(raw) > 1 else ""
        tariff = raw[2] if len(raw) > 2 else ""
        code_clean = code.replace(" ", "")
        c.execute(
            """
            INSERT OR REPLACE INTO tnved_cache (code, name, tariff, parsed_type, parsed_formula, loaded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                code_clean,
                name,
                tariff,
                parsed.get("type", ""),
                parsed.get("formula", ""),
                datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
    conn.commit()
    conn.close()
    logger.info(f"TNVED: сохранено {len(raw_rows)} кодов в БД")


def get_tnved_from_db(code: str) -> Optional[Dict]:
    """Получает код ТН ВЭД из SQLite-кэша."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT code, name, tariff, parsed_type, parsed_formula FROM tnved_cache WHERE code = ?", (code,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "code": row[0],
        "name": row[1],
        "tariff": row[2],
        "parsed_tariff": {"type": row[3], "formula": row[4]},
    }


def search_tnved_in_db(query: str) -> List[Dict]:
    """Поиск по наименованию в SQLite-кэше."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT code, name, tariff, parsed_type, parsed_formula FROM tnved_cache WHERE name LIKE ? LIMIT 10",
        (f"%{query}%",),
    )
    rows = c.fetchall()
    conn.close()
    return [
        {
            "code": r[0],
            "name": r[1],
            "tariff": r[2],
            "parsed_tariff": {"type": r[3], "formula": r[4]},
        }
        for r in rows
    ]


def get_all_tnved_from_db() -> List[List[str]]:
    """Получает ВСЕ коды из SQLite для восстановления кэша при старте."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT code, name, tariff FROM tnved_cache ORDER BY code")
    rows = c.fetchall()
    conn.close()
    logger.info(f"TNVED кэш: загружено {len(rows)} кодов из БД")
    return [[r[0], r[1], r[2]] for r in rows]


def clear_tnved_cache_db() -> int:
    """Очищает таблицу tnved_cache. Возвращает количество удалённых записей."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM tnved_cache")
    count = c.fetchone()[0]
    c.execute("DELETE FROM tnved_cache")
    conn.commit()
    conn.close()
    logger.info(f"TNVED кэш: удалено {count} кодов из БД")
    return count


def get_tnved_stats() -> dict:
    """Статистика по кэшу ТН ВЭД в БД."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*), parsed_type FROM tnved_cache GROUP BY parsed_type")
    stats = dict(c.fetchall())
    c.execute("SELECT COUNT(DISTINCT code) FROM tnved_cache")
    total = c.fetchone()[0]
    conn.close()
    return {"total": total, "by_type": stats}


# ------------------------------------------------------------------
# Экспорт логов в XLSX (через zipfile + xml, без openpyxl)
# ------------------------------------------------------------------

def _col_letter(idx: int) -> str:
    """Преобразует индекс колонки (0-based) в буквенное обозначение (A, B, ..., Z, AA, ...)."""
    result = ""
    while idx >= 0:
        result = chr(65 + (idx % 26)) + result
        idx = idx // 26 - 1
    return result


def _escape_xml(text: str) -> str:
    """Экранирует XML-спецсимволы и переводы строк."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    text = text.replace("\r\n", "&#10;").replace("\n", "&#10;").replace("\r", "&#10;")
    return text


def create_logs_xlsx(rows: List[Tuple], sheet_name: str = "logs") -> bytes:
    """Генерирует .xlsx через sharedStrings.xml (стандартный формат Excel).
    Совместимость: Excel, LibreOffice, Google Sheets.
    """
    import zipfile

    ct_ns = "http://schemas.openxmlformats.org/package/2006/content-types"

    # Собираем уникальные строки
    strings: List[str] = []
    str_index: Dict[str, int] = {}

    def add_str(s: str) -> int:
        s = str(s) if s is not None else ""
        if s not in str_index:
            str_index[s] = len(strings)
            strings.append(s)
        return str_index[s]

    # Заголовки
    headers = ["user_id", "username", "role", "content", "created_at"]
    header_indices = [add_str(h) for h in headers]

    # Данные
    data_indices: List[List[int]] = []
    for row in rows:
        data_indices.append([add_str(v) for v in row])

    # --- sharedStrings.xml ---
    ss_parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n',
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(strings)}" uniqueCount="{len(strings)}">\n',
    ]
    for s in strings:
        ss_parts.append(f'  <si><t xml:space="preserve">{_escape_xml(s)}</t></si>\n')
    ss_parts.append('</sst>')
    ss_xml = "".join(ss_parts).encode("utf-8")

    # --- workbook.xml ---
    wb_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">\n'
        '  <sheets>\n'
        f'    <sheet name="{_escape_xml(sheet_name)}" sheetId="1" r:id="rId1"/>\n'
        '  </sheets>\n'
        '  <calcPr calcId="124519" fullCalcOnLoad="1"/>\n'
        '</workbook>'
    ).encode("utf-8")

    # --- worksheet.xml ---
    max_col = 4
    max_row = len(rows) + 1
    ws_parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">\n',
        f'  <dimension ref="A1:{_col_letter(max_col)}{max_row}"/>\n',
        '  <sheetData>\n',
    ]
    # Заголовок
    ws_parts.append('    <row r="1">\n')
    for c_idx, si in enumerate(header_indices):
        cell_ref = f"{_col_letter(c_idx)}1"
        ws_parts.append(f'      <c r="{cell_ref}" t="s"><v>{si}</v></c>\n')
    ws_parts.append('    </row>\n')
    # Данные
    for r_idx, row_indices in enumerate(data_indices, 2):
        ws_parts.append(f'    <row r="{r_idx}">\n')
        for c_idx, si in enumerate(row_indices):
            cell_ref = f"{_col_letter(c_idx)}{r_idx}"
            ws_parts.append(f'      <c r="{cell_ref}" t="s"><v>{si}</v></c>\n')
        ws_parts.append('    </row>\n')
    ws_parts.append('  </sheetData>\n')
    ws_parts.append('</worksheet>')
    ws_xml = "".join(ws_parts).encode("utf-8")

    # --- workbook.xml.rels ---
    wb_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>\n'
        '  <Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" '
        'Target="sharedStrings.xml"/>\n'
        '</Relationships>'
    ).encode("utf-8")

    # --- [Content_Types].xml ---
    ct_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<Types xmlns="{ct_ns}">\n'
        '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        '  <Default Extension="xml" ContentType="application/xml"/>\n'
        '  <Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>\n'
        '  <Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>\n'
        '  <Override PartName="/xl/sharedStrings.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>\n'
        '</Types>'
    ).encode("utf-8")

    # --- .rels ---
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>\n'
        '</Relationships>'
    ).encode("utf-8")

    # --- сборка zip ---
    xlsx_buffer = BytesIO()
    with zipfile.ZipFile(xlsx_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", ct_xml)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels_xml)
        zf.writestr("xl/workbook.xml", wb_xml)
        zf.writestr("xl/worksheets/sheet1.xml", ws_xml)
        zf.writestr("xl/sharedStrings.xml", ss_xml)

    return xlsx_buffer.getvalue()


# ------------------------------------------------------------------
# Блокировки пользователей
# ------------------------------------------------------------------

def db_is_blocked(user_id: int, duration: float = 3600.0) -> bool:
    """Проверяет, заблокирован ли пользователь (с авторазблокировкой)."""
    import time
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT blocked_at FROM user_blocks WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False
    if time.time() - row[0] >= duration:
        c.execute("DELETE FROM user_blocks WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        return False
    conn.close()
    return True


def db_block_user(user_id: int, reason: str = "") -> None:
    """Блокирует пользователя (сохраняет timestamp в БД)."""
    import time
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO user_blocks (user_id, blocked_at, reason) VALUES (?, ?, ?)",
        (user_id, time.time(), reason),
    )
    conn.commit()
    conn.close()
    logger.warning(f"[DB] User {user_id} blocked, reason={reason}")


def db_unblock_user(user_id: int) -> bool:
    """Разблокирует пользователя. Возвращает True если был заблокирован."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM user_blocks WHERE user_id = ?", (user_id,))
    deleted = c.rowcount > 0
    c.execute("DELETE FROM suspicious_counts WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    if deleted:
        logger.info(f"[DB] User {user_id} unblocked")
    return deleted


def db_increment_suspicious(user_id: int) -> int:
    """Увеличивает счётчик подозрительных запросов. Возвращает новое значение."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO suspicious_counts (user_id, count) VALUES (?, 1)
        ON CONFLICT(user_id) DO UPDATE SET count = count + 1
        """,
        (user_id,),
    )
    conn.commit()
    c.execute("SELECT count FROM suspicious_counts WHERE user_id = ?", (user_id,))
    new_count = c.fetchone()[0]
    conn.close()
    return new_count


# ------------------------------------------------------------------
# ТН ВЭД — поиск по разделам (для хендлера подбора кода)
# ------------------------------------------------------------------

def search_tnved_by_sections(sections: List[str]) -> List[Dict]:
    """Ищет коды ТН ВЭД по списку разделов (префиксов).

    Фильтрует записи с пустым наименованием и проверяет совпадение
    первых 4 цифр кода с префиксом раздела.

    Args:
        sections: список префиксов, например ["5208", "6004"]

    Returns:
        Список dict с ключами: code, name, tariff, section
    """
    if not sections:
        return []

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    results: List[Dict] = []

    for section in sections:
        c.execute(
            """
            SELECT code, name, tariff
            FROM tnved_cache
            WHERE code LIKE ? AND name IS NOT NULL AND name != ''
            LIMIT 20
            """,
            (f"{section}%",),
        )
        section_prefix = section[:4]
        for row in c.fetchall():
            code_prefix = row[0][:4] if len(row[0]) >= 4 else row[0]
            if code_prefix == section_prefix:
                results.append({
                    "code": row[0],
                    "name": row[1],
                    "tariff": row[2],
                    "section": section,
                })

    conn.close()
    return results


# ------------------------------------------------------------------
# База знаний — дополнительные функции
# ------------------------------------------------------------------

def delete_knowledge_by_id(record_id: int) -> bool:
    """Удаляет запись из БЗ по ID. Возвращает True если удалена."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM knowledge_base WHERE id = ?", (record_id,))
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def delete_knowledge_by_topic(topic: str) -> int:
    """Удаляет все записи с совпадением темы (частичное). Возвращает кол-во удалённых."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM knowledge_base WHERE topic LIKE ?", (f"%{topic}%",))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted


def get_all_knowledge_with_ids() -> List[Dict]:
    """Возвращает все записи БЗ с ID (для /topics и /forget)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, topic, content, added_by, created_at FROM knowledge_base ORDER BY id")
    rows = c.fetchall()
    conn.close()
    return [
        {"id": r[0], "topic": r[1], "content": r[2], "added_by": r[3], "created_at": r[4]}
        for r in rows
    ]


def search_knowledge(query_words: set, top_n: int = 3) -> List[Dict]:
    """Умный поиск по БЗ: возвращает top_n самых релевантных записей.

    Алгоритм:
    - Совпадение слова с темой записи: +10 очков
    - Совпадение слова с контентом: +2 очка
    - Бонус: тема содержит ВСЕ слова запроса: +20
    """
    all_kb = get_all_knowledge_with_ids()
    scored = []
    query_list = list(query_words)

    for k in all_kb:
        topic_lower = k["topic"].lower()
        content_lower = k["content"].lower()
        score = 0

        for w in query_list:
            if w in topic_lower:
                score += 10
            if w in content_lower:
                score += 2

        # Бонус если тема содержит ВСЕ слова
        if all(w in topic_lower for w in query_list):
            score += 20

        if score > 0:
            scored.append((score, k))

    scored.sort(key=lambda x: -x[0])
    return [k for _, k in scored[:top_n]]


def vector_search(query_vector: List[float], top_n: int = 3, min_score: float = 0.3) -> List[Dict]:
    """Семантический поиск по базе знаний через косинусное сходство.

    Для записей без embedding автоматически делает fallback на keyword-поиск.

    Args:
        query_vector: вектор запроса (от get_embedding)
        top_n: сколько записей вернуть
        min_score: минимальный порог сходства (0.3 = умеренно похожие)

    Returns:
        Список записей sorted по релевантности (самые похожие первые)
    """
    from services.embeddings import cosine_similarity, blob_to_embedding

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, topic, content, embedding FROM knowledge_base")
    rows = c.fetchall()
    conn.close()

    scored = []
    no_embedding = []

    for row in rows:
        record_id, topic, content, emb_blob = row
        if emb_blob:
            vec = blob_to_embedding(emb_blob)
            if vec:
                score = cosine_similarity(query_vector, vec)
                if score >= min_score:
                    scored.append((score, {"id": record_id, "topic": topic, "content": content}))
        else:
            # Запись без embedding — попадёт в fallback
            no_embedding.append({"id": record_id, "topic": topic, "content": content})

    scored.sort(key=lambda x: -x[0])
    results = [k for _, k in scored[:top_n]]

    # Логируем если есть записи без embedding
    if no_embedding:
        logger.warning(
            f"[VectorSearch] {len(no_embedding)} записей без embedding — "
            f"используй /reindex для их векторизации"
        )

    return results


def get_knowledge_without_embeddings() -> List[Dict]:
    """Возвращает записи БЗ у которых нет embedding (для переиндексации)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, topic, content FROM knowledge_base WHERE embedding IS NULL"
    )
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "topic": r[1], "content": r[2]} for r in rows]


def get_knowledge_grouped() -> List[Dict]:
    """Возвращает записи БЗ сгруппированные по source_doc для /topics.

    Документы с секциями показываются как одна строка (имя документа + кол-во секций).
    Одиночные записи (--whole) показываются как есть.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, topic, source_doc, created_at FROM knowledge_base ORDER BY created_at, id"
    )
    rows = c.fetchall()
    conn.close()

    # Группируем по source_doc
    groups: dict = {}       # source_doc → [records]
    no_source: list = []    # записи без source_doc (одиночные --whole)

    for record_id, topic, source_doc, created_at in rows:
        if source_doc:
            if source_doc not in groups:
                groups[source_doc] = []
            groups[source_doc].append({"id": record_id, "topic": topic})
        else:
            no_source.append({"id": record_id, "topic": topic, "source_doc": None})

    result = []
    # Одиночные записи
    for rec in no_source:
        result.append({
            "display": f"📄 {rec['topic'][:70]}",
            "id": rec["id"],
            "ids": [rec["id"]],
            "is_group": False,
        })
    # Сгруппированные документы
    for source_doc, records in groups.items():
        ids = [r["id"] for r in records]
        result.append({
            "display": f"📁 {source_doc[:70]} ({len(records)} секций)",
            "id": ids[0],   # первый ID для удаления группой
            "ids": ids,
            "is_group": True,
        })

    return result


def delete_knowledge_by_source(source_doc: str) -> int:
    """Удаляет все секции документа по source_doc. Возвращает кол-во удалённых."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM knowledge_base WHERE source_doc = ?", (source_doc,))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted


def clear_knowledge_base() -> int:
    """Удаляет все записи из базы знаний. Возвращает кол-во удалённых."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM knowledge_base")
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted


# ------------------------------------------------------------------
# Scheduled reminders
# ------------------------------------------------------------------

def save_reminder(task_id: int, chat_id: int, task_text: str, deal_name: str,
                  due_ts: int, explicit_time: bool) -> None:
    """Сохраняет напоминание в БД."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            INSERT OR REPLACE INTO scheduled_reminders
            (task_id, chat_id, task_text, deal_name, due_ts, explicit_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (task_id, chat_id, task_text, deal_name, due_ts,
              1 if explicit_time else 0, datetime.now().isoformat()))
        conn.commit()
    finally:
        conn.close()


def delete_reminder(task_id: int) -> None:
    """Удаляет напоминание из БД."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("DELETE FROM scheduled_reminders WHERE task_id = ?", (task_id,))
        conn.commit()
    finally:
        conn.close()


def load_pending_reminders() -> list:
    """Загружает все будущие напоминания из БД."""
    import time
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute("""
            SELECT task_id, chat_id, task_text, deal_name, due_ts, explicit_time
            FROM scheduled_reminders
            WHERE due_ts > ?
        """, (int(time.time()),)).fetchall()
        return [
            {
                "task_id": r[0], "chat_id": r[1], "task_text": r[2],
                "deal_name": r[3], "due_ts": r[4], "explicit_time": bool(r[5]),
            }
            for r in rows
        ]
    finally:
        conn.close()
