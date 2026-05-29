"""
services/scheduler.py — планировщик задач West Asia Bot.

Задачи:
1. Утренняя рассылка в 9:15 МСК (рабочие дни) — просроченные и срок < 24ч
2. Напоминания о задачах по сроку (за 30 мин для долгосрочных, точно в срок для коротких)
"""
import asyncio
from datetime import datetime, timedelta, timezone
import pytz

from config import logger
from services.amocrm import TG_TO_AMO, get_overdue_tasks, _async_request
from database import save_reminder, delete_reminder, load_pending_reminders

MSK = pytz.timezone("Europe/Moscow")

# Храним запланированные напоминания: task_id → asyncio.Task
_scheduled: dict = {}


# ─── Утренняя рассылка ────────────────────────────────────────────────────────

async def _morning_digest(bot):
    """Отправляет утреннюю сводку каждому менеджеру из AMO_USERS."""
    logger.info("Scheduler: утренняя рассылка запущена")

    for tg_id, amo_id in TG_TO_AMO.items():
        try:
            tasks = await get_overdue_tasks(responsible_user_id=amo_id)

            # Задачи со сроком < 24 часов (не просроченные)
            now = datetime.now(MSK)
            tomorrow = now + timedelta(hours=24)

            # Получаем незакрытые задачи со сроком до завтра
            resp = await _async_request("GET", "/tasks", params={
                "filter[is_completed]": 0,
                "filter[responsible_user_id][]": amo_id,
                "filter[complete_till][from]": int(now.timestamp()),
                "filter[complete_till][to]": int(tomorrow.timestamp()),
                "limit": 20,
            })
            upcoming = resp.get("_embedded", {}).get("tasks", [])

            if not tasks and not upcoming:
                continue  # Нет задач — не беспокоим

            text = f"☀️ <b>Доброе утро! Сводка на {now.strftime('%d.%m.%Y')}</b>\n\n"

            if tasks:
                text += f"🔴 <b>Просроченные задачи: {len(tasks)}</b>\n"
                for t in tasks[:7]:
                    lead = f" — {t['lead_name']}" if t.get('lead_name') else ""
                    text += f"  • {t['text'][:60]}{lead}\n    📅 Срок был: {t['due']}\n"
                text += "\n"

            if upcoming:
                # Загружаем названия сделок
                lead_cache = {}
                for t in upcoming:
                    eid = t.get("entity_id")
                    if eid and t.get("entity_type") == "leads" and eid not in lead_cache:
                        lr = await _async_request("GET", f"/leads/{eid}")
                        lead_cache[eid] = lr.get("name", "")

                # Фильтруем пустые задачи
                upcoming_clean = [t for t in upcoming if t.get("text", "").strip()]
                # Сортируем: сначала с конкретным временем (не 23:59), потом остальные
                def _has_specific_time(t):
                    due_ts = t.get("complete_till", 0)
                    if not due_ts:
                        return False
                    dt = datetime.fromtimestamp(due_ts, tz=MSK)
                    # AmoCRM "Весь день" = полночь UTC = 02:59-03:01 МСК
                    # Конкретное время = всё остальное
                    if dt.hour == 23 and dt.minute == 59:
                        return False
                    if dt.hour == 2 and dt.minute == 59:
                        return False
                    if dt.hour == 3 and dt.minute == 0:
                        return False
                    return True
                upcoming_clean = sorted(upcoming_clean, key=lambda t: (0 if _has_specific_time(t) else 1, t.get("complete_till", 0) if _has_specific_time(t) else 9999999999))
                text += f"🟡 <b>Срок сегодня/завтра: {len(upcoming_clean)}</b>\n"
                for t in upcoming_clean[:20]:
                    task_text = t.get("text", "—").strip()[:100]
                    eid = t.get("entity_id")
                    lead_name = lead_cache.get(eid, "")[:50] if eid else ""
                    due_ts = t.get("complete_till", 0)
                    due_dt = datetime.fromtimestamp(due_ts, tz=MSK) if due_ts else None
                    # Показываем время только если конкретное (не 23:59)
                    if due_dt and (due_dt.hour != 23 or due_dt.minute != 59):
                        due_str = f"🕐 {due_dt.strftime('%d.%m %H:%M')}"
                    else:
                        due_str = ""
                    time_line = f"\n    {due_str}" if due_str else ""
                    if lead_name:
                        text += f"\n  📋 <b>{lead_name}</b>\n    {task_text}{time_line}\n"
                    else:
                        text += f"\n  • {task_text}{time_line}\n"

            await bot.send_message(tg_id, text, parse_mode="HTML")
            logger.info(f"Scheduler: рассылка отправлена → {tg_id}")

        except Exception as e:
            logger.error(f"Scheduler: ошибка рассылки для {tg_id}: {e}")


async def _morning_loop(bot):
    """Ждёт 9:15 МСК в рабочие дни и запускает рассылку."""
    while True:
        try:
            now = datetime.now(MSK)
            # Следующий запуск: сегодня в 9:15 или завтра
            target = now.replace(hour=9, minute=15, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)

            # Пропускаем выходные (5=суббота, 6=воскресенье)
            while target.weekday() >= 5:
                target += timedelta(days=1)

            delay = (target - now).total_seconds()
            logger.info(f"Scheduler: следующая рассылка в {target.strftime('%d.%m.%Y %H:%M МСК')} (через {delay/3600:.1f}ч)")
            await asyncio.sleep(delay)
            await _morning_digest(bot)

        except Exception as e:
            logger.error(f"Scheduler morning loop error: {e}")
            await asyncio.sleep(60)


# ─── Напоминания о задачах ────────────────────────────────────────────────────

async def _send_reminder(bot, chat_id: int, task_id: int, task_text: str, deal_name: str):
    """Отправляет напоминание с кнопками Выполнено / +1 день / +3 дня."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    deal_str = f"\n🔗 {deal_name}" if deal_name else ""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Выполнено", callback_data=f"task_done:{task_id}"),
        InlineKeyboardButton(text="📅 +1 день", callback_data=f"task_postpone:{task_id}:1"),
        InlineKeyboardButton(text="📅 +3 дня", callback_data=f"task_postpone:{task_id}:3"),
    ]])
    try:
        await bot.send_message(
            chat_id,
            f"⏰ <b>Напоминание о задаче!</b>\n\n📝 {task_text}{deal_str}",
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.error(f"Scheduler: ошибка напоминания {task_id}: {e}")
    finally:
        _scheduled.pop(task_id, None)
        delete_reminder(task_id)


def schedule_reminder(
    bot,
    chat_id: int,
    task_id: int,
    task_text: str,
    deal_name: str,
    due_dt: datetime,
    explicit_time: bool = False,
):
    """
    Планирует напоминание.
    explicit_time=True  → напомнить точно в срок (пользователь назвал конкретное время/«через N минут»)
    explicit_time=False → напомнить за 30 минут до срока (долгосрочная задача)
    """
    # Отменяем предыдущее напоминание по той же задаче если есть
    if task_id in _scheduled:
        _scheduled[task_id].cancel()

    now = datetime.now()

    if explicit_time:
        remind_at = due_dt
    else:
        remind_at = due_dt - timedelta(minutes=30)

    delay = (remind_at - now).total_seconds()
    if delay <= 0:
        return  # Уже прошло — не ставим

    async def _run():
        await asyncio.sleep(delay)
        await _send_reminder(bot, chat_id, task_id, task_text, deal_name)

    task = asyncio.create_task(_run())
    _scheduled[task_id] = task

    # Сохраняем в БД для восстановления после перезапуска
    save_reminder(
        task_id=task_id,
        chat_id=chat_id,
        task_text=task_text,
        deal_name=deal_name,
        due_ts=int(due_dt.timestamp()),
        explicit_time=explicit_time,
    )

    mode = "точно в срок" if explicit_time else "за 30 мин"
    logger.info(f"Scheduler: напоминание task_id={task_id} запланировано {mode}, через {delay/60:.1f} мин")


# ─── Обработка кнопок (done / postpone) ──────────────────────────────────────

async def handle_task_callback(callback, bot):
    """Обрабатывает нажатия кнопок напоминания."""
    from services.amocrm import _async_request
    data = callback.data  # task_done:ID или task_postpone:ID:DAYS

    try:
        if data.startswith("task_done:"):
            task_id = int(data.split(":")[1])
            await _async_request("PATCH", f"/tasks/{task_id}", data={"is_completed": True})
            await callback.message.edit_text(
                callback.message.text + "\n\n✅ <b>Задача выполнена!</b>",
                parse_mode="HTML",
                reply_markup=None,
            )
            await callback.answer("Задача закрыта ✅")

        elif data.startswith("task_postpone:"):
            parts = data.split(":")
            task_id = int(parts[1])
            days = int(parts[2])
            # Получаем текущий срок задачи
            resp = await _async_request("GET", f"/tasks/{task_id}")
            current_till = resp.get("complete_till", 0)
            new_till = current_till + days * 86400
            await _async_request("PATCH", f"/tasks/{task_id}", data={"complete_till": new_till})
            new_dt_obj = datetime.fromtimestamp(new_till)
            new_dt_str = new_dt_obj.strftime("%d.%m.%Y %H:%M")
            await callback.message.edit_text(
                callback.message.text + f"\n\n📅 <b>Перенесено на {new_dt_str}</b>",
                parse_mode="HTML",
                reply_markup=None,
            )
            await callback.answer(f"Перенесено на {days} дн. ✅")
            # Планируем новое напоминание за 30 минут до нового срока
            task_text = resp.get("text", "Задача")
            schedule_reminder(
                bot=bot,
                chat_id=callback.message.chat.id,
                task_id=task_id,
                task_text=task_text,
                deal_name="",
                due_dt=new_dt_obj,
                explicit_time=False,
            )

    except Exception as e:
        logger.error(f"Scheduler callback error: {e}")
        await callback.answer("Ошибка, попробуй ещё раз")


async def restore_reminders(bot):
    """Восстанавливает напоминания из БД после перезапуска."""
    from datetime import datetime
    pending = load_pending_reminders()
    if not pending:
        return
    logger.info(f"Scheduler: восстанавливаем {len(pending)} напоминаний из БД")
    for r in pending:
        due_dt = datetime.fromtimestamp(r["due_ts"])
        schedule_reminder(
            bot=bot,
            chat_id=r["chat_id"],
            task_id=r["task_id"],
            task_text=r["task_text"],
            deal_name=r["deal_name"],
            due_dt=due_dt,
            explicit_time=r["explicit_time"],
        )


def start_scheduler(bot):
    """Запускает утренний цикл рассылки и восстанавливает напоминания."""
    asyncio.create_task(_morning_loop(bot))
    asyncio.create_task(restore_reminders(bot))
    logger.info("Scheduler запущен")
