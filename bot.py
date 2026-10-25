import os
import random
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from database import get_or_create_user, update_user, add_game_rewards

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://your-domain.onrender.com")

dp = Dispatcher()

def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🐉 Увійти в Моє Лігво", web_app=WebAppInfo(url=WEBAPP_URL))
        ],
        [
            InlineKeyboardButton(text="💣 Гра «Бомба»", callback_data="play_bomb"),
            InlineKeyboardButton(text="🎬 «Вгадай фільм»", callback_data="play_movie")
        ],
        [
            InlineKeyboardButton(text="🎰 Крутити !рулетка", callback_data="play_roulette"),
            InlineKeyboardButton(text="👤 Профіль", callback_data="show_profile")
        ]
    ])

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user = await get_or_create_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    welcome_text = (
        f"👋 Вітаємо у **«Лігві Дракона»**, {message.from_user.first_name}!\n\n"
        f"🥚 Перед вами магічне гніздо, де живуть легендарні 3D-дракони!\n\n"
        f"💰 **Ваш початковий баланс:**\n"
        f"• 🪙 Монети: **{user['coins']}**\n"
        f"• 💧 Сльози Дракона: **{user['tears']}**\n"
        f"• 🍖 Смаколики (їжа): **{user['food']}**\n"
        f"• 🥚 Яйця в інвентарі: **{user['eggs']}**\n\n"
        f"🎮 Грайте в ігри чату, вибивайте яйця стихій та смаколики, або відкрийте своє 3D-гніздо прямо зараз:"
    )
    await message.answer(welcome_text, parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(F.text.lower().in_({"!моє лігво", "моє лігво", "!лигво", "/lair"}))
async def cmd_lair(message: types.Message):
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
            "⚠️ **У вас немає яєць для рулетки!** (Баланс: 0 🥚)\n\n"
            "🎮 Виграйте в чат-ігри **«Бомба»** або **«Вгадай фільм»**, щоб отримати яйце дракона з шансом **10%**!",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        return

    # Deduct 1 egg
    await update_user(user['user_id'], eggs=user['eggs'] - 1)

    elements = ['fire', 'storm', 'frost', 'jade']
    elem_names = {
        'fire': "🔥 Вогняне яйце (Тифумеранг)",
        'storm': "⚡ Грозове яйце (Флайтмейр)",
        'frost': "❄️ Крижане яйце (Дрімдракон)",
        'jade': "🌿 Смарагдове яйце (Синґтейл)"
    }
    won_elem = random.choice(elements)
    unlocked = json.loads(user['unlocked_elements'])

    if won_elem in unlocked:
        # Duplicate compensation: +5 Food
        await update_user(user['user_id'], food=user['food'] + 5)
        text = (
            f"🎰 **РУЛЕТКА 4 ЯЄЦЬ ЗУПИНИЛАСЯ!**\n\n"
            f"Вам випало: **{elem_names[won_elem]}**\n"
            f"⚠️ Оскільки цей дракон уже розблокований у вашому лігві, ви отримуєте компенсацію:\n"
            f"🍖 **+5 Смаколиків (їжі) в інвентар!**"
        )
    else:
        unlocked.append(won_elem)
        await update_user(user['user_id'], unlocked_elements=unlocked)
        text = (
            f"🎉 **ЛЕГЕНДАРНИЙ ДРОП У РУЛЕТЦІ!**\n\n"
            f"Вам випало абсолютно НОВЕ яйце:\n"
            f"✨ **{elem_names[won_elem]}** ✨\n\n"
            f"Дракон розблокований! Заходьте в **!моє лігво**, щоб дати йому власне ім'я!"
        )

    await message.answer(text, parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(F.text.lower().in_({"!бомба", "бомба", "/bomb"}))
async def cmd_bomb(message: types.Message):
    user = await get_or_create_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    coins = random.randint(15, 20)
    food = 1 if random.random() < 0.20 else 0
    egg = 1 if random.random() < 0.10 else 0

    await add_game_rewards(user['user_id'], coins=coins, food=food, eggs=egg)

    msg = f"💣 **Перемога у грі «Бомба»!**\nВи успішно знешкодили вибухівку та отримали: **+{coins} 🪙 Монет**"
    if food > 0:
        msg += "\n🍖 **+1 Смаколик** (випав з 20% шансом)!"
    if egg > 0:
        msg += "\n🥚 **ВАМ ВИПАЛО ЯЙЦЕ ДРАКОНА (10% шанс)!**\nКрутіть команду `!рулетка`, щоб забрати дракона!"

    await message.answer(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(F.text.lower().in_({"!фільм", "вгадай фільм", "/movie"}))
async def cmd_movie(message: types.Message):
    user = await get_or_create_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    coins = random.randint(15, 20)
    food = 1 if random.random() < 0.20 else 0
    egg = 1 if random.random() < 0.10 else 0

    await add_game_rewards(user['user_id'], coins=coins, food=food, eggs=egg)

    msg = f"🎬 **«Вгадай фільм» відгадано правильно!**\nНагорода за ерудицію: **+{coins} 🪙 Монет**"
    if food > 0:
        msg += "\n🍖 **+1 Смаколик** (випав з 20% шансом)!"
    if egg > 0:
        msg += "\n🥚 **ВАМ ВИПАЛО ЯЙЦЕ ДРАКОНА (10% шанс)!**\nКрутіть команду `!рулетка`, щоб забрати дракона!"

    await message.answer(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

@dp.message(F.text.lower().in_({"!профіль", "профіль", "/profile"}))
async def cmd_profile(message: types.Message):
    user = await get_or_create_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    unlocked = json.loads(user['unlocked_elements'])
    names = json.loads(user['dragon_names'])
    levels = json.loads(user['dragon_levels'])

    elem_icons = {'fire': '🔥', 'storm': '⚡', 'frost': '❄️', 'jade': '🌿'}
    active = user['active_element']
    active_name = names.get(active, "Дракон")
    active_lvl = levels.get(active, 1)

    text = (
        f"👤 **Профіль Повелителя Драконів:**\n\n"
        f"🪙 Монети: **{user['coins']}**\n"
        f"💧 Сльози Дракона: **{user['tears']}**\n"
        f"🍖 Смаколики: **{user['food']} шт**\n"
        f"🥚 Яйця для рулетки: **{user['eggs']} шт**\n\n"
        f"🐉 **Активний супутник:** {elem_icons.get(active, '🐉')} **{active_name}** (Lv {active_lvl})\n"
        f"🔓 Відкриті стихії: **{len(unlocked)} / 4**\n"
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=get_main_keyboard())

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
