import sqlite3
import os
import logging
from datetime import datetime
from config import DB_PATH

logger = logging.getLogger(__name__)

# Глобальное соединение с БД
conn = None


def init_db():
    """Инициализация базы данных и создание таблиц, если их нет."""
    global conn
    
    # Убедимся, что директория для БД существует
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")       # Ускорение параллельной записи
    conn.execute("PRAGMA foreign_keys=ON")
    
    cursor = conn.cursor()
    
    # Таблица диалогов
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dialogs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Индексы для таблицы диалогов
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_dialogs_user_ts 
        ON dialogs(user_id, timestamp DESC)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_dialogs_timestamp 
        ON dialogs(timestamp)
    """)
    
    # Таблица кэша ТН ВЭД
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tnved_cache (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            tariff TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Индексы для ТН ВЭД
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_tnved_name 
        ON tnved_cache(name)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_tnved_code_prefix 
        ON tnved_cache(code)
    """)
    
    # Таблица базы знаний
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            section_title TEXT,
            content TEXT NOT NULL,
            added_by INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Индексы для базы знаний
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_kb_topic 
        ON knowledge_base(topic)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_kb_section_title 
        ON knowledge_base(section_title)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_kb_created_at 
        ON knowledge_base(created_at DESC)
    """)
    
    # Таблица исправлений пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            user_message TEXT,
            bot_response TEXT,
            correction_note TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Индексы для исправлений
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_corrections_user 
        ON corrections(user_id, created_at DESC)
    """)
    
    # Таблица заблокированных пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS blocked_users (
            user_id INTEGER PRIMARY KEY,
            blocked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            reason TEXT
        )
    """)
    
    # Таблица кодов радиоэлектроники
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS custom_radio_codes (
            code TEXT PRIMARY KEY,
            description TEXT,
            added_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    logger.info(f"База данных инициализирована: {DB_PATH}")
    
    # Выводим статистику для мониторинга
    stats = get_db_stats()
    logger.info(f"Статистика БД: диалогов={stats['dialogs']}, "
                f"ТН ВЭД={stats['tnved']}, БЗ={stats['knowledge']}, "
                f"исправлений={stats['corrections']}")
    
    return conn


def get_connection():
    """Получить текущее соединение с БД."""
    global conn
    if conn is None:
        init_db()
    return conn


def get_recent_history(user_id: int, limit: int = 20) -> list:
    """
    Получить последние сообщения пользователя для контекста AI.
    
    Args:
        user_id: Telegram ID пользователя
        limit: Максимальное количество сообщений
    
    Returns:
        Список словарей [{"role": "user/assistant", "content": "..."}]
    """
    c = get_connection().cursor()
    c.execute("""
        SELECT role, content FROM dialogs 
        WHERE user_id = ? 
        ORDER BY timestamp DESC 
        LIMIT ?
    """, (user_id, limit))
    
    rows = c.fetchall()
    rows.reverse()  # От старых к новым
    
    return [{"role": row["role"], "content": row["content"]} for row in rows]


def save_message(user_id: int, role: str, content: str):
    """Сохранить сообщение в историю диалога."""
    c = get_connection().cursor()
    c.execute("""
        INSERT INTO dialogs (user_id, role, content) 
        VALUES (?, ?, ?)
    """, (user_id, role, content))
    get_connection().commit()


def search_knowledge_base(query: str, limit: int = 5) -> list:
    """
    Поиск по базе знаний с поддержкой связанных терминов.
    
    Args:
        query: Поисковый запрос
        limit: Максимальное количество результатов
    
    Returns:
        Список найденных секций [{"topic": ..., "section_title": ..., "content": ...}]
    """
    c = get_connection().cursor()
    
    # Разбиваем запрос на слова и ищем каждое
    terms = query.lower().split()
    if not terms:
        return []
    
    # Строим SQL с несколькими LIKE
    conditions = " OR ".join(["content LIKE ?" for _ in terms])
    params = [f"%{term}%" for term in terms]
    
    c.execute(f"""
        SELECT topic, section_title, content FROM knowledge_base 
        WHERE {conditions}
        ORDER BY created_at DESC 
        LIMIT ?
    """, params + [limit])
    
    rows = c.fetchall()
    return [{"topic": row["topic"], "section_title": row["section_title"], 
             "content": row["content"]} for row in rows]


def get_knowledge_topics() -> list:
    """Получить список всех уникальных тем в базе знаний."""
    c = get_connection().cursor()
    c.execute("SELECT DISTINCT topic FROM knowledge_base ORDER BY topic")
    return [row["topic"] for row in c.fetchall()]


def add_knowledge(topic: str, section_title: str, content: str, added_by: int):
    """Добавить секцию в базу знаний."""
    c = get_connection().cursor()
    c.execute("""
        INSERT INTO knowledge_base (topic, section_title, content, added_by) 
        VALUES (?, ?, ?, ?)
    """, (topic, section_title, content, added_by))
    get_connection().commit()
    logger.info(f"Добавлена секция в БЗ: topic={topic}, title={section_title}")


def get_tnved_by_code(code: str) -> dict:
    """Получить информацию о коде ТН ВЭД."""
    c = get_connection().cursor()
    c.execute("SELECT code, name, tariff FROM tnved_cache WHERE code = ?", (code,))
    row = c.fetchone()
    if row:
        return {"code": row["code"], "name": row["name"], "tariff": row["tariff"]}
    return None


def search_tnved_by_name(query: str, limit: int = 10) -> list:
    """Поиск кодов ТН ВЭД по наименованию."""
    c = get_connection().cursor()
    c.execute("""
        SELECT code, name, tariff FROM tnved_cache 
        WHERE name LIKE ? 
        LIMIT ?
    """, (f"%{query}%", limit))
    
    rows = c.fetchall()
    return [{"code": row["code"], "name": row["name"], "tariff": row["tariff"]} 
            for row in rows]


def add_tnved_codes(codes: list):
    """
    Пакетная вставка или обновление кодов ТН ВЭД.
    
    Args:
        codes: Список словарей [{"code": ..., "name": ..., "tariff": ...}]
    """
    c = get_connection().cursor()
    for item in codes:
        c.execute("""
            INSERT OR REPLACE INTO tnved_cache (code, name, tariff, updated_at) 
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """, (item["code"], item["name"], item.get("tariff", "")))
    get_connection().commit()
    logger.info(f"Загружено/обновлено кодов ТН ВЭД: {len(codes)}")


def add_correction(user_id: int, user_message: str, bot_response: str, correction_note: str):
    """Сохранить исправление от пользователя."""
    c = get_connection().cursor()
    c.execute("""
        INSERT INTO corrections (user_id, user_message, bot_response, correction_note) 
        VALUES (?, ?, ?, ?)
    """, (user_id, user_message, bot_response, correction_note))
    get_connection().commit()
    logger.info(f"Сохранено исправление от user {user_id}")


def is_user_blocked(user_id: int) -> bool:
    """Проверить, заблокирован ли пользователь."""
    c = get_connection().cursor()
    c.execute("SELECT user_id FROM blocked_users WHERE user_id = ?", (user_id,))
    return c.fetchone() is not None


def block_user(user_id: int, reason: str = ""):
    """Заблокировать пользователя."""
    c = get_connection().cursor()
    c.execute("""
        INSERT OR REPLACE INTO blocked_users (user_id, blocked_at, reason) 
        VALUES (?, CURRENT_TIMESTAMP, ?)
    """, (user_id, reason))
    get_connection().commit()
    logger.info(f"Заблокирован пользователь {user_id}")


def unblock_user(user_id: int):
    """Разблокировать пользователя."""
    c = get_connection().cursor()
    c.execute("DELETE FROM blocked_users WHERE user_id = ?", (user_id,))
    get_connection().commit()
    logger.info(f"Разблокирован пользователь {user_id}")


def get_db_stats() -> dict:
    """Получить статистику по таблицам БД."""
    c = get_connection().cursor()
    stats = {}
    for table in ["dialogs", "tnved_cache", "knowledge_base", "corrections"]:
        c.execute(f"SELECT COUNT(*) as count FROM {table}")
        stats[table] = c.fetchone()["count"]
    return stats


def cleanup_old_dialogs(retention_days: int = 90) -> int:
    """
    Удалить диалоги старше указанного количества дней.
    
    Args:
        retention_days: Срок хранения диалогов в днях (по умолчанию 90)
    
    Returns:
        Количество удалённых записей
    """
    c = get_connection().cursor()
    c.execute("""
        SELECT COUNT(*) as count FROM dialogs 
        WHERE timestamp < datetime('now', '-' || ? || ' days')
    """, (retention_days,))
    count = c.fetchone()["count"]
    
    if count > 0:
        c.execute("""
            DELETE FROM dialogs 
            WHERE timestamp < datetime('now', '-' || ? || ' days')
        """, (retention_days,))
        get_connection().commit()
        logger.info(f"Очищено старых диалогов: {count}")
    
    return count


def export_dialogs(start_date: str = None, end_date: str = None) -> list:
    """
    Экспорт диалогов для команды 'выгрузи логи'.
    
    Args:
        start_date: Начальная дата в формате YYYY-MM-DD
        end_date: Конечная дата в формате YYYY-MM-DD
    
    Returns:
        Список словарей с данными диалогов
    """
    c = get_connection().cursor()
    
    if start_date and end_date:
        c.execute("""
            SELECT user_id, role, content, timestamp 
            FROM dialogs 
            WHERE date(timestamp) BETWEEN ? AND ?
            ORDER BY timestamp
        """, (start_date, end_date))
    elif start_date:
        c.execute("""
            SELECT user_id, role, content, timestamp 
            FROM dialogs 
            WHERE date(timestamp) >= ?
            ORDER BY timestamp
        """, (start_date,))
    else:
        c.execute("""
            SELECT user_id, role, content, timestamp 
            FROM dialogs 
            ORDER BY timestamp DESC 
            LIMIT 1000
        """)
    
    rows = c.fetchall()
    return [{"user_id": row["user_id"], "role": row["role"], 
             "content": row["content"], "timestamp": row["timestamp"]} 
            for row in rows]
