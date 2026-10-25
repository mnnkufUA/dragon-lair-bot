import os
import random
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from database import get_or_create_user, update_user, add_game_rewards, reset_user

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://your-domain.onrender.com")

dp = Dispatcher()

def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🐉 Увійти в 3D Лігво", web_app=WebAppInfo(url=WEBAPP_URL))
        ],
        [
            InlineKeyboardButton(text="💣 Гра «Бомба»", callback_data="play_bomb"),
            InlineKeyboardButton(text="🎬 «Вгадай фільм»", callback_data="play_movie")
        ],
        [
            InlineKeyboardButton(text="🎰 Крутити !рулетка", callback_data="play_roulette"),
            InlineKeyboardButton(text="👤 Мій Профіль", callback_data="show_profile")
        ]
    ])

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user = await get_or_create_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
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
        f"🏰 Вітаємо у **«Лігві Дракона»**, {message.from_user.first_name}!\n\n"
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
            "🥚 **Ваше 3D-лігво ще порожнє!**\n"
            "У вас ще немає жодного дракона. Відкрийте або знайдіть свого першого дракона, щоб увійти до лігва!"
        )
    else:
        welcome_text += "🎮 Натискайте **🐉 Увійти в 3D Лігво**, щоб тренувати та милуватися своїм драконом!"

    await message.answer(welcome_text, parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(F.text.lower().in_({"!моє лігво", "моє лігво", "!лігво", "лігво", "/lair"}))
async def cmd_lair(message: types.Message):
    user = await get_or_create_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    unlocked = json.loads(user['unlocked_elements']) if user.get('unlocked_elements') else []

    if not unlocked:
        await message.answer(
            "🏰 **Ваше Лігво ще спить і порожнє!** 🥚\n\n"
            "У вас ще немає жодного дракона чи магічного яйця.\n"
            "Знайдіть або відкрийте свого першого дракона, щоб зайти до 3D-лігва!",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        return

    await message.answer(
        "🏰 **Вхід до вашого 3D-гнізда драконів:**\nНатисніть кнопку нижче, щоб відкрити 3D-світ:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🐉 Відкрити 3D Лігво Дракона", web_app=WebAppInfo(url=WEBAPP_URL))]
        ])
    )

@dp.message(F.text.lower().in_({"!рулетка", "рулетка", "/roulette"}))
async def cmd_roulette(message: types.Message):
    user = await get_or_create_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    if user['eggs'] < 1:
        await message.answer(
            "🥚 **У вас немає яєць для рулетки!** (Баланс: 0 🥚)\n\n"
            "🎮 Грайте в чат-ігри **Гра «Бомба»** або **«Вгадай фільм»**, щоб здобути яйце дракона з шансом **10%**!",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        return

    # Deduct 1 egg
    await update_user(user['user_id'], eggs=user['eggs'] - 1)

    elements = ['fire', 'storm', 'frost', 'jade']
    elem_names = {
        'fire': "🔥 Вогняне яйце (Тифумеранг)",
        'storm': "⚡ Штормове яйце (Флайтмейр)",
        'frost': "❄️ Крижане яйце (Дрімдракон)",
        'jade': "🎋 Нефритове яйце (Синґтейл)"
    }
    won_elem = random.choice(elements)
    unlocked = json.loads(user['unlocked_elements']) if user.get('unlocked_elements') else []

    if won_elem in unlocked:
        # Duplicate compensation: +5 Food
        await update_user(user['user_id'], food=user['food'] + 5)
        text = (
            f"🎰 **РУЛЕТКА СТИХІЙ:**\n\n"
            f"Вам випало яйце стихії: **{elem_names[won_elem]}**!\n"
            f"Оскільки ця стихія у вас вже є, яйце перетворено на поживу для дракона:\n"
            f"🍖 **+5 смаколиків додано до вашого запасу!**"
        )
    else:
        unlocked.append(won_elem)
        active_el = user.get('active_element')
        if not active_el:
            active_el = won_elem
        await update_user(user['user_id'], unlocked_elements=unlocked, active_element=active_el)
        text = (
            f"🎉 **НЕЙМОВІРНО! РУЛЕТКА РОЗБИЛА ШКАРАЛУПУ!**\n\n"
            f"Ви щойно розблокували нове магічне яйце:\n"
            f"✨ **{elem_names[won_elem]}** ✨\n\n"
            f"🏰 **Тепер двері 3D-лігва відчинено!**\n"
            f"Заходьте через кнопку **🐉 Увійти в 3D Лігво**, щоб наректи свого нового дракона та почати його вирощувати!"
        )

    await message.answer(text, parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(F.text.lower().in_({"!бомба", "бомба", "/bomb"}))
async def cmd_bomb(message: types.Message):
    user = await get_or_create_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    coins = random.randint(15, 20)
    food = 1 if random.random() < 0.20 else 0
    egg = 1 if random.random() < 0.10 else 0

    await add_game_rewards(user['user_id'], coins=coins, food=food, eggs=egg)

    msg = f"💣 **Перемога в грі «Бомба»!**\nВи вчасно знешкодили вибухівку й отримали: **+{coins} 🪙 Монет**"
    if food > 0:
        msg += "\n🍖 **+1 смаколик** (випав з 20% шансом)!"
    if egg > 0:
        msg += "\n🥚 **ВАМ ВИПАЛО ДРАКОНЯЧЕ ЯЙЦЕ (10% шанс)!**\nЗапустіть команду `!рулетка`, щоб відкрити дракона!"

    await message.answer(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(F.text.lower().in_({"!фільм", "вгадай фільм", "фільм", "/movie"}))
async def cmd_movie(message: types.Message):
    user = await get_or_create_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    coins = random.randint(15, 20)
    food = 1 if random.random() < 0.20 else 0
    egg = 1 if random.random() < 0.10 else 0

    await add_game_rewards(user['user_id'], coins=coins, food=food, eggs=egg)

    msg = f"🎬 **«Вгадай фільм» пройдено успішно!**\nВідмінна ерудиція: **+{coins} 🪙 Монет**"
    if food > 0:
        msg += "\n🍖 **+1 смаколик** (випав з 20% шансом)!"
    if egg > 0:
        msg += "\n🥚 **ВАМ ВИПАЛО ДРАКОНЯЧЕ ЯЙЦЕ (10% шанс)!**\nЗапустіть команду `!рулетка`, щоб відкрити дракона!"

    await message.answer(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(F.text.lower().in_({"!профіль", "профіль", "/profile"}))
async def cmd_profile(message: types.Message):
    user = await get_or_create_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    unlocked = json.loads(user['unlocked_elements']) if user.get('unlocked_elements') else []
    names = json.loads(user['dragon_names']) if user.get('dragon_names') else {}
    levels = json.loads(user['dragon_levels']) if user.get('dragon_levels') else {}

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
        f"👤 **Профіль володаря драконів:**\n\n"
        f"🪙 Монети: **{user['coins']}**\n"
        f"💧 Сльози дракона: **{user['tears']}**\n"
        f"🍖 Смаколики: **{user['food']} шт**\n"
        f"🥚 Драконячі яйця: **{user['eggs']} шт**\n\n"
        f"🐉 **Активний дракон:** {active_str}\n"
        f"🔓 Відкрито стихій: **{len(unlocked)} / 4**\n"
        f"{dragons_detail}"
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(Command("reset"))
async def cmd_reset(message: types.Message):
    await reset_user(message.from_user.id)
    await message.answer(
        "🔄 **Ваш профіль повністю скинуто до нуля!**\n"
        "У вас тепер 0 монет, 0 яєць, 0 драконів — стан чистого нового гравця.\n"
        "Спробуйте надіслати `/start` або `!моє лігво`.",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

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
