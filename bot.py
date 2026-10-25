import os
import random
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, BotCommand
from database import get_or_create_user, update_user, add_game_rewards, reset_user

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://dragon-lair-bot.onrender.com")
TG_APP_URL = os.getenv("TG_APP_URL", "https://t.me/MyDragonLair_bot/app")

dp = Dispatcher()

def get_main_keyboard(is_group: bool = False):
    # Telegram strictly forbids 'web_app' inline buttons in groups!
    # In groups we send standard url= link, in private chat we send web_app=
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

async def setup_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Головне меню та інвентар"),
        BotCommand(command="lair", description="Відкрити Лігво Дракона"),
        BotCommand(command="startdragon", description="Увійти в Лігво"),
        BotCommand(command="profile", description="Профіль та рівні драконів"),
        BotCommand(command="profildragon", description="Особистий профіль"),
        BotCommand(command="roulette", description="🎰 Рулетка драконячих яєць"),
        BotCommand(command="bomb", description="💣 Гра «Бомба»"),
        BotCommand(command="movie", description="🎬 Гра «Вгадай фільм»"),
    ]
    try:
        await bot.set_my_commands(commands)
    except Exception as e:
        print("Could not set bot commands:", e)

START_COMMANDS = ["start", "startdragon", "dragonstart", "start_dragon"]

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
            f"🏰 Вітаємо у **«Лігві Дракона»**, {fname}!\n\n"
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
            "• `/bomb` або `!бомба` — Гра «Бомба» (монети, смаколики та яйця!)\n"
            "• `/movie` або `!фільм` — Гра «Вгадай фільм»\n"
            "• `/roulette` або `!рулетка` — Крутити рулетку яєць\n"
            "• `/lair` або `!моєлігво` — Відкрити Лігво\n"
            "• `/profile` або `/profildragon` — Профіль драконів"
        )

        is_group = message.chat.type in ["group", "supergroup"]
        await message.answer(welcome_text, parse_mode="Markdown", reply_markup=get_main_keyboard(is_group=is_group))
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
        unlocked = json.loads(user['unlocked_elements']) if user.get('unlocked_elements') else []
        is_group = message.chat.type in ["group", "supergroup"]

        if not unlocked:
            await message.answer(
                "🏰 **Ваше Лігво ще спить і порожнє!** 🥚\n\n"
                "У вас ще немає жодного дракона чи магічного яйця.\n"
                "Зіграйте в `/bomb` або `/movie`, вибийте яйце та запустіть `/roulette`!",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard(is_group=is_group)
            )
            return

        if is_group:
            open_btn = InlineKeyboardButton(text="🐉 Відкрити Лігво Дракона", url=TG_APP_URL)
        else:
            open_btn = InlineKeyboardButton(text="🐉 Відкрити Лігво Дракона", web_app=WebAppInfo(url=WEBAPP_URL))

        await message.answer(
            "🏰 **Вхід до вашого гнізда драконів:**\nНатисніть кнопку нижче, щоб відкрити світ драконів:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[open_btn]])
        )
    except Exception as e:
        print("cmd_lair error:", e)

ROULETTE_COMMANDS = ["roulette", "roulettedragon", "рулетка"]
ROULETTE_TRIGGERS = ["!рулетка", "рулетка", "!рулеька", "рулеька", "!roulette", "roulette"]

@dp.message(Command(*ROULETTE_COMMANDS))
@dp.message(F.text.func(lambda text: is_text_trigger(text, ROULETTE_TRIGGERS)))
async def cmd_roulette(message: types.Message):
    try:
        uid = message.from_user.id if message.from_user else message.chat.id
        uname = (message.from_user.username or "") if message.from_user else ""
        fname = (message.from_user.first_name or "Володар") if message.from_user else "Володар"

        user = await get_or_create_user(uid, uname, fname)
        is_group = message.chat.type in ["group", "supergroup"]

        if user['eggs'] < 1:
            await message.answer(
                f"❌ **У вас немає яєць для рулетки!** (Потрібно 1 🥚)\n\n"
                f"💡 **Як отримати яйце:**\n"
                f"• Грайте в `/bomb` або `/movie` (10% шанс вибити драконяче яйце)!\n"
                f"• Отримуйте нагороди за активність у чаті.",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard(is_group=is_group)
            )
            return

        await update_user(user['user_id'], eggs=user['eggs'] - 1)

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

        is_duplicate = won_elem in unlocked

        if is_duplicate:
            await update_user(user['user_id'], food=user['food'] + 5)
            text = (
                f"🎰 **Рулетка прокручена!** (-1 🥚)\n\n"
                f"✨ Випала стихія: **{elem_names[won_elem]}**!\n"
                f"ℹ️ У вас вже є цей дракон. Компенсація: **+5 🍖 смаколиків**!"
            )
        else:
            unlocked.append(won_elem)
            if not user.get('active_element'):
                await update_user(user['user_id'], active_element=won_elem)
            if won_elem not in levels:
                levels[won_elem] = 1
            await update_user(
                user['user_id'],
                unlocked_elements=json.dumps(unlocked),
                dragon_levels=json.dumps(levels)
            )
            text = (
                f"🎰 **РУЛЕТКА ПРОКРУЧЕНА!** (-1 🥚)\n\n"
                f"🎉 **НЕЙМОВІРНО! ВИ ВІДКРИЛИ НОВОГО ДРАКОНА!**\n"
                f"🐉 Стихія: **{elem_names[won_elem]}**\n\n"
                f"Тепер він доступний у вашому лігві! Перейдіть у меню та познайомтеся зі своїм новим улюбленцем."
            )

        await message.answer(text, parse_mode="Markdown", reply_markup=get_main_keyboard(is_group=is_group))
    except Exception as e:
        print("cmd_roulette error:", e)

BOMB_COMMANDS = ["bomb", "bombgame", "bombdragon", "бомба", "гра_бомба"]
BOMB_TRIGGERS = ["!бомба", "бомба", "!гра бомба", "гра бомба", "!bomb", "bomb"]

@dp.message(Command(*BOMB_COMMANDS))
@dp.message(F.text.func(lambda text: is_text_trigger(text, BOMB_TRIGGERS)))
async def cmd_bomb(message: types.Message):
    try:
        uid = message.from_user.id if message.from_user else message.chat.id
        uname = (message.from_user.username or "") if message.from_user else ""
        fname = (message.from_user.first_name or "Володар") if message.from_user else "Володар"

        user = await get_or_create_user(uid, uname, fname)
        is_group = message.chat.type in ["group", "supergroup"]

        coins = random.randint(15, 20)
        food = 1 if random.random() < 0.20 else 0
        egg = 1 if random.random() < 0.10 else 0

        await add_game_rewards(user['user_id'], coins=coins, food=food, eggs=egg)

        msg = f"💣 **Перемога в грі «Бомба»!**\nВи вчасно знешкодили вибухівку й отримали: **+{coins} 🪙 Монет**"
        if food > 0:
            msg += "\n🍖 **+1 смаколик** (випав з 20% шансом)!"
        if egg > 0:
            msg += "\n🥚 **ВАМ ВИПАЛО ДРАКОНЯЧЕ ЯЙЦЕ (10% шанс)!**\nЗапустіть команду `/roulette` або `!рулетка`, щоб відкрити дракона!"

        await message.answer(msg, parse_mode="Markdown", reply_markup=get_main_keyboard(is_group=is_group))
    except Exception as e:
        print("cmd_bomb error:", e)

MOVIE_COMMANDS = ["movie", "moviegame", "moviedragon", "фільм", "вгадай_фільм"]
MOVIE_TRIGGERS = ["!фільм", "фільм", "!вгадай фільм", "вгадай фільм", "!movie", "movie"]

@dp.message(Command(*MOVIE_COMMANDS))
@dp.message(F.text.func(lambda text: is_text_trigger(text, MOVIE_TRIGGERS)))
async def cmd_movie(message: types.Message):
    try:
        uid = message.from_user.id if message.from_user else message.chat.id
        uname = (message.from_user.username or "") if message.from_user else ""
        fname = (message.from_user.first_name or "Володар") if message.from_user else "Володар"

        user = await get_or_create_user(uid, uname, fname)
        is_group = message.chat.type in ["group", "supergroup"]

        coins = random.randint(15, 20)
        food = 1 if random.random() < 0.20 else 0
        egg = 1 if random.random() < 0.10 else 0

        await add_game_rewards(user['user_id'], coins=coins, food=food, eggs=egg)

        msg = f"🎬 **«Вгадай фільм» пройдено успішно!**\nВідмінна ерудиція: **+{coins} 🪙 Монет**"
        if food > 0:
            msg += "\n🍖 **+1 смаколик** (випав з 20% шансом)!"
        if egg > 0:
            msg += "\n🥚 **ВАМ ВИПАЛО ДРАКОНЯЧЕ ЯЙЦЕ (10% шанс)!**\nЗапустіть команду `/roulette` або `!рулетка`, щоб відкрити дракона!"

        await message.answer(msg, parse_mode="Markdown", reply_markup=get_main_keyboard(is_group=is_group))
    except Exception as e:
        print("cmd_movie error:", e)

PROFILE_COMMANDS = ["profile", "profildragon", "profiledragon", "dragonprofile", "профіль", "профиль"]
PROFILE_TRIGGERS = ["!профіль", "профіль", "!профиль", "профиль", "!profildragon", "!profile", "profildragon", "profile"]

@dp.message(Command(*PROFILE_COMMANDS))
@dp.message(F.text.func(lambda text: is_text_trigger(text, PROFILE_TRIGGERS)))
async def cmd_profile(message: types.Message):
    try:
        uid = message.from_user.id if message.from_user else message.chat.id
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
            f"👤 **Профіль володаря драконів ({fname}):**\n\n"
            f"🪙 Монети: **{user['coins']}**\n"
            f"💧 Сльози дракона: **{user['tears']}**\n"
            f"🍖 Смаколики: **{user['food']} шт**\n"
            f"🥚 Драконячі яйця: **{user['eggs']} шт**\n\n"
            f"🐉 **Активний дракон:** {active_str}\n"
            f"🔓 Відкрито стихій: **{len(unlocked)} / 4**\n"
            f"{dragons_detail}"
        )
        await message.answer(text, parse_mode="Markdown", reply_markup=get_main_keyboard(is_group=is_group))
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
    await cmd_movie(query.message)

@dp.callback_query(F.data == "play_roulette")
async def cb_roulette(query: types.CallbackQuery):
    await query.answer()
    await cmd_roulette(query.message)

@dp.callback_query(F.data == "show_profile")
async def cb_profile(query: types.CallbackQuery):
    await query.answer()
    await cmd_profile(query.message)
