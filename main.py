import asyncio
import json
import logging
import os
import uuid
from datetime import date
from pathlib import Path

from aiogram import Bot, Dispatcher, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

TOKEN = os.environ["BOT_TOKEN"]
TIMEZONE = os.environ.get("BOT_TIMEZONE", "Europe/Warsaw")
DAILY_HOUR = int(os.environ.get("DAILY_HOUR", "11"))
DAILY_MINUTE = int(os.environ.get("DAILY_MINUTE", "0"))
DAILY_TITLE = "Гуляешь сегодня?"

STATE_FILE = Path("state.json")

bot = Bot(token=TOKEN)
dp = Dispatcher()

votes: dict[str, dict] = {}
state: dict = {"chat_id": None, "last_message_id": None}


def load_state() -> None:
    global state
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass


def save_state() -> None:
    STATE_FILE.write_text(json.dumps(state))


def keyboard(event_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👍 Да", callback_data=f"vote:{event_id}:yes"),
                InlineKeyboardButton(text="🤷 Возможно", callback_data=f"vote:{event_id}:maybe"),
                InlineKeyboardButton(text="👎 Нет", callback_data=f"vote:{event_id}:no"),
            ],
            [InlineKeyboardButton(text="📊 Результаты", callback_data=f"stats:{event_id}")],
        ]
    )


def new_event(title: str) -> str:
    short_id = uuid.uuid4().hex[:8]
    event_id = f"{short_id}_{date.today()}"
    votes[event_id] = {"title": title, "users": {}}
    return event_id


@dp.message(Command("poll"))
async def cmd_poll(message: types.Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    title = parts[1].strip() if len(parts) > 1 else "Без названия"
    event_id = new_event(title)
    await message.answer(f"📌 {title}", reply_markup=keyboard(event_id))


@dp.message(Command("setdaily"))
async def cmd_setdaily(message: types.Message) -> None:
    state["chat_id"] = message.chat.id
    save_state()
    await message.answer(
        f"✅ Эта группа зарегистрирована для ежедневной голосовалки в "
        f"{DAILY_HOUR:02d}:{DAILY_MINUTE:02d} ({TIMEZONE}).\n\n"
        "Сделай меня админом с правом закреплять сообщения."
    )


@dp.message(Command("stopdaily"))
async def cmd_stopdaily(message: types.Message) -> None:
    if state.get("chat_id") == message.chat.id:
        state["chat_id"] = None
        state["last_message_id"] = None
        save_state()
        await message.answer("⛔ Ежедневная голосовалка отключена.")
    else:
        await message.answer("Эта группа не была зарегистрирована.")


@dp.callback_query()
async def callbacks(callback: types.CallbackQuery) -> None:
    data = callback.data or ""
    parts = data.split(":")

    if len(parts) < 2:
        await callback.answer()
        return

    action = parts[0]
    event_id = parts[1]
    event = votes.get(event_id)

    if event is None:
        await callback.answer("Эта голосовалка больше недоступна.", show_alert=True)
        return

    if action == "vote" and len(parts) == 3 and parts[2] in ("yes", "maybe", "no"):
        event["users"][callback.from_user.id] = {
            "name": callback.from_user.first_name,
            "answer": parts[2],
        }
        await callback.answer("Сохранено ✅")

    elif action == "stats":
        users = event["users"]
        groups: dict[str, list[str]] = {"yes": [], "maybe": [], "no": []}
        for info in users.values():
            groups[info["answer"]].append(info["name"])

        def section(title: str, names: list[str]) -> str:
            if not names:
                return f"{title}\n- никого"
            return title + "\n" + "\n".join(f"- {n}" for n in names)

        text = (
            f"📊 {event['title']}\n\n"
            + section("👍 Идут:", groups["yes"])
            + "\n\n"
            + section("🤷 Думают:", groups["maybe"])
            + "\n\n"
            + section("👎 Не идут:", groups["no"])
        )

        await callback.answer(text, show_alert=True)

    else:
        await callback.answer()


async def send_daily_poll() -> None:
    chat_id = state.get("chat_id")
    if not chat_id:
        logging.info("Daily poll skipped: no chat registered.")
        return

    last_id = state.get("last_message_id")
    if last_id:
        try:
            await bot.unpin_chat_message(chat_id, last_id)
        except TelegramBadRequest as e:
            logging.warning("Failed to unpin previous message: %s", e)

    event_id = new_event(DAILY_TITLE)
    msg = await bot.send_message(
        chat_id, f"📌 {DAILY_TITLE}", reply_markup=keyboard(event_id)
    )

    try:
        await bot.pin_chat_message(chat_id, msg.message_id, disable_notification=True)
    except TelegramBadRequest as e:
        logging.warning("Failed to pin message: %s", e)

    state["last_message_id"] = msg.message_id
    save_state()


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    load_state()

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        send_daily_poll,
        CronTrigger(hour=DAILY_HOUR, minute=DAILY_MINUTE, timezone=TIMEZONE),
    )
    scheduler.start()
    logging.info(
        "Scheduled daily poll at %02d:%02d %s", DAILY_HOUR, DAILY_MINUTE, TIMEZONE
    )

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
