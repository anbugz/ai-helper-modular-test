"""
services/amo_leads.py — расширенная работа со сделками West Asia.

Функции:
- Распознавание номера сделки (64К, 73М, 82ЖД, 91А, 107Авто)
- Получение полной карточки сделки с кастомными полями
- Форматирование карточки для Telegram
- Чеклист по текущему этапу
"""
import re
from datetime import datetime
from typing import Optional

# ─── ID кастомных полей ───────────────────────────────────────────────────────
FIELD_IDS = {
    "transport_type":   1084185,  # Тип транспорта (select)
    "incoterms":        1084245,  # INCOTERMS (select)
    "origin":           1084199,  # Пункт отправления
    "destination":      1084201,  # Пункт назначения (РФ)
    "weight":           1084187,  # Вес брутто (кг)
    "volume":           1084197,  # Объём (м³)
    "hs_code":          1084195,  # HS-код
    "cargo_desc":       1084193,  # Описание груза
    "forwarder":        1084211,  # Перевозчик / Forwarder
    "arrival_date":     1084189,  # Дата прибытия (план)
    "container_awb":    1084249,  # Номер контейнера / AWB
    "customs_status":   1084191,  # Статус таможни (select)
    "dt_date":          1084215,  # Дата подачи ДТ
    "gtd_date":         1084219,  # Дата выпуска ГТД
    "gtd_number":       1084247,  # ГТД
}

# ─── Распознавание номера сделки ─────────────────────────────────────────────

# Паттерн: число + суффикс типа
DEAL_NUMBER_PATTERN = re.compile(
    r'\b(\d{1,4})(К|М|ЖД|А|Авто)\b',
    re.IGNORECASE | re.UNICODE
)

DEAL_TYPE_NAMES = {
    'к':    'Карго (сборный)',
    'м':    'Море',
    'жд':   'Прямое ЖД',
    'а':    'Авиа',
    'авто': 'Авто',
}

DEAL_TYPE_EMOJI = {
    'к':    '📦',
    'м':    '🚢',
    'жд':   '🚂',
    'а':    '✈️',
    'авто': '🚚',
}


def parse_deal_number(text: str) -> Optional[dict]:
    """
    Распознаёт номер сделки в тексте.
    Возвращает {'number': '64', 'type': 'к', 'full': '64К', 'search_query': '64К'}
    или None если не найдено.
    """
    match = DEAL_NUMBER_PATTERN.search(text)
    if not match:
        return None
    number = match.group(1)
    deal_type = match.group(2).lower()
    full = f"{number}{match.group(2).upper()}"
    return {
        'number': number,
        'type': deal_type,
        'full': full,
        'type_name': DEAL_TYPE_NAMES.get(deal_type, deal_type),
        'emoji': DEAL_TYPE_EMOJI.get(deal_type, '📋'),
        'search_query': full,
    }


def is_deal_number_request(text: str) -> bool:
    """Проверяет содержит ли текст номер сделки."""
    return bool(DEAL_NUMBER_PATTERN.search(text))


# ─── Извлечение кастомных полей ──────────────────────────────────────────────

def extract_custom_fields(lead: dict) -> dict:
    """Извлекает кастомные поля из сделки AmoCRM."""
    fields = {}
    field_id_to_key = {v: k for k, v in FIELD_IDS.items()}

    for cf in lead.get('custom_fields_values') or []:
        field_id = cf.get('field_id')
        key = field_id_to_key.get(field_id)
        if not key:
            continue
        values = cf.get('values', [])
        if not values:
            continue
        val = values[0].get('value')
        if val is not None:
            # Дата в unix timestamp → человекочитаемый формат
            if key in ('arrival_date', 'dt_date', 'gtd_date') and isinstance(val, (int, float)):
                try:
                    val = datetime.fromtimestamp(int(val)).strftime('%d.%m.%Y')
                except Exception:
                    pass
            fields[key] = val
    return fields


# ─── Форматирование карточки сделки ──────────────────────────────────────────

def format_lead_card(lead: dict, pipelines: dict, users: dict) -> str:
    """Форматирует полную карточку сделки для Telegram."""
    name = lead.get('name', '—')
    lead_id = lead.get('id', '')
    pipeline_id = lead.get('pipeline_id', 0)
    status_id = lead.get('status_id', 0)
    responsible_id = lead.get('responsible_user_id', 0)
    price = lead.get('price', 0)

    pipeline = pipelines.get(pipeline_id, {})
    pipeline_name = pipeline.get('name', '—')
    status_name = pipeline.get('statuses', {}).get(status_id, '—')
    responsible = users.get(responsible_id, '—')

    # Определяем тип сделки по номеру в названии
    deal_info = parse_deal_number(name)
    deal_emoji = deal_info['emoji'] if deal_info else '📋'
    deal_type = deal_info['type_name'] if deal_info else ''

    # Кастомные поля
    cf = extract_custom_fields(lead)

    lines = [
        f"{deal_emoji} <b>{name}</b>",
        f"🆔 ID: <code>{lead_id}</code>",
        f"📊 {pipeline_name} → <b>{status_name}</b>",
        f"👤 Менеджер: {responsible}",
    ]

    if price:
        lines.append(f"💰 Бюджет: {price:,} ₽".replace(',', ' '))

    if deal_type:
        lines.append(f"🏷 Тип: {deal_type}")

    lines.append("")  # разделитель

    # Логистика
    if cf.get('transport_type'):
        lines.append(f"🚛 Транспорт: {cf['transport_type']}")
    if cf.get('incoterms'):
        lines.append(f"📄 Incoterms: {cf['incoterms']}")
    if cf.get('origin') or cf.get('destination'):
        origin = cf.get('origin', '?')
        dest = cf.get('destination', '?')
        lines.append(f"📍 Маршрут: {origin} → {dest}")
    if cf.get('forwarder'):
        lines.append(f"🤝 Перевозчик: {cf['forwarder']}")
    if cf.get('container_awb'):
        lines.append(f"📦 Контейнер/AWB: {cf['container_awb']}")
    if cf.get('weight') or cf.get('volume'):
        wv = []
        if cf.get('weight'): wv.append(f"{cf['weight']} кг")
        if cf.get('volume'): wv.append(f"{cf['volume']} м³")
        lines.append(f"⚖️ Груз: {', '.join(wv)}")
    if cf.get('cargo_desc'):
        lines.append(f"📝 Описание: {cf['cargo_desc'][:80]}")
    if cf.get('hs_code'):
        lines.append(f"🔢 HS-код: {cf['hs_code']}")

    lines.append("")  # разделитель

    # Таможня
    if cf.get('arrival_date'):
        lines.append(f"📅 Прибытие (план): {cf['arrival_date']}")
    if cf.get('customs_status'):
        lines.append(f"🛃 Статус таможни: {cf['customs_status']}")
    if cf.get('dt_date'):
        lines.append(f"📋 Дата подачи ДТ: {cf['dt_date']}")
    if cf.get('gtd_date'):
        lines.append(f"✅ Дата выпуска ГТД: {cf['gtd_date']}")
    if cf.get('gtd_number'):
        lines.append(f"🔖 ГТД: {cf['gtd_number']}")

    # Чеклист по этапу
    checklist = get_stage_checklist(status_name, cf, deal_info)
    if checklist:
        lines.append("")
        lines.append("📌 <b>Что делать сейчас:</b>")
        for item in checklist:
            lines.append(f"  • {item}")

    return '\n'.join(line for line in lines)


# ─── Чеклисты по этапам ──────────────────────────────────────────────────────

def get_stage_checklist(status_name: str, cf: dict, deal_info: Optional[dict]) -> list:
    """Возвращает чеклист действий для текущего этапа сделки."""
    s = status_name.lower()

    if 'новая заявка' in s or 'запрос' in s:
        return [
            "Уточнить у клиента: товар, вес, объём, адрес доставки",
            "Запросить HS-код или описание товара для подбора",
            "Выяснить условия поставки (Incoterms)",
            "Уточнить сроки — когда готов товар",
        ]

    if 'ставка' in s or 'кп' in s or 'рассмотрени' in s:
        return [
            "Запросить ставки у агентов по нужному виду транспорта",
            "Рассчитать таможенные платежи (ТН ВЭД + инвойс)",
            "Подготовить КП клиенту",
            "Поставить задачу: follow-up через 2 дня",
        ]

    if 'договор' in s or 'документ' in s:
        items = [
            "Подписать договор с клиентом",
            "Собрать пакет документов: инвойс, упаковочный лист, договор с поставщиком",
        ]
        if not cf.get('hs_code'):
            items.append("⚠️ HS-код не заполнен — уточнить у Михаила")
        if not cf.get('incoterms'):
            items.append("⚠️ Incoterms не заполнен — уточнить условия поставки")
        return items

    if 'оплата поставщику' in s or 'оплата' in s:
        return [
            "Проверить инвойс поставщика",
            "Согласовать оплату с бухгалтером",
            "После оплаты — зафиксировать в CRM",
            "Запросить подтверждение оплаты (платёжку)",
        ]

    if 'производств' in s:
        return [
            "Запросить у поставщика статус производства",
            "Уточнить дату готовности товара",
            "Предупредить агента о предстоящей отгрузке",
        ]

    if 'бронирован' in s:
        return [
            "Забронировать место у перевозчика/агента",
            "Уточнить дату отправки",
            "Заполнить поле 'Перевозчик/Forwarder' в CRM",
        ]

    if 'отгрузк' in s:
        return [
            "Получить отгрузочные документы от поставщика",
            "Проверить инвойс, упаковочный лист, коносамент/AWB",
            "Передать документы декларанту (Михаил, Анна)",
            "Заполнить номер контейнера/AWB в CRM",
        ]

    if 'в пути' in s or 'отправлен' in s or 'груз вышел' in s:
        arrival = cf.get('arrival_date', '')
        items = [
            f"Груз в пути. Ожидаемое прибытие: {arrival}" if arrival else "Уточнить дату прибытия и заполнить в CRM",
            "Отслеживать статус у перевозчика",
        ]
        if not cf.get('container_awb'):
            items.append("⚠️ Номер контейнера/AWB не заполнен")
        if not cf.get('customs_status'):
            items.append("Предупредить декларанта за 2-3 дня до прибытия")
        return items

    if 'таможн' in s:
        items = []
        customs = cf.get('customs_status', '').lower()
        if 'нужен декларант' in customs:
            items.append("⚠️ Нужен декларант — передать документы Михаилу и Анне")
            items.append("Передать: инвойс, упаковочный лист, договор, транзитную декларацию")
            items.append("Проверить скрин ЕЛС (если сценарий В)")
        else:
            items.append("Уточнить статус таможенного оформления у декларанта")
            items.append("Проверить заполнен ли статус таможни в CRM")
        if not cf.get('hs_code'):
            items.append("⚠️ HS-код не заполнен — уточнить у Михаила")
        if not cf.get('dt_date'):
            items.append("После подачи ДТ — заполнить дату в CRM")
        return items

    if 'выпуск' in s or 'доставк' in s:
        items = [
            "Получить ГТД и УПД от декларанта",
            "Согласовать доставку до клиента",
        ]
        if not cf.get('gtd_number'):
            items.append("Заполнить номер ГТД в CRM")
        if not cf.get('gtd_date'):
            items.append("Заполнить дату выпуска ГТД в CRM")
        items.append("Выставить финальный счёт клиенту")
        items.append("Получить подтверждение получения груза")
        return items

    return []
