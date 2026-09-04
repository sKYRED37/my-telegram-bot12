import asyncio
import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)

logging.basicConfig(level=logging.INFO)

# ==================== НАСТРОЙКИ ====================
# Токен бота от @BotFather
BOT_TOKEN = "8472101199:AAGlbOQroXPAGbB27LAn2zWEaktXUrUNMV0"
# Твой личный Telegram id (число, БЕЗ минуса). Узнать у @userinfobot.
# Только этот человек сможет открывать /admin и менять, куда идут заявки
OWNER_ID = 1766395031

# Куда слать заявки по умолчанию, ПОКА владелец не настроит это через /admin
DEFAULT_DESTINATION_CHAT_ID = 0
# ====================================================

bot = Bot(token=8472101199:AAGlbOQroXPAGbB27LAn2zWEaktXUrUNMV0)
dp = Dispatcher(storage=MemoryStorage())

BOT_NAME = "Brief NEWS"

# === ТЕМЫ ПРЕДЛОЖКИ ===
TOPICS = {
    "search_players": "🔍 Поиск игроков",
    "roster": "📋 Публикация ростера",
    "search_clan": "🏰 Поиск клана",
    "cooperation": "🤝 Сотрудничество и реклама",
    "other": "💬 Другое",
}


# ==================== ХРАНИЛИЩЕ НАСТРОЕК (JSON) ====================
# Куда слать заявки — группа или личка. Настраивается владельцем через /admin.

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")


def _load_settings() -> dict:
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_settings(data: dict) -> None:
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_destination() -> dict | None:
    """
    Возвращает текущее место назначения заявок:
    {"chat_id": int, "type": "private"|"group", "title": str}
    или None, если ещё не настроено.
    """
    data = _load_settings()
    return data.get("destination")


def set_destination(chat_id: int, dest_type: str, title: str) -> None:
    data = _load_settings()
    data["destination"] = {"chat_id": chat_id, "type": dest_type, "title": title}
    _save_settings(data)


# ==================== БАЗА ДАННЫХ (SQLite) ====================
# Хранит все заявки. Файл submissions.db создаётся автоматически при старте.

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "submissions.db")


@contextmanager
def _db_connect():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Создаёт файл БД и таблицу submissions, если их ещё нет."""
    with _db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                username      TEXT,
                full_name     TEXT,
                topic_key     TEXT NOT NULL,
                topic_title   TEXT NOT NULL,
                text          TEXT NOT NULL,
                destination   TEXT,
                created_at    TEXT NOT NULL
            )
            """
        )


def save_submission(
    user_id: int,
    username: str | None,
    full_name: str,
    topic_key: str,
    topic_title: str,
    text: str,
    destination: str,
) -> int:
    """Сохраняет одну заявку в БД, возвращает её id."""
    with _db_connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO submissions
                (user_id, username, full_name, topic_key, topic_title, text, destination, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                username,
                full_name,
                topic_key,
                topic_title,
                text,
                destination,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        return cursor.lastrowid


def get_recent(limit: int = 10) -> list[sqlite3.Row]:
    """Последние N заявок, самые новые первыми."""
    with _db_connect() as conn:
        rows = conn.execute(
            "SELECT * FROM submissions ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return rows


def get_stats() -> dict:
    """Возвращает {"total": int, "by_topic": {topic_title: count}}."""
    with _db_connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM submissions").fetchone()["c"]
        rows = conn.execute(
            "SELECT topic_title, COUNT(*) AS c FROM submissions GROUP BY topic_title ORDER BY c DESC"
        ).fetchall()
        by_topic = {row["topic_title"]: row["c"] for row in rows}
        return {"total": total, "by_topic": by_topic}


# ==================== СОСТОЯНИЯ (FSM) ====================

class SubmitForm(StatesGroup):
    waiting_text = State()


class AdminForm(StatesGroup):
    waiting_group_forward = State()


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


def get_destination_chat_id() -> int:
    dest = get_destination()
    if dest:
        return dest["chat_id"]
    return DEFAULT_DESTINATION_CHAT_ID


def get_destination_label() -> str:
    dest = get_destination()
    if not dest:
        return "личка владельца (по умолчанию)"
    if dest["type"] == "private":
        return "личка владельца"
    return f"группа «{dest['title']}»"


def topics_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=title, callback_data=f"topic:{key}")]
        for key, title in TOPICS.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data="confirm:send"),
                InlineKeyboardButton(text="❌ Отменить", callback_data="confirm:cancel"),
            ]
        ]
    )


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👤 Слать мне в бота", callback_data="admin:dest_private")],
            [InlineKeyboardButton(text="👥 Слать в группу", callback_data="admin:dest_group")],
        ]
    )


# ==================== ПОЛЬЗОВАТЕЛЬСКИЙ СЦЕНАРИЙ (ПРЕДЛОЖКА) ====================

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"👋 Привет! Это <b>{BOT_NAME}</b>.\n\n"
        f"Выбери тему своего предложения, а после напиши текст запроса.",
        reply_markup=topics_keyboard(),
        parse_mode="HTML",
    )


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Действие отменено. Выбери тему заново:",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer("Темы:", reply_markup=topics_keyboard())


@dp.callback_query(F.data.startswith("topic:"))
async def choose_topic(callback: CallbackQuery, state: FSMContext):
    topic_key = callback.data.split(":", 1)[1]
    topic_title = TOPICS.get(topic_key, "Другое")

    await state.update_data(topic_key=topic_key, topic_title=topic_title)
    await state.set_state(SubmitForm.waiting_text)

    await callback.message.edit_text(
        f"Тема: <b>{topic_title}</b>\n\n"
        f"Теперь напиши текст своего запроса одним сообщением.",
        parse_mode="HTML",
    )
    await callback.message.answer(
        "Можешь отправить текст, фото/видео с подписью или просто текст.\n"
        "Чтобы отменить — нажми кнопку ниже или /cancel.",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@dp.message(SubmitForm.waiting_text, F.text == "❌ Отмена")
async def cancel_via_button(message: Message, state: FSMContext):
    await cmd_cancel(message, state)


@dp.message(SubmitForm.waiting_text)
async def receive_text(message: Message, state: FSMContext):
    data = await state.get_data()
    topic_title = data.get("topic_title", "Другое")

    await state.update_data(
        user_text=message.text or message.caption or "(без текста)",
    )

    preview = (
        f"📝 <b>Предпросмотр заявки</b>\n\n"
        f"Тема: <b>{topic_title}</b>\n"
        f"Текст: {message.text or message.caption or '(без текста)'}\n\n"
        f"Отправить на модерацию?"
    )
    await message.answer(preview, reply_markup=confirm_keyboard(), parse_mode="HTML")


@dp.callback_query(F.data == "confirm:cancel")
async def confirm_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Заявка отменена.")
    await callback.message.answer("Выбери тему заново:", reply_markup=topics_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "confirm:send")
async def confirm_send(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    topic_key = data.get("topic_key", "other")
    topic_title = data.get("topic_title", "Другое")
    user_text = data.get("user_text", "(без текста)")

    user = callback.from_user
    username = f"@{user.username}" if user.username else "нет username"

    admin_text = (
        f"📩 <b>Новая заявка — {BOT_NAME}</b>\n\n"
        f"Тема: <b>{topic_title}</b>\n"
        f"От: {user.full_name} ({username}, id: <code>{user.id}</code>)\n\n"
        f"Текст:\n{user_text}"
    )

    destination_chat_id = get_destination_chat_id()

    # заявка сохраняется в БД независимо от того, удастся ли её доставить
    save_submission(
        user_id=user.id,
        username=user.username,
        full_name=user.full_name,
        topic_key=topic_key,
        topic_title=topic_title,
        text=user_text,
        destination=get_destination_label(),
    )

    try:
        await bot.send_message(destination_chat_id, admin_text, parse_mode="HTML")
        await callback.message.edit_text(
            "✅ Спасибо! Твоя заявка отправлена на модерацию."
        )
    except Exception as e:
        logging.error(f"Не удалось отправить заявку: {e}")
        await callback.message.edit_text(
            "⚠️ Не удалось отправить заявку. Сообщи об этом администратору."
        )

    await state.clear()
    await callback.message.answer(
        "Хочешь отправить ещё одну заявку? Выбери тему:",
        reply_markup=topics_keyboard(),
    )
    await callback.answer()


# ==================== АДМИН-ПАНЕЛЬ (ТОЛЬКО ДЛЯ OWNER_ID) ====================

@dp.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return  # обычные пользователи не должны даже знать, что команда есть

    await state.clear()
    await message.answer(
        f"⚙️ <b>Админ-панель — {BOT_NAME}</b>\n\n"
        f"Сейчас заявки приходят сюда: <b>{get_destination_label()}</b>\n\n"
        f"Выбери, куда слать новые заявки:",
        reply_markup=admin_keyboard(),
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "admin:dest_private")
async def admin_set_private(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback.from_user.id):
        await callback.answer()
        return

    set_destination(OWNER_ID, "private", "личка владельца")
    await state.clear()
    await callback.message.edit_text(
        "✅ Готово! Теперь все заявки будут приходить тебе в личку боту."
    )
    await callback.answer()


@dp.callback_query(F.data == "admin:dest_group")
async def admin_set_group(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback.from_user.id):
        await callback.answer()
        return

    await state.set_state(AdminForm.waiting_group_forward)
    await callback.message.edit_text(
        "👥 Чтобы направить заявки в группу, есть два способа:\n\n"
        "<b>Способ 1 (проще всего)</b>\n"
        "1. Добавь этого бота в нужную группу и сделай его администратором\n"
        "2. Напиши в этой группе команду /setgroup\n\n"
        "<b>Способ 2</b>\n"
        "Перешли мне сюда (в личку) любое сообщение из той группы — "
        "я определю её по пересланному сообщению.\n\n"
        "Для отмены — /cancel",
        parse_mode="HTML",
    )
    await callback.answer()


@dp.message(AdminForm.waiting_group_forward, F.forward_from_chat)
async def admin_receive_group_forward(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return

    chat = message.forward_from_chat
    if chat.type not in ("group", "supergroup"):
        await message.answer(
            "⚠️ Это сообщение не из группы. Перешли сообщение именно из той "
            "группы, куда должны приходить заявки, либо используй /setgroup "
            "прямо в группе."
        )
        return

    set_destination(chat.id, "group", chat.title or "группа")
    await state.clear()
    await message.answer(
        f"✅ Готово! Теперь заявки будут приходить в группу «{chat.title}».\n"
        f"Убедись, что бот состоит в этой группе и может там писать."
    )


@dp.message(Command("setgroup"))
async def cmd_setgroup(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        return

    if message.chat.type not in ("group", "supergroup"):
        await message.answer(
            "Эту команду нужно вызывать прямо в группе, куда должны "
            "приходить заявки."
        )
        return

    set_destination(message.chat.id, "group", message.chat.title or "группа")
    await state.clear()
    await message.answer(
        f"✅ Готово! Заявки теперь будут приходить в эту группу «{message.chat.title}»."
    )

    try:
        await bot.send_message(
            OWNER_ID,
            f"✅ Заявки теперь направляются в группу «{message.chat.title}».",
        )
    except Exception:
        pass  # если владелец не писал боту в личку — просто пропускаем


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if not is_owner(message.from_user.id):
        return

    stats = get_stats()
    if stats["total"] == 0:
        await message.answer("Заявок пока нет.")
        return

    lines = [f"📊 <b>Статистика — {BOT_NAME}</b>", "", f"Всего заявок: <b>{stats['total']}</b>", ""]
    for topic_title, count in stats["by_topic"].items():
        lines.append(f"{topic_title}: {count}")

    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("last"))
async def cmd_last(message: Message):
    if not is_owner(message.from_user.id):
        return

    rows = get_recent(limit=10)
    if not rows:
        await message.answer("Заявок пока нет.")
        return

    lines = [f"🗂 <b>Последние заявки</b> (макс. 10)", ""]
    for row in rows:
        username = f"@{row['username']}" if row["username"] else "нет username"
        text_preview = row["text"] if len(row["text"]) <= 80 else row["text"][:77] + "…"
        lines.append(
            f"#{row['id']} · {row['created_at']}\n"
            f"{row['topic_title']} · {row['full_name']} ({username})\n"
            f"{text_preview}\n"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        f"<b>{BOT_NAME}</b> — бот-предложка.\n\n"
        f"/start — выбрать тему и оставить заявку\n"
        f"/cancel — отменить текущее действие"
    )
    if is_owner(message.from_user.id):
        text += (
            "\n\n<b>Для владельца:</b>\n"
            "/admin — куда отправлять заявки (лично / группа)\n"
            "/setgroup — направить заявки в текущую группу (вызывать в группе)\n"
            "/stats — статистика заявок по темам\n"
            "/last — последние 10 заявок из базы данных"
        )
    await message.answer(text, parse_mode="HTML")


async def main():
    init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
