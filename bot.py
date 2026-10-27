import os
import random
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, BotCommand
from database import get_or_create_user, update_user, add_game_rewards, reset_user

from config import BOT_TOKEN, WEBAPP_URL, TG_APP_URL
try:
    from handlers.bomb_handlers import router as bomb_router, cmd_bomb
except ImportError:
    from bomb_handlers import router as bomb_router, cmd_bomb

try:
    from handlers.hunt_handlers import router as hunt_router, cmd_hunt
except ImportError:
    from hunt_handlers import router as hunt_router, cmd_hunt

try:
    from handlers.cities_handlers import router as cities_router, cmd_cities
except ImportError:
    from cities_handlers import router as cities_router, cmd_cities

dp = Dispatcher()
dp.include_router(bomb_router)
dp.include_router(hunt_router)
dp.include_router(cities_router)

def get_main_keyboard(is_group: bool = False, user_id: int = None, has_started: bool = True):
    # Telegram strictly forbids 'web_app' inline buttons in groups!
    # In groups we send standard url= link with startapp parameter, in private chat we send web_app=
    if is_group:
        if has_started and user_id:
            lair_btn = InlineKeyboardButton(text="🐉 Увійти в Лігво", url=f"https://t.me/MyDragonLair_bot/app?startapp=user_{user_id}")
        else:
            lair_btn = InlineKeyboardButton(text="🐉 Увійти в Лігво", url="https://t.me/MyDragonLair_bot?start=lair")
    else:
        url = f"{WEBAPP_URL}?user_id={user_id}" if user_id else WEBAPP_URL
        lair_btn = InlineKeyboardButton(text="🐉 Увійти в Лігво", web_app=WebAppInfo(url=url))

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
        print("Could not set bot commands:", e)

START_COMMANDS = ["start", "startdragon", "dragonstart", "start_dragon"]


# --- USER ID DISCOVERY COMMAND ---
MYID_COMMANDS = ["myid", "id", "айди", "мойайди"]
MYID_TRIGGERS = ["!id", "!айди", "айди", "id", "!myid", "мій id", "мой id", "!мійid", "!мойid"]

@dp.message(Command(*MYID_COMMANDS))
@dp.message(F.text.func(lambda text: is_text_trigger(text, MYID_TRIGGERS)))
async def cmd_myid(message: types.Message):
    try:
        uid = message.from_user.id if message.from_user else message.chat.id
        await message.answer(
            f"🆔 <b>Ваш числовий Telegram ID:</b> <code>{uid}</code>\n"
            f"<i>(натисніть для копіювання)</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        print("cmd_myid error:", e)

@dp.message(Command(*START_COMMANDS))
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    try:
        uid = message.from_user.id if message.from_user else message.chat.id
        uname = (message.from_user.username or "") if message.from_user else ""
        fname = (message.from_user.first_name or "Володар") if message.from_user else "Володар"

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
            status_dragon = f"{elem_names.get(active, '🐉')} **«{custom_name}»**"

        welcome_text = (
            f"🏰 Вітаємо у **«Лігві Дракона»**, {fname}!\n"
            f"🆔 **Ваш Telegram ID:** `{uid}`\n\n"
            f"✨ Це магічний світ, де ви зрощуєте та тренуєте живих 3D-драконів!\n\n"
            f"👛 **Ваш інвентар:**\n"
            f"🪙 Монети: **{user['coins']}**\n"
            f"💧 Сльози дракона: **{user['tears']}**\n"
            f"🍖 Смаколики (їжа): **{user['food']}**\n"
            f"🥚 Драконячі яйця: **{user['eggs']}**\n\n"
            f"🐉 **Ваш дракон:** {status_dragon}\n\n"
        )

        if not unlocked:
            welcome_text += (
                "🥚 **Ваше Лігво ще порожнє!**\n"
                "У вас ще немає жодного дракона. Відкрийте або знайдіть свого першого дракона, щоб увійти до лігва!\n\n"
            )
        else:
            welcome_text += "🎮 Натискайте **🐉 Увійти в Лігво**, щоб тренувати та милуватися своїм драконом!\n\n"

        welcome_text += (
            "🎮 **Швидкі команди:**\n"
            "• `/bomb` або `!бомба` — Гра «Бомба» (слова, склади, монети, їжа та яйця!)\n"
            "• `/movie` або `!фільм` — Гра «Вгадай фільм / гру» (постери та дешифровка)\n"
            "• `/cities` або `!міста` — Гра «Міста Дракона» (географічна битва)\n"
            "• `/roulette` або `!рулетка` — Крутити рулетку яєць\n"
            "• `/lair` або `!моєлігво` — Відкрити 3D Лігво Дракона\n"
            "• `/profile` — Особистий профіль володаря драконів"
        )

        is_group = message.chat.type in ["group", "supergroup"]
        if not is_group:
            await update_user(uid, has_started=1)
            # Check deep link start args
            text_parts = message.text.split() if message.text else []
            if len(text_parts) > 1:
                arg = text_parts[1].lower()
                if arg == "roulette":
                    await cmd_roulette(message)
                    return

        has_started = bool(user.get('has_started', 0)) if is_group else True
        await message.answer(welcome_text, parse_mode="Markdown", reply_markup=get_main_keyboard(is_group=is_group, user_id=uid, has_started=has_started))
    except Exception as e:
        print("cmd_start error:", e)

LAIR_COMMANDS = ["lair", "dragon", "дракон", "лігво", "моєлігво", "startdragon"]
LAIR_TRIGGERS = ["!моєлігво", "!моє лігво", "моєлігво", "моє лігво", "!лігво", "лігво", "!lair", "lair"]

@dp.message(Command(*LAIR_COMMANDS))
@dp.message(F.text.func(lambda text: is_text_trigger(text, LAIR_TRIGGERS)))
async def cmd_lair(message: types.Message):
    try:
        uid = message.from_user.id if message.from_user else message.chat.id
        uname = (message.from_user.username or "") if message.from_user else ""
        fname = (message.from_user.first_name or "Володар") if message.from_user else "Володар"

        user = await get_or_create_user(uid, uname, fname)
        is_group = message.chat.type in ["group", "supergroup"]

        if is_group:
            if user.get('has_started', 0) == 1:
                lair_url = f"https://t.me/MyDragonLair_bot/app?startapp=user_{uid}"
                open_btn = InlineKeyboardButton(text="🐉 Відкрити Лігво Дракона", url=lair_url)
            else:
                lair_url = "https://t.me/MyDragonLair_bot?start=lair"
                open_btn = InlineKeyboardButton(text="🐉 Відкрити Лігво Дракона", url=lair_url)
        else:
            open_btn = InlineKeyboardButton(text="🐉 Відкрити Лігво Дракона", web_app=WebAppInfo(url=f"{WEBAPP_URL}?user_id={uid}"))

        await message.answer(
            "🏰 **Вхід до вашого гнізда драконів:**\nНатисніть кнопку нижче, щоб відкрити 3D світ драконів:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[open_btn]])
        )
    except Exception as e:
        print("cmd_lair error:", e)

ROULETTE_COMMANDS = ["roulette", "roulettedragon", "рулетка"]
ROULETTE_TRIGGERS = ["!рулетка", "рулетка", "!рулеька", "рулеька", "!roulette", "roulette"]

@dp.message(Command(*ROULETTE_COMMANDS))
@dp.message(F.text.func(lambda text: is_text_trigger(text, ROULETTE_TRIGGERS)))
async def cmd_roulette(message: types.Message, user_override: types.User = None):
    try:
        user_obj = user_override or message.from_user
        uid = user_obj.id if user_obj else message.chat.id
        uname = (user_obj.username or "") if user_obj else ""
        fname = (user_obj.first_name or "Володар") if user_obj else "Володар"

        user = await get_or_create_user(uid, uname, fname)
        is_group = message.chat.type in ["group", "supergroup"]

        if user['eggs'] < 1:
            await message.answer(
                "❌ **У вас немає драконячих яєць!** (Потрібно 1 🥚)\n\n"
                "💡 **Як отримати яйце:**\n"
                "• Перемагайте в іграх `/bomb`, `/movie` або `/cities` (10% шанс вибити драконяче яйце у кожній грі)!",
                parse_mode="Markdown"
            )
            return

        # Player has eggs >= 1! Launch Roulette in Mini App!
        if is_group:
            if user.get('has_started', 0) == 1:
                roulette_url = f"https://t.me/MyDragonLair_bot/app?startapp=roulette_{uid}"
                btn = InlineKeyboardButton(text="🎰 Відкрити Рулетку в Лігві", url=roulette_url)
            else:
                roulette_url = "https://t.me/MyDragonLair_bot?start=roulette"
                btn = InlineKeyboardButton(text="🎰 Відкрити Рулетку в Лігві", url=roulette_url)
        else:
            roulette_url = f"{WEBAPP_URL}?open=roulette&user_id={uid}"
            btn = InlineKeyboardButton(text="🎰 Відкрити Рулетку в Лігві", web_app=WebAppInfo(url=roulette_url))

        await message.answer(
            "🎰 **Рулетка 4 Стихій Дракона готова до запуску!**\n"
            "Використайте 1 🥚, щоб випробувати удачу та вибити дракона у 3D!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn]])
        )
    except Exception as e:
        print("cmd_roulette error:", e)

PROFILE_COMMANDS = ["profile", "profildragon", "profiledragon", "dragonprofile", "профіль", "профиль"]
PROFILE_TRIGGERS = ["!профіль", "профіль", "!профиль", "профиль", "!profildragon", "!profile", "profildragon", "profile"]

@dp.message(Command(*PROFILE_COMMANDS))
@dp.message(F.text.func(lambda text: is_text_trigger(text, PROFILE_TRIGGERS)))
async def cmd_profile(message: types.Message, user_override: types.User = None):
    try:
        user_obj = user_override or message.from_user
        uid = user_obj.id if user_obj else message.chat.id
        uname = (message.from_user.username or "") if message.from_user else ""
        fname = (message.from_user.first_name or "Володар") if message.from_user else "Володар"

        user = await get_or_create_user(uid, uname, fname)
        unlocked = json.loads(user['unlocked_elements']) if user.get('unlocked_elements') else []
        names = json.loads(user['dragon_names']) if user.get('dragon_names') else {}
        levels = json.loads(user['dragon_levels']) if user.get('dragon_levels') else {}
        is_group = message.chat.type in ["group", "supergroup"]

        elem_icons = {'fire': '🔥', 'storm': '⚡', 'frost': '❄️', 'jade': '🎋'}
        active = user.get('active_element', '')
        
        if active and active in unlocked:
            active_name = names.get(active, "Дракон")
            active_lvl = levels.get(active, 1)
            active_str = f"{elem_icons.get(active, '🐉')} **«{active_name}»** (Lv {active_lvl})"
        else:
            active_str = "🔒 Ще немає (Лігво спить)"

        dragons_detail = ""
        if unlocked:
            dragons_detail = "\n🐉 **Рівні ваших драконів:**\n"
            for el in unlocked:
                el_icon = elem_icons.get(el, '🐉')
                el_name = names.get(el, el.capitalize())
                el_lvl = levels.get(el, 1)
                marker = " *(активний)*" if el == active else ""
                dragons_detail += f"• {el_icon} {el_name}: **Рівень {el_lvl}**{marker}\n"

        text = (
            f"👤 **Профіль володаря драконів ({fname}):**\n"
            f"🆔 **Ваш Telegram ID:** `{uid}`\n\n"
            f"🪙 Монети: **{user['coins']}**\n"
            f"💧 Сльози дракона: **{user['tears']}**\n"
            f"🍖 Смаколики: **{user['food']} шт**\n"
            f"🥚 Драконячі яйця: **{user['eggs']} шт**\n\n"
            f"🐉 **Активний дракон:** {active_str}\n"
            f"🔓 Відкрито стихій: **{len(unlocked)} / 4**\n"
            f"{dragons_detail}"
        )
        await message.answer(text, parse_mode="Markdown", reply_markup=get_main_keyboard(is_group=is_group, user_id=uid))
    except Exception as e:
        print("cmd_profile error:", e)

@dp.message(Command("reset"))
async def cmd_reset(message: types.Message):
    try:
        uid = message.from_user.id if message.from_user else message.chat.id
        await reset_user(uid)
        is_group = message.chat.type in ["group", "supergroup"]
        await message.answer(
            "🔄 **Ваш профіль повністю скинуто до нуля!**\n"
            "У вас тепер 0 монет, 0 яєць, 0 драконів — стан чистого нового гравця.\n"
            "Спробуйте надіслати `/start` або `!моєлігво`.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(is_group=is_group)
        )
    except Exception as e:
        print("cmd_reset error:", e)

# Callback queries handlers
@dp.callback_query(F.data == "play_bomb")
async def cb_bomb(query: types.CallbackQuery):
    await query.answer()
    await cmd_bomb(query.message)

@dp.callback_query(F.data == "play_movie")
async def cb_movie(query: types.CallbackQuery):
    await query.answer()
    await cmd_hunt(query.message)

@dp.callback_query(F.data == "play_roulette")
async def cb_roulette(query: types.CallbackQuery):
    await query.answer()
    await cmd_roulette(query.message, user_override=query.from_user)

@dp.callback_query(F.data == "show_profile")
async def cb_profile(query: types.CallbackQuery):
    await query.answer()
    await cmd_profile(query.message, user_override=query.from_user)