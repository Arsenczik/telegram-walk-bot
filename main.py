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
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove


TOKEN = os.environ["BOT_TOKEN"]
TIMEZONE = os.environ.get("BOT_TIMEZONE", "Europe/Warsaw")

DAILY_HOUR = int(os.environ.get("DAILY_HOUR", "10"))
DAILY_MINUTE = int(os.environ.get("DAILY_MINUTE", "0"))

DAILY_TITLE = "Гуляешь сегодня?"

STATE_FILE = Path("state.json")

bot = Bot(token=TOKEN)
dp = Dispatcher()

votes: dict[str, dict] = {}
state: dict = {"chat_id": None}

user_waiting_for_poll = {}


# ---------------- STATE ----------------

def load_state() -> None:
    global state
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass


def save_state() -> None:
    STATE_FILE.write_text(json.dumps(state))


# ---------------- KEYBOARD ----------------

def keyboard(event_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да👍", callback_data=f"vote:{event_id}:yes"),
                InlineKeyboardButton(text="Может🤷", callback_data=f"vote:{event_id}:maybe"),
                InlineKeyboardButton(text="Нет👎", callback_data=f"vote:{event_id}:no"),
            ],
            [
                InlineKeyboardButton(text="Кто будет📊", callback_data=f"stats:{event_id}")
            ],
        ]
    )
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Центр"), KeyboardButton(text="📍 Бестик")],
            [KeyboardButton(text="✏️ Свой вариант")],
        ],
        resize_keyboard=True
    )

# ---------------- EVENTS ----------------

def new_event(title: str) -> str:
    event_id = uuid.uuid4().hex[:8]
    votes[event_id] = {"title": title, "users": {}}
    return event_id


# ---------------- COMMANDS ----------------

@dp.message(Command("poll"))
async def cmd_poll(message: types.Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    title = parts[1].strip() if len(parts) > 1 else "Без названия"

    event_id = new_event(title)

    await message.answer(
        f"📌 {title}",
        reply_markup=keyboard(event_id)
    )

@dp.message(Command("menu"))
async def cmd_menu(message: types.Message):
    user_id = message.from_user.id

    # удалить команду /menu
    try:
        await message.delete()
    except:
        pass

    # отправить меню
    msg = await message.answer(
        "🟣 <b>Создание голосовалки</b>",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )

    # сохранить сообщение меню
    user_waiting_for_poll[user_id] = {
        "chat_id": message.chat.id,
        "menu_msg_id": msg.message_id
    }

@dp.message(Command("setdaily"))
async def cmd_setdaily(message: types.Message) -> None:
    await message.delete()
    
    state["chat_id"] = message.chat.id
    save_state()
    
    await message.answer(
        "🚀 <b>Панель голосовалок</b>\n\n"
        "🟣 Создание голосовалки\n"
        "Выбери действие 👇",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )



@dp.message(lambda message: message.text is not None)
async def handle_menu(message: types.Message):
    text = (message.text or "").strip()
    user_id = message.from_user.id

    data = user_waiting_for_poll.get(user_id)

    # 1. режим "свой вариант" — пользователь вводит название
    if data and data.get("mode") == "custom":
        if data.get("menu_msg_id"):
            try:
                await message.delete()
            except Exception as e:
                logging.warning(f"Не удалось удалить сообщение юзера: {e}")

        try:
            await message.delete()
        except:
            pass

        # удаляем сообщение бота "Напиши название голосовалки 👇"
        if data.get("prompt_msg_id"):
            try:
                await bot.delete_message(message.chat.id, data["prompt_msg_id"])
            except:
                pass

        title = text
        event_id = new_event(title)

        await message.answer(f"📌 {title}", reply_markup=keyboard(event_id))
        await message.answer(" ", reply_markup=ReplyKeyboardRemove())

        user_waiting_for_poll.pop(user_id, None)
        return

        # 2. кнопка "Свой вариант"
    if text == "✏️ Свой вариант":
        prompt = await message.answer("Напиши название голосовалки 👇")
        if data:
            data["mode"] = "custom"
            data["prompt_msg_id"] = prompt.message_id
        else:
            user_waiting_for_poll[user_id] = {
                "chat_id": message.chat.id,
                "mode": "custom",
                "prompt_msg_id": prompt.message_id
            }
        return

    # 3. кнопка "Центр"
    if text == "📍 Центр":
        try:
            await message.delete()
        except:
            pass
        title = "Кто будет в центре?"
        event_id = new_event(title)
        await message.answer(f"📌 {title}", reply_markup=keyboard(event_id))
        if data and data.get("menu_msg_id"):
            try:
                await bot.delete_message(message.chat.id, data["menu_msg_id"])
            except:
                pass
        user_waiting_for_poll.pop(user_id, None)
        return

    # 4. кнопка "Бестик"
    if text == "📍 Бестик":
        try:
            await message.delete()
        except:
            pass
        title = "Кто будет на бестике?"
        event_id = new_event(title)
        await message.answer(f"📌 {title}", reply_markup=keyboard(event_id))
        if data and data.get("menu_msg_id"):
            try:
                await bot.delete_message(message.chat.id, data["menu_msg_id"])
            except:
                pass
        user_waiting_for_poll.pop(user_id, None)
        return


# ---------------- CALLBACKS ----------------

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
    if not event:
        await callback.message.answer("Устарело")
        await callback.answer()
        return

    if action == "vote":
        event["users"][callback.from_user.id] = {
            "name": callback.from_user.first_name,
            "answer": parts[2],
        }
        await callback.answer("Сохранено")

    elif action == "stats":
        groups = {"yes": [], "maybe": [], "no": []}

        for u in event["users"].values():
            groups[u["answer"]].append(u["name"])

        def fmt(title, arr):
            return title + "\n" + ("\n".join(arr) if arr else "- никого")

        text = (
            f"📊 {event['title']}\n\n"
            f"{fmt('👍 Да', groups['yes'])}\n\n"
            f"{fmt('🤷 Возможно', groups['maybe'])}\n\n"
            f"{fmt('👎 Нет', groups['no'])}"
        )

        await callback.answer(text, show_alert=True)


# ---------------- DAILY JOB ----------------

async def send_daily_poll():
    chat_id = state.get("chat_id")

    if not chat_id:
        logging.info("Нет группы")
        return

    event_id = new_event(DAILY_TITLE)

    try:
        msg = await bot.send_message(
            chat_id,
            f"📌 {DAILY_TITLE}",
            reply_markup=keyboard(event_id)
        )

        await bot.pin_chat_message(chat_id, msg.message_id)

    except Exception as e:
        logging.warning(f"Ошибка: {e}")

# ---------------- MAIN ----------------

async def main():
    logging.basicConfig(level=logging.INFO)
    load_state()

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    scheduler.add_job(
        send_daily_poll,
        CronTrigger(hour=DAILY_HOUR, minute=DAILY_MINUTE, timezone=TIMEZONE),
    )

    scheduler.start()

    from aiogram.types import BotCommand

    await bot.set_my_commands([
        BotCommand(command="menu", description="открыть меню"),
    ])

    logging.info(f"Bot started. Daily at {DAILY_HOUR}:{DAILY_MINUTE}")

    # 👇 ОБЯЗАТЕЛЬНО ВНУТРИ функции
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
