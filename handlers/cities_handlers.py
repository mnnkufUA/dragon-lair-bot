from aiogram import Router, types, F
from aiogram.filters import Command, Filter
import database
from games.cities_game import CitiesGame, Player, active_cities_games
from config import CITIES_TURN_SECONDS

router = Router(name="cities_router")


class IsCitiesTurnFilter(Filter):
    async def __call__(self, message: types.Message) -> bool:
        game = active_cities_games.get(message.chat.id)
        return bool(
            game 
            and game.state == "ACTIVE" 
            and game.current_player 
            and game.current_player.user_id == message.from_user.id
        )


CITIES_TRIGGERS = {"!міста", "міста", "!місто", "місто", "!cities", "cities", "!city", "city"}

def is_cities_trigger(text: str) -> bool:
    if not text:
        return False
    clean = text.lower().strip().split("@")[0].strip()
    return clean in CITIES_TRIGGERS


@router.message(Command("cities", "city", "міста", "місто"))
@router.message(F.text.func(is_cities_trigger))
async def cmd_cities(message: types.Message):
    chat_id = message.chat.id

    if chat_id in active_cities_games:
        game = active_cities_games[chat_id]
        if game.state == "LOBBY":
            await message.answer("⚠️ У цьому чаті вже відкрито збір каравану! Тисніть «➕ Приєднатися» вище.")
        else:
            await message.answer(
                "⚠️ У цьому чаті вже триває гра «Міста Дракона»!\nЩоб зупинити раунд примусово, надішліть команду `/stop_cities`.",
                parse_mode="Markdown"
            )
        return

    bet = 0
    turn_seconds = CITIES_TURN_SECONDS
    args = (message.text or "").split()

    if len(args) > 1:
        try:
            bet = int(args[1])
            if bet < 0:
                bet = 0
            if bet > 100000:
                await message.answer("❌ Максимальна ставка: 100 000 🪙")
                return
        except ValueError:
            pass

    creator_id = message.from_user.id if message.from_user else message.chat.id
    if bet > 0:
        has_funds = await database.try_deduct_coins(creator_id, bet)
        if not has_funds:
            await message.answer(f"❌ Недостатньо 🪙 монет для ставки {bet}!")
            return

    creator_player = Player(
        user_id=creator_id,
        username=message.from_user.username if message.from_user else "",
        first_name=message.from_user.first_name if message.from_user else "Мандрівник"
    )

    game = CitiesGame(chat_id=chat_id, creator=creator_player, bet=bet, turn_seconds=turn_seconds)
    active_cities_games[chat_id] = game
    await game.start_lobby(message.bot)


@router.message(Command("stop_cities", "stopcities", "стоп_міста"))
async def cmd_stop_cities(message: types.Message):
    chat_id = message.chat.id
    game = active_cities_games.get(chat_id)
    if not game:
        await message.answer("У цьому чаті зараз немає активної гри в Міста.")
        return

    name = message.from_user.first_name if message.from_user else "Гравцем"
    await game.force_stop(
        message.bot,
        reason=f"Гру зупинено {name}."
    )


@router.callback_query(F.data.startswith("cities_speed_"))
async def cb_cities_speed(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    game = active_cities_games.get(chat_id)
    if not game:
        await callback.answer("Гра вже не активна.", show_alert=True)
        return

    try:
        speed = int(callback.data.replace("cities_speed_", ""))
        await game.set_speed(speed, callback.bot)
        await callback.answer(f"⏱️ Час на відповідь: {speed} секунд!")
    except Exception:
        await callback.answer("Помилка зміни часу.", show_alert=True)


@router.callback_query(F.data == "cities_join")
async def cb_cities_join(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    game = active_cities_games.get(chat_id)
    if not game:
        await callback.answer("Лобі вже не дійсне.", show_alert=True)
        return

    player = Player(
        user_id=callback.from_user.id,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name
    )
    success, msg = await game.add_player(player, callback.bot)
    await callback.answer(msg, show_alert=not success)


@router.callback_query(F.data == "cities_leave")
async def cb_cities_leave(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    game = active_cities_games.get(chat_id)
    if not game:
        await callback.answer("Лобі вже не дійсне.", show_alert=True)
        return

    success, msg = await game.remove_player(callback.from_user.id, callback.bot)
    await callback.answer(msg, show_alert=not success)


@router.callback_query(F.data == "cities_start_now")
async def cb_cities_start_now(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    game = active_cities_games.get(chat_id)
    if not game:
        await callback.answer("Лобі не знайдено.", show_alert=True)
        return

    if callback.from_user.id != game.creator_id:
        await callback.answer("Лише ініціатор може розпочати гру достроково!", show_alert=True)
        return

    await callback.answer("Вирушаємо у подорож!")
    await game.start_game(callback.bot)


@router.callback_query(F.data == "cities_compass")
async def cb_cities_compass(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    game = active_cities_games.get(chat_id)
    if not game:
        await callback.answer("Гра не знайдена.", show_alert=True)
        return

    success, msg = await game.use_compass(callback.from_user.id, callback.bot)
    await callback.answer(msg, show_alert=not success)


@router.message(F.text, ~F.text.startswith("/"), ~F.text.startswith("!"), IsCitiesTurnFilter())
async def handle_cities_turn(message: types.Message):
    chat_id = message.chat.id
    game = active_cities_games.get(chat_id)
    if game:
        await game.process_city(message.from_user.id, message.text, message.bot)
