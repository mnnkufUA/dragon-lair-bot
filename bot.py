import asyncio
import html
import json
import logging
import random

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, BotCommand

from config import BOT_TOKEN, WEBAPP_URL, TG_APP_URL
from database import (
    get_or_create_user, update_user, reset_user,
    try_spend_egg, add_food,
)
from handlers.bomb_handlers import router as bomb_router
from handlers.hunt_handlers import router as hunt_router
from handlers.cities_handlers import router as cities_router

logger = logging.getLogger(__name__)

dp = Dispatcher()
dp.include_router(bomb_router)
dp.include_router(hunt_router)
dp.include_router(cities_router)

HTML = "HTML"

# Блокировка на пользователя: не даёт крутить рулетку двумя кликами одновременно
_user_locks: dict[int, asyncio.Lock] = {}


def _lock_for(uid: int) -> asyncio.Lock:
    return _user_locks.setdefault(uid, asyncio.Lock())


def _who(message: types.Message, from_user: types.User | None = None):
    """Возвращает (id, username, имя) НАСТОЯЩЕГО пользователя.

    Важно: когда нажимают инлайн-кнопку, query.message — это сообщение БОТА,
    поэтому message.from_user там = бот. Для кнопок передаём query.from_user отдельно.
    """
    u = from_user or message.from_user
    if u:
        return u.id, (u.username or ""), (u.first_name or "Володар")
    return message.chat.id, "", "Володар"


def _is_group(message: types.Message) -> bool:
    return message.chat.type in ("group", "supergroup")


def get_main_keyboard(is_group: bool = False):
    # В группах Telegram запрещает web_app-кнопки, поэтому там обычная ссылка
    if is_group:
        lair_btn = InlineKeyboardButton(text="🐉 Увійти в Лігво", url=TG_APP_URL)
    else:
        lair_btn = InlineKeyboardButton(text="🐉 Увійти в Лігво", web_app=WebAppInfo(url=WEBAPP_URL))

    return InlineKeyboardMarkup(inline_keyboard=[
        [lair_btn],
        [
            InlineKeyboardButton(text="🎰 Крутити !рулетка", callback_data="play_roulette"),
            InlineKeyboardButton(text="👤 Мій Профіль", callback_data="show_profile")
        ]
    ])


def is_text_trigger(text: str, triggers: list) -> bool:
    if not text:
        return False
    clean = text.lower().strip()
    clean = clean.split('@')[0].strip()
    no_punct = clean.lstrip('!/').strip()
    compact = clean.replace(' ', '')
    for trig in triggers:
        t_clean = trig.lower().lstrip('!/').strip()
        t_compact = trig.lower().replace(' ', '')
        if clean == trig.lower() or no_punct == t_clean or compact == t_compact:
            return True
    return False


async def _report_error(message: types.Message, name: str):
    logger.exception("%s error", name)
    try:
        await message.answer("⚠️ Щось пішло не так. Спробуйте ще раз трохи пізніше.")
    except Exception:
        pass


async def setup_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Головне меню та інвентар"),
        BotCommand(command="lair", description="Відкрити Лігво Дракона"),
        BotCommand(command="startdragon", description="Увійти в Лігво"),
        BotCommand(command="profile", description="Профіль та рівні драконів"),
        BotCommand(command="profildragon", description="Особистий профіль"),
        BotCommand(command="roulette", description="🎰 Рулетка драконячих яєць"),
        BotCommand(command="bomb", description="💣 Гра «Бомба» (слова та склади)"),
        BotCommand(command="movie", description="🎬 Гра «Вгадай фільм / гру»"),
        BotCommand(command="cities", description="🏛️ Гра «Міста Дракона»"),
        BotCommand(command="stop_bomb", description="🛑 Зупинити раунд Бомби"),
        BotCommand(command="stop_cities", description="🛑 Зупинити гру в Міста"),
    ]
    try:
        await bot.set_my_commands(commands)
    except Exception as e:
        logger.warning("Could not set bot commands: %s", e)


START_COMMANDS = ["start", "startdragon", "dragonstart", "start_dragon"]


@dp.message(Command(*START_COMMANDS))
async def cmd_start(message: types.Message, from_user: types.User | None = None):
    try:
        uid, uname, fname = _who(message, from_user)

        user = await get_or_create_user(uid, uname, fname)
        unlocked = json.loads(user['unlocked_elements']) if user.get('unlocked_elements') else []

        status_dragon = "🔒 Ще немає (Лігво спить)"
        if unlocked:
            elem_names = {
                'fire': "🔥 Вогняний дракон",
                'storm': "⚡ Штормовий дракон",
                'frost': "❄️ Крижаний дракон",
                'jade': "🎋 Нефритовий дракон"
            }
            names = json.loads(user['dragon_names']) if user.get('dragon_names') else {}
            active = user.get('active_element') or unlocked[0]
            custom_name = names.get(active, "Дракон")
            status_dragon = f"{elem_names.get(active, '🐉')} <b>«{html.escape(str(custom_name))}»</b>"

        welcome_text = (
            f"🏰 Вітаємо у <b>«Лігві Дракона»</b>, {html.escape(fname)}!\n\n"
            f"✨ Це магічний світ, де ви зрощуєте та тренуєте живих 3D-драконів!\n\n"
            f"👛 <b>Ваш інвентар:</b>\n"
            f"🪙 Монети: <b>{user['coins']}</b>\n"
            f"💧 Сльози дракона: <b>{user['tears']}</b>\n"
            f"🍖 Смаколики (їжа): <b>{user['food']}</b>\n"
            f"🥚 Драконячі яйця: <b>{user['eggs']}</b>\n\n"
            f"🐉 <b>Ваш дракон:</b> {status_dragon}\n\n"
        )

        if not unlocked:
            welcome_text += (
                "🥚 <b>Ваше Лігво ще порожнє!</b>\n"
                "У вас ще немає жодного дракона. Відкрийте або знайдіть свого першого дракона, щоб увійти до лігва!\n\n"
            )
        else:
            welcome_text += "🎮 Натискайте <b>🐉 Увійти в Лігво</b>, щоб тренувати та милуватися своїм драконом!\n\n"

        welcome_text += (
            "🎮 <b>Швидкі команди:</b>\n"
            "• <code>/bomb</code> або <code>!бомба</code> — Гра «Бомба» (слова, склади, монети, їжа та яйця!)\n"
            "• <code>/movie</code> або <code>!фільм</code> — Гра «Вгадай фільм / гру» (постери та дешифровка)\n"
            "• <code>/cities</code> або <code>!міста</code> — Гра «Міста Дракона» (географічна битва)\n"
            "• <code>/roulette</code> або <code>!рулетка</code> — Крутити рулетку яєць\n"
            "• <code>/lair</code> або <code>!моєлігво</code> — Відкрити 3D Лігво Дракона\n"
            "• <code>/profile</code> — Особистий профіль володаря драконів"
        )

        await message.answer(welcome_text, parse_mode=HTML, reply_markup=get_main_keyboard(is_group=_is_group(message)))
    except Exception:
        await _report_error(message, "cmd_start")


LAIR_COMMANDS = ["lair", "dragon", "дракон", "лігво", "моєлігво"]
LAIR_TRIGGERS = ["!моєлігво", "!моє лігво", "моєлігво", "моє лігво", "!лігво", "лігво", "!lair", "lair"]


@dp.message(Command(*LAIR_COMMANDS))
@dp.message(F.text.func(lambda text: is_text_trigger(text, LAIR_TRIGGERS)))
async def cmd_lair(message: types.Message, from_user: types.User | None = None):
    try:
        uid, uname, fname = _who(message, from_user)

        user = await get_or_create_user(uid, uname, fname)
        unlocked = json.loads(user['unlocked_elements']) if user.get('unlocked_elements') else []
        is_group = _is_group(message)

        if not unlocked:
            await message.answer(
                "🏰 <b>Ваше Лігво ще спить і порожнє!</b> 🥚\n\n"
                "У вас ще немає жодного дракона чи магічного яйця.\n"
                "Зіграйте в <code>/bomb</code> або <code>/movie</code>, вибийте яйце та запустіть <code>/roulette</code>!",
                parse_mode=HTML,
                reply_markup=get_main_keyboard(is_group=is_group)
            )
            return

        if is_group:
            open_btn = InlineKeyboardButton(text="🐉 Відкрити Лігво Дракона", url=TG_APP_URL)
        else:
            open_btn = InlineKeyboardButton(text="🐉 Відкрити Лігво Дракона", web_app=WebAppInfo(url=WEBAPP_URL))

        await message.answer(
            "🏰 <b>Вхід до вашого гнізда драконів:</b>\nНатисніть кнопку нижче, щоб відкрити світ драконів:",
            parse_mode=HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[open_btn]])
        )
    except Exception:
        await _report_error(message, "cmd_lair")


ROULETTE_COMMANDS = ["roulette", "roulettedragon", "рулетка"]
ROULETTE_TRIGGERS = ["!рулетка", "рулетка", "!рулеька", "рулеька", "!roulette", "roulette"]

NO_EGGS_TEXT = (
    "❌ <b>У вас немає яєць для рулетки!</b> (Потрібно 1 🥚)\n\n"
    "💡 <b>Як отримати яйце:</b>\n"
    "• Грайте в <code>/bomb</code> або <code>/movie</code> (10% шанс вибити драконяче яйце)!\n"
    "• Отримуйте нагороди за активність у чаті."
)


@dp.message(Command(*ROULETTE_COMMANDS))
@dp.message(F.text.func(lambda text: is_text_trigger(text, ROULETTE_TRIGGERS)))
async def cmd_roulette(message: types.Message, from_user: types.User | None = None):
    try:
        uid, uname, fname = _who(message, from_user)
        is_group = _is_group(message)

        async with _lock_for(uid):
            user = await get_or_create_user(uid, uname, fname)

            # Яйце списывается атомарно: если его нет — списание не пройдёт
            if user['eggs'] < 1 or not await try_spend_egg(uid):
                await message.answer(NO_EGGS_TEXT, parse_mode=HTML, reply_markup=get_main_keyboard(is_group=is_group))
                return

            elements = ['fire', 'storm', 'frost', 'jade']
            elem_names = {
                'fire': "🔥 Вогняного Дракона (Typhoomerang)",
                'storm': "⚡ Штормового Дракона (Flightmare)",
                'frost': "❄️ Крижаного Дракона (Dreamdragon)",
                'jade': "🎋 Нефритового Дракона (Singetail)"
            }

            won_elem = random.choice(elements)
            unlocked = json.loads(user['unlocked_elements']) if user.get('unlocked_elements') else []
            levels = json.loads(user['dragon_levels']) if user.get('dragon_levels') else {}

            if won_elem in unlocked:
                await add_food(uid, 5)
                text = (
                    f"🎰 <b>Рулетка прокручена!</b> (-1 🥚)\n\n"
                    f"✨ Випала стихія: <b>{elem_names[won_elem]}</b>!\n"
                    f"ℹ️ У вас вже є цей дракон. Компенсація: <b>+5 🍖 смаколиків</b>!"
                )
            else:
                unlocked.append(won_elem)
                levels.setdefault(won_elem, 1)
                fields = {"unlocked_elements": unlocked, "dragon_levels": levels}
                if not user.get('active_element'):
                    fields["active_element"] = won_elem
                await update_user(uid, **fields)
                text = (
                    f"🎰 <b>РУЛЕТКА ПРОКРУЧЕНА!</b> (-1 🥚)\n\n"
                    f"🎉 <b>НЕЙМОВІРНО! ВИ ВІДКРИЛИ НОВОГО ДРАКОНА!</b>\n"
                    f"🐉 Стихія: <b>{elem_names[won_elem]}</b>\n\n"
                    f"Тепер він доступний у вашому лігві! Перейдіть у меню та познайомтеся зі своїм новим улюбленцем."
                )

        await message.answer(text, parse_mode=HTML, reply_markup=get_main_keyboard(is_group=is_group))
    except Exception:
        await _report_error(message, "cmd_roulette")


PROFILE_COMMANDS = ["profile", "profildragon", "profiledragon", "dragonprofile", "профіль", "профиль"]
PROFILE_TRIGGERS = ["!профіль", "профіль", "!профиль", "профиль", "!profildragon", "!profile", "profildragon", "profile"]


@dp.message(Command(*PROFILE_COMMANDS))
@dp.message(F.text.func(lambda text: is_text_trigger(text, PROFILE_TRIGGERS)))
async def cmd_profile(message: types.Message, from_user: types.User | None = None):
    try:
        uid, uname, fname = _who(message, from_user)

        user = await get_or_create_user(uid, uname, fname)
        unlocked = json.loads(user['unlocked_elements']) if user.get('unlocked_elements') else []
        names = json.loads(user['dragon_names']) if user.get('dragon_names') else {}
        levels = json.loads(user['dragon_levels']) if user.get('dragon_levels') else {}

        elem_icons = {'fire': '🔥', 'storm': '⚡', 'frost': '❄️', 'jade': '🎋'}
        active = user.get('active_element') or ''

        if active and active in unlocked:
            active_name = html.escape(str(names.get(active, "Дракон")))
            active_lvl = levels.get(active, 1)
            active_str = f"{elem_icons.get(active, '🐉')} <b>«{active_name}»</b> (Lv {active_lvl})"
        else:
            active_str = "🔒 Ще немає (Лігво спить)"

        dragons_detail = ""
        if unlocked:
            dragons_detail = "\n🐉 <b>Рівні ваших драконів:</b>\n"
            for el in unlocked:
                el_icon = elem_icons.get(el, '🐉')
                el_name = html.escape(str(names.get(el, el.capitalize())))
                el_lvl = levels.get(el, 1)
                marker = " <i>(активний)</i>" if el == active else ""
                dragons_detail += f"• {el_icon} {el_name}: <b>Рівень {el_lvl}</b>{marker}\n"

        text = (
            f"👤 <b>Профіль володаря драконів ({html.escape(fname)}):</b>\n\n"
            f"🪙 Монети: <b>{user['coins']}</b>\n"
            f"💧 Сльози дракона: <b>{user['tears']}</b>\n"
            f"🍖 Смаколики: <b>{user['food']} шт</b>\n"
            f"🥚 Драконячі яйця: <b>{user['eggs']} шт</b>\n\n"
            f"🐉 <b>Активний дракон:</b> {active_str}\n"
            f"🔓 Відкрито стихій: <b>{len(unlocked)} / 4</b>\n"
            f"{dragons_detail}"
        )
        await message.answer(text, parse_mode=HTML, reply_markup=get_main_keyboard(is_group=_is_group(message)))
    except Exception:
        await _report_error(message, "cmd_profile")


@dp.message(Command("reset"))
async def cmd_reset(message: types.Message):
    """Сброс теперь с подтверждением, чтобы случайно не стереть весь прогресс."""
    try:
        uid, _, _ = _who(message)
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Так, скинути все", callback_data=f"reset_yes:{uid}"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data=f"reset_no:{uid}"),
        ]])
        await message.answer(
            "⚠️ <b>Скинути профіль повністю?</b>\n"
            "Монети, яйця, їжа та всі дракони будуть видалені. Це не можна скасувати!",
            parse_mode=HTML,
            reply_markup=kb,
        )
    except Exception:
        await _report_error(message, "cmd_reset")


@dp.callback_query(F.data.startswith("reset_yes:"))
async def cb_reset_yes(query: types.CallbackQuery):
    owner = int(query.data.split(":")[1])
    if query.from_user.id != owner:
        await query.answer("Це не ваша кнопка 🙂", show_alert=True)
        return
    await reset_user(owner)
    await query.answer("Готово!")
    try:
        await query.message.edit_text(
            "🔄 <b>Профіль скинуто до нуля.</b>\nСпробуйте надіслати <code>/start</code>.",
            parse_mode=HTML,
        )
    except Exception:
        pass


@dp.callback_query(F.data.startswith("reset_no:"))
async def cb_reset_no(query: types.CallbackQuery):
    owner = int(query.data.split(":")[1])
    if query.from_user.id != owner:
        await query.answer("Це не ваша кнопка 🙂", show_alert=True)
        return
    await query.answer("Скасовано")
    try:
        await query.message.edit_text("👌 Скидання скасовано.")
    except Exception:
        pass


# ---------- Обработчики кнопок ----------
# ВАЖНО: передаём query.from_user — того, кто реально нажал кнопку.

@dp.callback_query(F.data == "play_roulette")
async def cb_roulette(query: types.CallbackQuery):
    await query.answer()
    await cmd_roulette(query.message, from_user=query.from_user)


@dp.callback_query(F.data == "show_profile")
async def cb_profile(query: types.CallbackQuery):
    await query.answer()
    await cmd_profile(query.message, from_user=query.from_user)
