"""
handlers/text.py — обработка текстовых сообщений (основной хэндлер).
Перенос из handlers_legacy.py: handle_text.

Логика:
  1. Security сканирование
  2. PII фильтрация
  3. Транслит латиницы → кириллица
  4. Экспорт логов (админ)
  5. Обработка "несогласен"
  6. Режим обучения
  7. Rate limit
  8. Извлечение кодов ТН ВЭД
  9. Поиск по описанию → DeepSeek с уточняющими вопросами
  10. ВЭД-расчёт (fallback-форматирование)
  11. AI-ассистент (общие вопросы)
  12. Курс ЦБ РФ в ответе
"""
import re
import asyncio
from datetime import timedelta
from typing import Dict, Any
from aiogram import Router, types, F
from aiogram.types import Message

from bot_instance import bot
from config import (
    ADMIN_ID, LEARN_MODE, PENDING_CODE_UPDATE,
    RADIO_FEE, CUSTOMS_FEE_RUB, RADIO_ELECTRONICS_CODES_SET,
    TNVED_FULL_NAMES, logger,
)
from database import (
    save_message, save_correction, get_knowledge,
    get_dialogs_for_export, create_logs_xlsx,
    search_tnved_by_sections,
)
from services.security import full_security_scan, is_blocked, contains_pii, redact_pii
from services.tnved import (
    is_radio_electronics, extract_tnved_codes,
    get_tnved_from_cache, calculate_customs_fee,
)
from services.currency import get_cbr_rates, format_cross_rates, convert_fee_to_currency, detect_base_currency
from services.ai import ask_deepseek, build_messages
from services.calc import format_calculation_fallback, strip_ai_assistant_junk
from utils.telegram import safe_send, check_rate_limit
from utils.text import words_to_number, transliterate_latin_to_cyrillic, lemmatize_russian
from utils.ts_parser import extract_ts_components_with_currency

router = Router()


# ------------------------------------------------------------------
# MATERIAL MAP — подбор ТН ВЭД по материалам
# ------------------------------------------------------------------

MATERIAL_MAP = {
    # === ХЛОПОК (5208) ===
    "хлопок": "5208", "хлопка": "5208", "хлопку": "5208", "хлопком": "5208",
    "хлопковый": "5208", "хлопковая": "5208", "хлопковое": "5208", "хлопковые": "5208",
    "хлопковой": "5208", "хлопкового": "5208", "хлопковому": "5208",
    "хлопковых": "5208", "хлопковым": "5208", "хлопковыми": "5208",
    "хлопчатобумажный": "5208", "хлопчатобумажная": "5208",
    "хлопчатобумажное": "5208", "хлопчатобумажные": "5208",
    "хлопчатка": "5208", "хлопчатобумаж": "5208",
    "cotton": "5208",
    # === ШЕРСТЬ (5105) ===
    "шерсть": "5105", "шерсти": "5105", "шерстью": "5105",
    "шерстяной": "5105", "шерстяная": "5105", "шерстяное": "5105",
    "шерстяные": "5105", "шерстяного": "5105",
    "шерстяным": "5105", "шерстяных": "5105",
    "wool": "5105",
    # === ШЁЛК (5007) ===
    "шёлк": "5007", "шелк": "5007", "шёлка": "5007", "шелка": "5007",
    "шёлку": "5007", "шёлком": "5007",
    "шелковый": "5007", "шелковая": "5007", "шелковое": "5007",
    "шелковые": "5007", "шелковой": "5007", "шелковых": "5007",
    "шелковым": "5007", "шелковыми": "5007",
    "silk": "5007",
    # === ЛЁН (5309) ===
    "лён": "5309", "лен": "5309", "льна": "5309",
    "льняной": "5309", "льняная": "5309", "льняное": "5309",
    "льняные": "5309", "льняного": "5309",
    "flax": "5309",
    # === СИНТЕТИКА (5407 / 5501) ===
    "синтетика": "5407", "синтетики": "5407", "синтетикой": "5407",
    "синтетический": "5407", "синтетическая": "5407", "синтетическое": "5407",
    "синтетические": "5407", "синтетического": "5407",
    "полиэстер": "5407", "полиэстра": "5407", "полиэстера": "5407",
    "полиэфир": "5407",
    "polyester": "5407",
    "акрил": "5501", "акриловый": "5501", "акриловая": "5501",
    # === КОЖА (4202) ===
    "кожа": "4202", "кожи": "4202", "кожей": "4202", "кожу": "4202",
    "кожаный": "4202", "кожаная": "4202", "кожаное": "4202",
    "кожаные": "4202", "кожаной": "4202", "кожаных": "4202",
    "кожаным": "4202",
    "leather": "4202",
    # === МЕТАЛЛЫ ===
    "сталь": "7326", "стали": "7326", "стальная": "7326", "стальной": "7326",
    "нержавейка": "7326", "нержавеющая": "7326", "нержавеющей": "7326",
    "алюминий": "7602", "алюминия": "7602", "алюминиевый": "7602",
    "медь": "7409", "медная": "7409", "медный": "7409", "меди": "7409",
    "латунь": "7409", "латунная": "7409", "латуни": "7409",
    "цинк": "7901", "цинковый": "7901",
    # === ЭЛЕКТРОНИКА ===
    "телефон": "8517", "телефона": "8517", "телефонов": "8517",
    "смартфон": "8517", "смартфона": "8517",
    "iphone": "8517", "айфон": "8517",
    "ноутбук": "8471", "ноутбука": "8471",
    "компьютер": "8471", "компьютера": "8471", "компьютерный": "8471",
    "планшет": "8471", "планшета": "8471",
    "монитор": "8528", "монитора": "8528",
    "телевизор": "8528", "телевизора": "8528",
    # === ОДЕЖДА ===
    "куртка": "6201", "куртки": "6201", "куртку": "6201",
    "пальто": "6201",
    "пуховик": "6201", "пуховика": "6201",
    "рубашка": "6205", "рубашки": "6205", "рубашку": "6205",
    "блузка": "6206", "блузки": "6206", "блузку": "6206",
    "футболка": "6109", "футболки": "6109", "футболку": "6109",
    "брюки": "6203", "брюк": "6203",
    "джинсы": "6204", "джинсов": "6204",
    "юбка": "6204", "юбки": "6204", "юбку": "6204",
    # === ОБУВЬ ===
    "обувь": "6403", "обуви": "6403", "обувью": "6403",
    "кроссовки": "6404", "кроссовок": "6404",
    "ботинки": "6403", "ботинок": "6403",
    "туфли": "6403", "туфель": "6403",
    "сапоги": "6403", "сапог": "6403",
    # === ПРОДУКТЫ ===
    "кофе": "0901", "чай": "0902", "чая": "0902",
    "шоколад": "1806", "шоколада": "1806",
    "конфеты": "1704", "конфет": "1704",
    "сок": "2009", "сока": "2009",
    "вино": "2204", "вина": "2204",
    # === МЕБЕЛЬ ===
    "стул": "9403", "стула": "9403", "стулья": "9403",
    "стол": "9403", "стола": "9403",
    "диван": "9401", "дивана": "9401",
    "кровать": "9403", "кровати": "9403",
    "шкаф": "9403", "шкафа": "9403",
    # === ПРОЧЕЕ ===
    "игрушка": "9503", "игрушки": "9503",
    "велосипед": "8712", "велосипеда": "8712",
    "самокат": "8712", "самоката": "8712",
    "косметика": "3304", "косметики": "3304",
    "парфюм": "3303",
    "зубная": "3306",
    "лампа": "8539", "лампы": "8539",
    "светодиод": "8539", "светодиода": "8539",
    "led": "8539",
    # === ОБЩИЕ ===
    "ткань": "5208", "ткани": "5208", "тканей": "5208",
    "тканью": "5208", "тканям": "5208", "тканями": "5208",
    "трикотаж": "6004", "трикотажа": "6004",
}


# ------------------------------------------------------------------
# VED INTENT KEYWORDS
# ------------------------------------------------------------------

VED_INTENT_KEYWORDS = (
    # Прямые ВЭД-термины
    "тн вэд", "таможн", "пошлин", "деклар", "оформлен",
    # Действия с кодом
    "подбери", "подбир", "найди код", "какой код", "код товара",
    "код для", "код на ", "шифр", "номенклатур",
    # Материалы
    "хлопок", "хлопчатобумажн", "шерсть", "шерстяной", "шёлк", "шелк", "шелковый",
    "лён", "лен ", "льняной", "синтетика", "полиэстер", "полиэфир", "акрил",
    "кожа", "кожаный", "сталь", "нержавейка", "алюминий", "медь", "латунь", "цинк",
    "телефон", "смартфон", "ноутбук", "компьютер", "планшет", "монитор", "телевизор",
    # Категории товаров
    "ткань", "ткани", "трикотаж", "текстиль", "материал", "сырьё", "сырье",
    "одежда", "обувь", "куртка", "пальто", "пуховик", "рубашка", "блузка", "футболка",
    "брюки", "джинсы", "юбка", "кроссовки", "ботинки", "туфли", "сапоги",
    "электроника", "радио", "лампа", "светодиод",
    "мебель", "стул", "стол", "диван", "кровать", "шкаф",
    "продукт", "кофе", "чай", "шоколад", "конфеты", "сок", "вино",
    "косметика", "парфюм", "игрушка", "велосипед", "самокат",
    # Логистика
    "груз", "перевозк", "фрахт", "доставк", "контейнер", "партия",
    "карго", "логистик", "маршрут", "инвойс", "упаковк",
    # Бизнес-процессы ВЭД
    "контракт", "поставщик", "партнёр", "партнер", "клиент",
    "импорт", "экспорт", "закупк", "заказ", "сделка",
    "документ", "сертификат", "декларац", "разрешени",
    "счёт", "счет", "платёж", "платеж", "оплат",
    # Расчётные
    "расчёт", "посчитай", "сколько будет", "сколько плат", "узнать плат",
    "ндс", "сбор", "страховк", "платеж",
    # Общие ВЭД-контексты
    "китай", "китайск", "турци", "оаэ", "индия", "вьетнам", "европ",
)


# ------------------------------------------------------------------
# STOP WORDS для фильтрации ключевых слов
# ------------------------------------------------------------------

STOP_WORDS = {
    # Служебные и вежливые
    "подбери", "какой", "код", "товар", "штука", "кг", "вес",
    "цена", "стоимость", "сумма", "рубль", "доллар", "евро", "юань",
    "нужен", "расчёт", "помоги", "пожалуйста", "привет", "скажи",
    "будь", "добрый", "можно", "сколько", "стоить", "будет",
    "прошу", "дай", "выдай", "покажи", "нужно", "надо", "делать",
    # Предлоги и союзы
    "из", "для", "под", "при", "про", "без", "над", "через", "перед",
    "после", "между", "около", "возле", "пока", "если", "когда",
    # Местоимения и указатели
    "такой", "этот", "также", "очень", "только", "чтобы", "который",
    "которая", "которые", "которых", "здесь", "там", "тут", "где",
    # Единицы измерения
    "штук", "палет", "короб", "мест", "сантиметр", "сантиметров",
    "плотност", "ширина", "длина", "высота", "размер",
    "процент", "масса", "грамм", "метр", "сантиметр", "миллиметр",
    # "Бытовые" слова
    "заявка", "заявки", "заявку", "заявок",
    "пришла", "пришло", "пришёл", "пришли", "приходить",
    "почта", "почту", "почтой", "почте", "письмо", "письма", "email",
    "новая", "новый", "новое", "новые",
    "сделать", "сделал", "делаю", "делать", "делаешь",
    "работа", "работу", "работы", "работе", "задача", "задачу",
    "встреча", "встречу", "звонок", "звоню", "звонить",
    "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье",
    "сегодня", "вчера", "завтра", "утром", "днём", "вечером",
    "утро", "вечер", "день", "неделя", "месяц", "год",
    "пока", "потом", "сейчас", "сразу", "позже", "раньше",
    "хочу", "хотел", "нужен", "надо", "надобно", "необходимо",
    "мне", "тебе", "нам", "вам", "ему", "ей", "им",
    "я", "ты", "он", "она", "оно", "мы", "вы", "они",
    "быть", "есть", "нет", "да", "нету",
}


# ------------------------------------------------------------------
# MAIN HANDLER
# ------------------------------------------------------------------

@router.message(F.text)
async def handle_text(message: Message):
    """Основной обработчик текстовых сообщений."""
    user_id = message.from_user.id
    user_text = message.text or ""
    if not user_text or user_text.startswith("/"):
        return

    # === ПОЛНОЕ SECURITY СКАНИРОВАНИЕ ===
    is_attack, reason = full_security_scan(user_text, user_id)
    if is_attack:
        if reason == "USER_BLOCKED":
            await message.answer("⛔ Ваш аккаунт временно заблокирован за подозрительную активность.")
            return
        
        logger.warning(f"SECURITY BLOCKED [{reason}] from user {user_id}: {user_text[:100]}")
        
        # Определяем, забанен ли пользователь
        user_banned = is_blocked(user_id)
        
        await message.answer(
            "⛔ Запрос отклонён по политике безопасности.\n"
            "Если это легитимный запрос — обратитесь к администратору."
        )
        
        # Уведомление админу
        if ADMIN_ID:
            try:
                block_msg = "\n🚫 Пользователь ЗАБЛОКИРОВАН" if user_banned else ""
                await bot.send_message(
                    ADMIN_ID,
                    f"⚠️ <b>SECURITY: {reason}</b>{block_msg}\n"
                    f"User: <code>{user_id}</code>\n"
                    f"Text: <code>{user_text[:200]}</code>",
                )
            except Exception:
                pass
        return
    
    # === PII-ФИЛЬТР (логирование) ===
    has_pii, pii_types = contains_pii(user_text)
    if has_pii:
        logger.info(f"PII detected from user {user_id}: {pii_types}")
        user_text_clean = redact_pii(user_text)
    else:
        user_text_clean = user_text
    
    text_lower = user_text_clean.lower()

    # === ОБРАБОТКА ТРАНСЛИТА (vatnye volokna → ватные волокна) ===
    has_cyrillic = bool(re.search(r'[а-яё]', text_lower))
    has_latin = bool(re.search(r'[a-z]', text_lower))
    if not has_cyrillic and has_latin:
        text_lower = transliterate_latin_to_cyrillic(text_lower)

    # === ЭКСПОРТ ЛОГОВ (админ) ===
    log_keywords = ["логи", "выгрузи логи", "экспорт логов", "логи работы"]
    if user_id == ADMIN_ID and any(
        text_lower.startswith(k) or f" {k} " in f" {text_lower} " for k in log_keywords
    ):
        from utils.telegram import parse_date_range
        df, dt = parse_date_range(user_text)
        logs = get_dialogs_for_export(df, dt)
        if not logs:
            await message.answer("📭 Пусто.")
            return
        xb = create_logs_xlsx(logs, "logs")
        fn = f"logs_{df or 'all'}_{dt or 'all'}.xlsx"
        await message.answer_document(
            document=types.BufferedInputFile(xb, filename=fn),
            caption=f"📊 {len(logs)} записей",
        )
        return

    # === ОБРАБОТКА "НЕСОГЛАСЕН" ===
    if any(
        k in text_lower for k in ["несогласен", "не согласен", "неправильно", "неверно"]
    ):
        if not message.reply_to_message:
            await message.answer(
                "Для записи замечания ответьте на сообщение бота словом «несогласен»."
            )
            return
        orig = message.reply_to_message.text or ""
        save_correction(
            user_id,
            message.from_user.username or "",
            orig[:500],
            user_text[:500],
        )
        if ADMIN_ID:
            try:
                await bot.send_message(
                    ADMIN_ID,
                    f"⚠️ @{message.from_user.username or user_id}: {user_text[:200]}",
                )
            except Exception as e:
                logger.error(f"Не удалось уведомить: {e}")
        await message.answer("⚠️ Замечание записано.")
        return

    # === РЕЖИМ ОБУЧЕНИЯ ===
    if user_id in LEARN_MODE:
        LEARN_MODE[user_id]["content"] += "\n" + user_text
        await message.answer("✅ Записано.")
        return

    # === RATE LIMIT ===
    if not check_rate_limit(user_id):
        return

    logger.info(f"User {user_id}: {user_text[:80]}...")
    save_message(user_id, message.from_user.username or "", "user", user_text)

    # === ИЗВЛЕЧЕНИЕ КОДОВ ТН ВЭД ===
    codes = extract_tnved_codes(user_text)
    radio_detected = any(is_radio_electronics(c) for c in codes)

    found_codes = []
    missing = []
    if codes:
        for c in codes[:3]:
            info = get_tnved_from_cache(c)
            if info:
                # Очищаем наименование от некорректных символов
                info["name"] = info.get("name", "").replace("🠺", "→").replace("🠔", "←").strip()
                found_codes.append(info)
            else:
                missing.append(c)

    # === ОПРЕДЕЛЕНИЕ ТИПА ЗАПРОСА ===
    calc_words = (
        "инвойс", "сумма", "стоимость", "расчёт", "платеж",
        "пошлина", "ндс", "сбор", "таможенная", "тс",
        "фрахт", "страховк", "посчитай", "сколько будет",
        "узнать плат", "сколько плат",
    )
    # Удаляем коды ТН ВЭД из текста (нормализуем пробелы), потом ищем суммы
    text_normalized = re.sub(r"(\d)\s+(?=\d)", r"\1", user_text)
    text_no_codes = re.sub(r"\d{8,10}", "", text_normalized)
    # Проверяем наличие числа ≥ 1000 (инвойс/фрахт/страховка)
    has_amount = bool(re.search(r"(?<!\d)\d{4,}(?!\d)", text_no_codes))
    is_calc = any(w in text_lower for w in calc_words) or (
        bool(found_codes) and has_amount
    )

    # === СЦЕНАРИЙ 2: БЫСТРЫЙ ОТВЕТ ПО КОДУ (без расчёта) ===
    if codes and found_codes and not is_calc:
        info = found_codes[0]
        pt = info["parsed_tariff"]
        if pt.get("type") in ("min", "plus", "fixed_eur"):
            duty_type = f"комбинированная ({pt['formula']})"
        elif pt.get("type") == "percent":
            duty_type = "адвалорная"
        else:
            duty_type = info["tariff"]
        vat = (
            "10%"
            if any(w in info["name"].lower() for w in ("пищев", "детск", "медиц", "книг", "печат"))
            else "22%"
        )
        name_clean = info["name"].replace("🠺", "→").replace("🠔", "←")
        radio = (
            "\n\n⚡ <b>РАДИОСБОР:</b> 73 860 ₽ (фиксированный)\n"
            "   <i>По Приложению №1 к ПП РФ №1637</i>"
            if any(is_radio_electronics(c) for c in codes)
            else ""
        )
        await safe_send(
            message,
            f"📋 <code>{info['code']}</code>\n"
            f"🔧 {name_clean}\n"
            f"💰 Пошлина: {info['tariff']} — {duty_type}\n"
            f"🧾 НДС: {vat}"
            f"{radio}"
            f"\n\n📌 <i>Точную информацию уточняйте у декларанта.</i>"
        )
        return

    # === КОД НЕ НАЙДЕН ===
    if codes and not found_codes:
        await safe_send(
            message, f"❌ Код не найден: <code>{', '.join(missing)}</code>"
        )
        return

    # === СЦЕНАРИЙ 3: ПОИСК ПО ОПИСАНИЮ (если нет явных кодов) ===
    if not found_codes and not codes:
        # ДЕТЕКЦИЯ ВЭД-ИНТЕНТА
        has_ved_intent = any(kw in text_lower for kw in VED_INTENT_KEYWORDS)

        # --- Был ли недавно подбор кода? ---
        # Если бот в прошлом ответе подбирал код / задавал уточнения, то текущее
        # сообщение, скорее всего, продолжение темы. В этом случае НЕ подмешиваем
        # коды материалов (чтобы «хлопок» не утянул в ткани) — пусть LLM сама решит
        # по истории диалога, новый это запрос или уточнение.
        recently_picking = False
        try:
            from database import get_dialog_history
            _prev = get_dialog_history(user_id, limit=4)
            _earlier = _prev[:-1] if _prev else []
            _prev_bot = next((m["content"] for m in reversed(_earlier) if m["role"] == "assistant"), "")
            _prev_user = next((m["content"] for m in reversed(_earlier) if m["role"] == "user"), "")
            _prev_combined = (_prev_bot + " " + _prev_user).lower()

            bot_was_picking = any(
                marker in _prev_bot.lower()
                for marker in ("тн вэд", "уточняющие вопрос", "уточните", "наиболее вероятн", "подбор", "группа")
            )

            # Материал в текущем сообщении
            _kw_in_msg = [w for w in re.findall(r'[а-яёa-z]{4,}', text_lower) if w not in STOP_WORDS]
            _materials_now = [
                w for w in _kw_in_msg
                if (w in MATERIAL_MAP) or (lemmatize_russian(w) in MATERIAL_MAP)
            ]
            # Новый материал = тот, которого НЕ было в предыдущем диалоге.
            # «хлопок» после «хлопковые футболки» — не новый. «алюминий» — новый.
            _has_new_material = any(
                m[:4] not in _prev_combined for m in _materials_now
            ) if _materials_now else False

            has_new_intent = bool(
                re.search(r"(?<!\d)\d{4,}(?!\d)", user_text)
                or any(w in text_lower for w in ("посчитай", "подбери", "инвойс", "фрахт", "сколько", "рассчитай"))
                or _has_new_material
            )
            # Продолжение темы, только если бот недавно подбирал И нет признаков нового запроса
            recently_picking = bool(bot_was_picking and not has_new_intent)
            logger.info(
                f"[CTX DEBUG] bot_was_picking={bot_was_picking}, "
                f"materials_now={_materials_now}, has_new_material={_has_new_material}, "
                f"has_new_intent={has_new_intent}, recently_picking={recently_picking}, "
                f"prev_bot_len={len(_prev_bot)}, hist_len={len(_prev)}"
            )
        except Exception as e:
            logger.warning(f"Не удалось проверить контекст диалога: {e}")

        if has_ved_intent:
            # === БЛОК ПОИСКА ПО МАТЕРИАЛАМ ===
            # Извлекаем ключевые слова (4+ букв)
            keywords = re.findall(r'[а-яёa-z]{4,}', text_lower)
            keywords = [w for w in keywords if w not in STOP_WORDS]
            seen = set()
            keywords = [w for w in keywords if not (w in seen or seen.add(w))]

            # --- Шаг 1: Поиск по маппингу материалов (с лемматизацией) ---
            matched_sections = set()
            lemmatized_hits = []
            for kw in keywords:
                # Прямое совпадение
                if kw in MATERIAL_MAP:
                    matched_sections.add(MATERIAL_MAP[kw])
                    lemmatized_hits.append(kw)
                else:
                    # Пробуем лемматизировать
                    lemma = lemmatize_russian(kw)
                    if lemma in MATERIAL_MAP:
                        matched_sections.add(MATERIAL_MAP[lemma])
                        lemmatized_hits.append(f"{kw}→{lemma}")
                    # Пробуем проверить начало слова (хлопковой → хлоп)
                    elif len(kw) >= 5:
                        for base_key, section in MATERIAL_MAP.items():
                            if len(base_key) >= 4 and kw.startswith(base_key[:4]):
                                matched_sections.add(section)
                                lemmatized_hits.append(f"{kw}~{base_key}")
                                break
        
            all_results = []
            if matched_sections and not recently_picking:
                all_results = search_tnved_by_sections(list(matched_sections))
        
            # --- ВСЕГДА Используем DeepSeek с уточняющими вопросами ---
            context_parts = [
                f"[КОНТЕКСТ: запрос на подбор кода ТН ВЭД]",
                f"Запрос пользователя: {user_text}",
            ]
        
            if lemmatized_hits:
                context_parts.append(f"Распознанные материалы: {', '.join(lemmatized_hits)}")
        
            if all_results:
                context_parts.append(f"\nНайденные варианты кодов из БД:")
                # Убираем дубликаты по коду
                seen_codes = set()
                unique_results = []
                for r in all_results[:8]:
                    if r["code"] not in seen_codes:
                        seen_codes.add(r["code"])
                        unique_results.append(r)
                for r in unique_results[:5]:
                    name = (r["name"] or "—").replace("🠺", "→").strip()
                    context_parts.append(f"  {r['code']} | {name[:120]} | {r['tariff']}")
            else:
                context_parts.append("\nВ БД нет точных совпадений по материалу.")
            
            # === ПОИСК ПО БАЗЕ ЗНАНИЙ — TF-IDF ===
            try:
                from services.search import tfidf_search
                kb_results = tfidf_search(user_text, top_n=4, min_score=0.05)
                # Если найденные секции из одного документа — добираем ещё секции из него же
                if kb_results:
                    from database import get_all_knowledge_with_ids
                    source_docs = set(
                        k.get("source_doc") for k in kb_results if k.get("source_doc")
                    )
                    if len(source_docs) == 1:
                        # Один документ — берём все его секции (до 8)
                        all_kb = get_all_knowledge_with_ids()
                        src = list(source_docs)[0]
                        same_doc = [k for k in all_kb if k.get("source_doc") == src]
                        if len(same_doc) > len(kb_results):
                            # Добавляем секции которых ещё нет в результатах
                            found_ids = {k["id"] for k in kb_results}
                            extra = [k for k in same_doc if k["id"] not in found_ids]
                            kb_results = kb_results + extra[:max(0, 8 - len(kb_results))]
                if kb_results:
                    context_parts.append("\n\n[КОНТЕКСТ ИЗ БАЗЫ ЗНАНИЙ]:")
                    for k in kb_results:
                        topic = k.get("topic", "")
                        content = k.get("content", "")[:4000]
                        context_parts.append(f"\n--- {topic} ---\n{content}")
                    context_parts.append("\nВАЖНО: дай ПОЛНЫЙ подробный ответ с контактами, ФИО, телефонами, email. НЕ сокращай. НЕ выдумывай.")
            except Exception as e:
                logger.warning(f"KB search error: {e}")
        
            context_parts.append(
                "\n\n=== ИНСТРУКЦИЯ ДЛЯ ОТВЕТА ===\n"
                "Ты — эксперт West Asia по ВЭД, логистике и внутренним процессам компании.\n"
                "Если в контексте выше есть ответ на вопрос пользователя — ответь на основе контекста.\n"
                "ВАЖНО: если в контексте есть контактные данные (телефон, email, адрес, Telegram) — выведи их ПОЛНОСТЬЮ, без сокращений.\n"
                "Если в контексте нет ответа — помоги с подбором кода ТН ВЭД:\n"
                "1. Начни с краткого анализа: какая ГРУППА ТН ВЭД (первые 4 цифры) наиболее вероятна.\n"
                "2. Если в диалоге выше ты УЖЕ задавал уточняющие вопросы и пользователь на них ответил — "
                "НЕ повторяй вопросы заново, а уточни код на основе полученных ответов. "
                "Если же это первое обращение — задай 2-4 УТОЧНЯЮЩИХ ВОПРОСА (без ответов на них точный код не определить):\n"
                "   - Для тканей: плотность (г/м²), переплетение (саржа, полотняное), состав (%), отделка, ширина\n"
                "   - Для электроники: назначение, технические характеристики\n"
                "   - Для одежды: пол, возраст, материал, способ изготовления\n"
                "   - Для металлов: сплав, форма, обработка\n"
                "   - Общие: страна происхождения, назначение, технические параметры\n"
                "3. Если есть похожие группы — укажи альтернативы с кратким пояснением.\n"
                "4. КРИТИЧЕСКИ ВАЖНО — ЗАПРЕЩЕНО ВЫДУМЫВАТЬ ЦИФРЫ:\n"
                "   - НЕ называй конкретный размер пошлины (никаких '15%', '20%', '15-20%', 'X евро/кг').\n"
                "   - НЕ называй ставку НДС числом (даже '20%' — это НЕВЕРНО, актуальная базовая 22%, но её всё равно НЕ пиши).\n"
                "   - НЕ придумывай ставки по странам, преференции в процентах, пороги.\n"
                "   - Точные ставки есть ТОЛЬКО в базе ТН ВЭД — если кода нет в контексте выше, ставку знать невозможно.\n"
                "   - Вместо цифр пиши: 'точную ставку пошлины и НДС уточните по конкретному коду у декларанта'.\n"
                "5. НЕ пиши курс ЦБ. НЕ давай финальный расчёт платежей.\n"
                "6. В конце: '📌 Точный код и ставки подтвердите у декларанта или через предварительное решение ФТС.'\n"
                "7. Формат: кратко, структурировано, с эмодзи."
            )
        
            extra = "\n".join(context_parts)

            # Ограничиваем общий размер промпта
            if len(extra) > 12000:
                extra = extra[:12000] + "\n...[контекст обрезан]"
            logger.info(f"[KB DEBUG s4] prompt len={len(extra)}, recently_picking={recently_picking}")

            # Историю подаём ТОЛЬКО если это продолжение темы (recently_picking).
            # Для нового товара/расчёта — без истории, чтобы не смешивать с прошлым.
            msgs = build_messages(
                user_id, user_text,
                extra_context=extra,
                include_history=recently_picking,
                history_limit=6,
            )
            answer = await ask_deepseek(msgs)
            answer = strip_ai_assistant_junk(answer)
            logger.info(f"[KB DEBUG s4] DeepSeek answer: {answer[:500]}")
            
            await safe_send(message, answer)
            return

    # === ОПРЕДЕЛЯЕМ ТИП ЗАПРОСА ===
    base_cur = detect_base_currency(user_text)
    has_ins = any(w in text_lower for w in ("страховка", "страхование"))

    # Инициализация переменных (используются в обоих сценариях)
    ti = found_codes[0] if found_codes else None
    vat_rate = 0.22
    customs_fee_rub = 0.0
    ts_fallback = 0.0
    ts_components: Dict[str, Dict[str, Any]] = {}
    comps: Dict[str, Dict[str, Any]] = {}

    rates = None
    try:
        rates = await get_cbr_rates()
    except Exception as e:
        logger.error(f"Курсы: {e}")

    if is_calc and found_codes:
        # === СЦЕНАРИЙ 1: ВЭД-РАСЧЁТ ===
        cr = format_cross_rates(rates) if rates else ""
        extra = (
            f"[КУРСЫ ЦБ РФ {rates.get('DATE','') if rates else ''}] "
            f"CNY={rates.get('CNY','') if rates else ''}₽ "
            f"USD={rates.get('USD','') if rates else ''}₽ "
            f"EUR={rates.get('EUR','') if rates else ''}₽. "
            f"Кросс: {cr}. Валюта: {base_cur}. НДС: 22%/10%. "
        )
        extra += (
            "ТС (п.1 ст.40 ТК ЕАЭС): Инвойс + Фрахт + Страховка + Упаковка + Прочее. "
            "Не указано → 0. Всё в валюте инвойса. "
            "Конвертация: чужая валюта → ₽ ЦБ → валюта инвойса. "
            "СБОР (таможенный и радио): считай в ₽, затем конвертируй в валюту инвойса (CNY/USD/EUR). "
            "НЕ пиши курс ЦБ РФ в ответе — он будет добавлен автоматически. "
        )
        if has_ins:
            extra += "Страховка — в ТС. "
        extra += "НЕ придумывай ставки и курсы."

        # Удаляем коды ТН ВЭД перед парсингом сумм, чтобы код не стал инвойсом
        text_clean_for_ts = re.sub(r"(\d)\s+(?=\d)", r"\1", user_text)
        # Теперь удаляем коды (уже без пробелов)
        for c in codes:
            text_clean_for_ts = text_clean_for_ts.replace(c, "")
        
        comps = extract_ts_components_with_currency(text_clean_for_ts)
        # Базовая валюта = валюта инвойса, если определена
        if "invoice" in comps and comps["invoice"]["currency"] != "RUB":
            base_cur = comps["invoice"]["currency"]
        else:
            base_cur = detect_base_currency(user_text)

        # Вычисляем ТС в валюте инвойса с конвертацией
        if "invoice" in comps:
            inv = comps["invoice"]
            ts_fallback += inv["value"]
            ts_components["invoice"] = {
                "value": inv["value"], "currency": inv["currency"],
                "converted": inv["value"], "rate": None,
            }

        for key in ("freight", "insurance"):
            if key in comps:
                comp = comps[key]
                val = comp["value"]
                cur = comp["currency"]
                converted = val
                rate_info = None
                if cur != base_cur and rates and base_cur in rates:
                    try:
                        if cur == "RUB":
                            # RUB → валюта инвойса: делим на курс валюты
                            converted = round(val / float(rates[base_cur]), 2)
                            rate_info = f"{val:,.0f} ₽ → {converted:,.2f} {base_cur}"
                        elif cur in rates:
                            # Чужая валюта → RUB → валюта инвойса
                            rub_val = val * float(rates[cur])
                            converted = round(rub_val / float(rates[base_cur]), 2)
                            rate_info = f"{val} {cur} → {rub_val:,.2f} ₽ → {converted:,.2f} {base_cur}"
                    except (ValueError, TypeError, ZeroDivisionError):
                        pass
                ts_fallback += converted
                ts_components[key] = {
                    "value": val, "currency": cur,
                    "converted": converted, "rate": rate_info,
                }

        vat_rate = (
            0.10
            if any(
                w in ti["name"].lower()
                for w in ("пищев", "детск", "медиц", "книг", "печат")
            )
            else 0.22
        )

        ts_rub_for_fee = 0.0
        if ts_fallback and rates:
            if base_cur == "RUB":
                ts_rub_for_fee = ts_fallback
            elif base_cur in rates:
                try:
                    ts_rub_for_fee = ts_fallback * float(rates[base_cur])
                except (ValueError, TypeError):
                    pass

        if radio_detected:
            customs_fee_rub = RADIO_FEE
        else:
            customs_fee_rub = calculate_customs_fee(ts_rub_for_fee)

        # ВЭД-расчёт: НЕ вызываем DeepSeek, сразу fallback
        answer = ""

    else:
        # === СЦЕНАРИЙ 3: AI-АССИСТЕНТ (общий вопрос) ===
        extra = "Ты AI-помощник West Asia для менеджеров по ВЭД. "
        extra += "ДУМАЙ перед ответом: проанализируй что именно спрашивает менеджер, найди в контексте самое релевантное, не смешивай разные понятия. "
        extra += "Например: 'декларант' — это сотрудник West Asia (Анна, Михаил, Александра), а не экспедитор/агент. 'Агент авиа' — это внешний партнёр по авиадоставке, а не декларант. "
        extra += "Если в вопросе несколько смыслов — выбери наиболее очевидный для менеджера ВЭД в контексте West Asia. "
        extra += "НЕ пиши курс ЦБ РФ в ответе — он будет добавлен автоматически. "
        extra += (
            "НЕ выдумывай числовые ставки пошлины и НДС: если точных данных по коду ТН ВЭД нет, "
            "не называй проценты ('15%', '20%') и не придумывай ставку НДС — "
            "пиши 'уточните точную ставку у декларанта по конкретному коду'. "
            "КРИТИЧЕСКИ ВАЖНО — ЗАПРЕЩЕНО ВЫДУМЫВАТЬ КОНТАКТЫ И КОМПАНИИ: "
            "если в базе знаний (контексте выше) нет данных об агентах, экспедиторах, партнёрах, "
            "сотрудниках или любых других конкретных компаниях/людях — "
            "НЕ придумывай названия фирм, ФИО, телефоны, email, специализации. "
            "Вместо этого честно скажи: 'В базе данных West Asia не найдено информации по этому запросу. "
            "Обратитесь к менеджеру для получения актуального списка.' "
            "Правило: если контакт не пришёл в контексте — его не существует для тебя."
        )
        
        # === ПОИСК ПО БАЗЕ ЗНАНИЙ — TF-IDF ===
        try:
            from services.search import tfidf_search
            kb_results = tfidf_search(user_text, top_n=4, min_score=0.05)

            # Умная фильтрация: если спрашивают про декларанта — убираем записи про агентов/экспедиторов
            _q = text_lower
            if any(w in _q for w in ("декларант", "декларанта", "декларанты")):
                kb_results = [
                    k for k in kb_results
                    if not any(w in k.get("topic", "").lower() for w in ("агент", "экспедитор", "авиа", "авто", "море", "жд"))
                ]
            # И наоборот: если спрашивают про агентов/экспедиторов — убираем записи про декларантов
            elif any(w in _q for w in ("агент", "экспедитор", "перевозчик")):
                kb_results = [
                    k for k in kb_results
                    if "декларант" not in k.get("topic", "").lower()
                ]

            # Если найденные секции из одного документа — добираем ещё секции из него же
            if kb_results:
                from database import get_all_knowledge_with_ids
                source_docs = set(
                    k.get("source_doc") for k in kb_results if k.get("source_doc")
                )
                if len(source_docs) == 1:
                    all_kb = get_all_knowledge_with_ids()
                    src = list(source_docs)[0]
                    same_doc = [k for k in all_kb if k.get("source_doc") == src]
                    if len(same_doc) > len(kb_results):
                        found_ids = {k["id"] for k in kb_results}
                        extra_docs = [k for k in same_doc if k["id"] not in found_ids]
                        kb_results = kb_results + extra_docs[:max(0, 8 - len(kb_results))]
            if kb_results:
                extra += "\n\n[КОНТЕКСТ ИЗ БАЗЫ ЗНАНИЙ]:\n"
                for k in kb_results:
                    topic = k.get("topic", "")
                    content = k.get("content", "")[:4000]
                    extra += f"\n--- {topic} ---\n{content}\n"
                extra += "\nВАЖНО: дай ПОЛНЫЙ подробный ответ с контактами, ФИО, телефонами, email. НЕ сокращай. НЕ выдумывай данных которых нет в контексте.\n"
        except Exception as e:
            logger.warning(f"Ошибка поиска в knowledge_base: {e}")
        
        # Ограничиваем общий размер промпта
        if len(extra) > 12000:
            extra = extra[:12000] + "\n...[контекст обрезан]"
        logger.info(f"[KB DEBUG s3] prompt len={len(extra)}, has_kb={'[КОНТЕКСТ' in extra}")
        # AI-ассистент — без истории (чтобы не склеивались запросы)
        msgs = build_messages(user_id, user_text, extra_context=extra, include_history=False)
        answer = await ask_deepseek(msgs)
        logger.info(f"[KB DEBUG s3] DeepSeek answer: {answer[:500]}")
        
        # Лёгкая очистка
        answer = strip_ai_assistant_junk(answer)

    # --- РАСЧЁТНЫЙ ЗАПРОС: чистый fallback ---
    if is_calc and found_codes and ts_fallback and base_cur:
        code_val = found_codes[0]["code"]
        name_val = TNVED_FULL_NAMES.get(
            found_codes[0]["code"][:6], found_codes[0]["name"]
        )
        answer = format_calculation_fallback(
            code=code_val,
            name=name_val,
            currency=base_cur,
            rates=rates or {},
            tariff_info=ti,
            is_radio=radio_detected,
            customs_fee_rub=customs_fee_rub,
            vat_rate=vat_rate,
            ts_fallback=ts_fallback,
            ts_components=ts_components,
            weight_kg=comps.get("weight_kg"),
        )
    else:
        # --- ШАПКА (только для не-расчётных или без суммы) ---
        header = ""
        if found_codes:
            info = found_codes[0]
            pt = info["parsed_tariff"]
            header = f"📋 <code>{info['code']}</code>\n"
            name_clean = re.sub(r"\s*\(за исключением[^)]+", "", info["name"]).strip()
            name_clean = name_clean.replace("🠺", "→").replace("🠔", "←")
            full_name = TNVED_FULL_NAMES.get(info["code"][:6], name_clean)
            header += f"🔧 {full_name}\n"
            header += f"💰 <b>Пошлина:</b> {info['tariff']}"
            if pt.get("type") in ("min", "plus", "fixed_eur"):
                header += f" — комбинированная ({pt['formula']})"
            elif pt.get("type") == "percent":
                header += " — адвалорная"
            header += "\n"
            vat_str = "10% (льготная)" if vat_rate == 0.10 else "22% (базовая)"
            header += f"🧾 <b>НДС:</b> {vat_str}\n"
            if radio_detected:
                _, fee_display = convert_fee_to_currency(RADIO_FEE, base_cur or "RUB", rates or {})
                header += f"⚡ <b>Радиоэлектроника:</b> сбор {fee_display}\n"
            if missing:
                header += f"⚠️ Не найдены: {', '.join(missing)}\n"

        # Fallback если DeepSeek не вывёл платежи
        has_deepseek_calc = any(
            k in answer.lower()
            for k in (
                "итого платежей", "итоговый расчёт", "итоговый расчет", "📊 итоговый",
                "платежи в валюте", "платежи:", "итого:", "итого к оплате",
                "таможенная стоимость:", "таможенных платежей",
            )
        )
        if is_calc and base_cur and not has_deepseek_calc:
            code_val = found_codes[0]["code"] if found_codes else None
            name_val = (
                TNVED_FULL_NAMES.get(found_codes[0]["code"][:6], found_codes[0]["name"])
                if found_codes else None
            )
            fallback = format_calculation_fallback(
                code=code_val,
                name=name_val,
                currency=base_cur,
                rates=rates or {},
                tariff_info=ti,
                is_radio=radio_detected,
                customs_fee_rub=customs_fee_rub,
                vat_rate=vat_rate,
                ts_fallback=ts_fallback,
                ts_components=ts_components,
                weight_kg=comps.get("weight_kg"),
            )
            if fallback:
                answer += "\n\n" + fallback

        if header:
            answer = header + "\n" + answer

    # --- Декларант (только для НЕ-расчётных ответов) ---
    if found_codes and not is_calc and "декларант" not in answer.lower():
        answer += "\n\n📌 <i>Точную информацию уточняйте у декларанта.</i>"

    # --- Курс ЦБ РФ ---
    # Добавляем курс ТОЛЬКО если его ещё нет в ответе
    if "💱" not in answer and "курс цб" not in answer.lower():
        try:
            rates = await get_cbr_rates()
            cny = rates.get("CNY", "н/д")
            usd = rates.get("USD", "н/д")
            eur = rates.get("EUR", "н/д")
            date = rates.get("DATE", "сегодня")
            answer += (
                f"\n\n💱 <i>Курс ЦБ РФ на {date}: "
                f"1 USD = {usd} ₽, 1 CNY = {cny} ₽, 1 EUR = {eur} ₽</i>"
            )
        except Exception:
            pass

    save_message(user_id, message.from_user.username or "", "assistant", answer)
    await safe_send(message, answer)
