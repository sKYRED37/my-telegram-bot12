import asyncio
import logging

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

import storage

logging.basicConfig(level=logging.INFO)

# ==================== НАСТРОЙКИ ====================
# Токен бота от @BotFather
BOT_TOKEN = "ВСТАВЬ_СЮДА_ТОКЕН"

# Твой личный Telegram id (число, БЕЗ минуса). Узнать у @userinfobot.
# Только этот человек сможет открывать /admin и менять, куда идут заявки
OWNER_ID = 000000000

# Куда слать заявки по умолчанию, ПОКА владелец не настроит это через /admin
DEFAULT_DESTINATION_CHAT_ID = OWNER_ID
# ====================================================

bot = Bot(token=BOT_TOKEN)
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


class SubmitForm(StatesGroup):
    waiting_text = State()


class AdminForm(StatesGroup):
    waiting_group_forward = State()


# ---------- вспомогательные функции ----------

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


def get_destination_chat_id() -> int:
    dest = storage.get_destination()
    if dest:
        return dest["chat_id"]
    return DEFAULT_DESTINATION_CHAT_ID


def get_destination_label() -> str:
    dest = storage.get_destination()
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


# ---------- пользовательский сценарий (предложка) ----------

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


# ---------- админ-панель (только для OWNER_ID) ----------

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

    storage.set_destination(OWNER_ID, "private", "личка владельца")
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

    storage.set_destination(chat.id, "group", chat.title or "группа")
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

    storage.set_destination(message.chat.id, "group", message.chat.title or "группа")
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
            "/setgroup — направить заявки в текущую группу (вызывать в группе)"
        )
    await message.answer(text, parse_mode="HTML")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
