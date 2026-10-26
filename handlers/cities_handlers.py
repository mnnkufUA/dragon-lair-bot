import logging

from aiogram import Router, types, F
from aiogram.filters import Command, Filter

import database
try:
    from games.cities_game import CitiesGame, Player, active_cities_games
except ImportError:
    from cities_game import CitiesGame, Player, active_cities_games
from handlers.bomb_handlers import chat_has_game, can_stop_game, _creating_chats
from config import CITIES_TURN_SECONDS

logger = logging.getLogger(__name__)

router = Router(name="cities_router")


class IsCitiesTurnFilter(Filter):
    async def __call__(self, message: types.Message) -> bool:
        if not message.from_user:
            return False
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

    if chat_has_game(chat_id):
        game = active_cities_games.get(chat_id)
        if game and game.state == "LOBBY":
            await message.answer("⚠️ У цьому чаті вже відкрито збір каравану! Тисніть «➕ Приєднатися» вище.")
        elif game:
            await message.answer(
                "⚠️ У цьому чаті вже триває гра «Міста Дракона»!\nЩоб зупинити раунд примусово, надішліть команду <code>/stop_cities</code>.",
                parse_mode="HTML"
            )
        else:
            await message.answer("⚠️ У цьому чаті вже йде інша гра. Дочекайтеся її завершення.")
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

    _creating_chats.add(chat_id)
    try:
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
        try:
            await game.start_lobby(message.bot)
        except Exception:
            # Не удалось отправить лобби — снимаем игру и возвращаем ставку, чтобы чат не завис
            logger.exception("cities start_lobby failed")
            active_cities_games.pop(chat_id, None)
            if bet > 0:
                await database.add_coins(creator_id, bet)
            await message.answer("⚠️ Не вдалося запустити гру. Спробуйте ще раз.")
    finally:
        _creating_chats.discard(chat_id)


@router.message(Command("stop_cities", "stopcities", "стоп_міста"))
async def cmd_stop_cities(message: types.Message):
    chat_id = message.chat.id
    game = active_cities_games.get(chat_id)
    if not game:
        await message.answer("У цьому чаті зараз немає активної гри в Міста.")
        return

    if not await can_stop_game(message, game.creator_id):
        await message.answer("🚫 Зупинити гру може лише той, хто її створив, або адміністратор чату.")
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

    if callback.from_user.id != game.creator_id:
        await callback.answer("Лише ініціатор може змінювати час!", show_alert=True)
        return

    try:
        speed = int(callback.data.replace("cities_speed_", ""))
        await game.set_speed(speed, callback.bot)
        await callback.answer(f"⏱️ Час на відповідь: {speed} секунд!")
    except Exception:
        await callback.answer("Помилка зміни часу.", show_alert=True)


# Эти 3 обработчика раньше отсутствовали — кнопки режима и команд в лобби «Міст» не реагировали.
@router.callback_query(F.data.in_({"cities_mode_team", "cities_mode_ffa"}))
async def cb_cities_mode(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    game = active_cities_games.get(chat_id)
    if not game:
        await callback.answer("Лобі вже не дійсне.", show_alert=True)
        return

    if callback.from_user.id != game.creator_id:
        await callback.answer("Лише ініціатор може змінювати режим!", show_alert=True)
        return

    mode = "TEAM" if callback.data == "cities_mode_team" else "FFA"
    await game.set_mode(mode, callback.bot)
    await callback.answer("🛡️ Командний режим!" if mode == "TEAM" else "⚔️ Кожен сам за себе!")


@router.callback_query(F.data.in_({"cities_team_red", "cities_team_blue"}))
async def cb_cities_team(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    game = active_cities_games.get(chat_id)
    if not game:
        await callback.answer("Лобі вже не дійсне.", show_alert=True)
        return

    team = "red" if callback.data == "cities_team_red" else "blue"
    ok = await game.set_team(callback.from_user.id, team, callback.bot)
    if ok:
        await callback.answer("🔴 Ви за Вогонь!" if team == "red" else "🔵 Ви за Лід!")
    else:
        await callback.answer("Спочатку приєднайтесь до гри!", show_alert=True)


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

    if game.state != "LOBBY":
        await callback.answer("Гра вже розпочалась!", show_alert=True)
        return

    ok, msg = await game.start_game(callback.bot)
    await callback.answer("Вирушаємо у подорож!" if ok else msg, show_alert=not ok)


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
        # Раньше тут вызывался несуществующий game.process_city() — любое названное
        # город приводило к ошибке, а игра зависала до таймаута.
        await game.process_word(message.from_user.id, message.text, message.bot)
