#!/bin/bash
# backup.sh — бэкап WA AI Helper на VDS
# Запуск: ./backup.sh  или по крону

set -e

DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/home/wa/backups"
mkdir -p "$BACKUP_DIR"

# Источники
TEST_DIR="/home/wa/ai-helper-test"
PROD_DIR="/home/wa/ai-helper"
DATA_DIR="/home/wa/bot-data"
TEST_DB="${DATA_DIR}/bot.db"
PROD_DB="${PROD_DIR}/bot.db"

# --- Тестовый бот (bot-data) ---
if [ -f "$TEST_DB" ]; then
    echo "[$DATE] Бэкап тестовой БД (${DATA_DIR})..."
    python3 -c "
import sqlite3, shutil
src = '${TEST_DB}'
dst = '${BACKUP_DIR}/bot_test_${DATE}.db'
shutil.copy2(src, dst)
conn = sqlite3.connect(dst)
conn.execute('PRAGMA integrity_check')
conn.close()
print('OK')
"
    gzip -f "${BACKUP_DIR}/bot_test_${DATE}.db"
    echo "  → ${BACKUP_DIR}/bot_test_${DATE}.db.gz"
fi

# --- Тестовый бот (локальная .db если есть) ---
if [ -f "${TEST_DIR}/bot.db" ]; then
    echo "[$DATE] Бэкап локальной тестовой БД..."
    python3 -c "
import sqlite3, shutil
src = '${TEST_DIR}/bot.db'
dst = '${BACKUP_DIR}/bot_test_local_${DATE}.db'
shutil.copy2(src, dst)
conn = sqlite3.connect(dst)
conn.execute('PRAGMA integrity_check')
conn.close()
print('OK')
"
    gzip -f "${BACKUP_DIR}/bot_test_local_${DATE}.db"
    echo "  → ${BACKUP_DIR}/bot_test_local_${DATE}.db.gz"
fi

if [ -f "${TEST_DIR}/.env" ]; then
    cp "${TEST_DIR}/.env" "${BACKUP_DIR}/env_test_${DATE}"
    echo "  → ${BACKUP_DIR}/env_test_${DATE}"
fi

# --- Продакшен бот ---
if [ -f "$PROD_DB" ]; then
    echo "[$DATE] Бэкап прод БД..."
    python3 -c "
import sqlite3, shutil
src = '${PROD_DB}'
dst = '${BACKUP_DIR}/bot_prod_${DATE}.db'
shutil.copy2(src, dst)
conn = sqlite3.connect(dst)
conn.execute('PRAGMA integrity_check')
conn.close()
print('OK')
"
    gzip -f "${BACKUP_DIR}/bot_prod_${DATE}.db"
    echo "  → ${BACKUP_DIR}/bot_prod_${DATE}.db.gz"
fi

if [ -f "${PROD_DIR}/.env" ]; then
    cp "${PROD_DIR}/.env" "${BACKUP_DIR}/env_prod_${DATE}"
    echo "  → ${BACKUP_DIR}/env_prod_${DATE}"
fi

# --- Systemd сервисы ---
cp /etc/systemd/system/wa-bot*.service "$BACKUP_DIR/" 2>/dev/null || true

# --- Чистка старых бэкапов (оставляем 14 дней) ---
find "$BACKUP_DIR" -name "*.gz" -mtime +14 -delete
find "$BACKUP_DIR" -name "env_*" -mtime +14 -delete

echo "[$DATE] Бэкап готов. Файлы:"
ls -lh "$BACKUP_DIR"/*.gz "$BACKUP_DIR"/env_* 2>/dev/null || true

echo ""
echo "=== Восстановление на новый VDS ==="
echo "1. git clone https://github.com/anbugz/ai-helper-test.git"
echo "2. python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
echo "3. cp env_test_${DATE} .env"
echo "4. zcat bot_test_${DATE}.db.gz > bot.db"
echo "5. sudo cp wa-bot.service /etc/systemd/system/"
echo "6. sudo systemctl enable --now wa-bot"
