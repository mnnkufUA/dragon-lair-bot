from aiogram import Router, types, F
from aiogram.filters import Command, Filter
import database
from games.cyber_bomb import BombGame, Player, active_bomb_games
from config import BOMB_TURN_SECONDS

router = Router(name="bomb_router")


class IsBombTurnFilter(Filter):
    async def __call__(self, message: types.Message) -> bool:
        game = active_bomb_games.get(message.chat.id)
        return bool(
            game 
            and game.state == "ACTIVE" 
            and game.current_player 
            and game.current_player.user_id == message.from_user.id
        )


BOMB_TRIGGERS = {"!бомба", "бомба", "!bomb", "bomb", "!ядро", "ядро"}

def is_bomb_trigger(text: str) -> bool:
    if not text:
        return False
    clean = text.lower().strip().split("@")[0].strip()
    return clean in BOMB_TRIGGERS


@router.message(Command("bomb", "bombgame", "бомба", "ядро"))
@router.message(F.text.func(is_bomb_trigger))
async def cmd_bomb(message: types.Message):
    chat_id = message.chat.id

    if chat_id in active_bomb_games:
        game = active_bomb_games[chat_id]
        if game.state == "LOBBY":
            await message.answer("⚠️ У цьому чаті вже триває збір у лобі! Натискайте «➕ Приєднатися» вище.")
        else:
            await message.answer(
                "⚠️ У цьому чаті вже лютує «Полум'я Дракона» (Бомба)!\nЯкщо раунд потрібно скинути, надішліть `/stop_bomb`.",
                parse_mode="Markdown"
            )
        return

    bet = 0
    turn_seconds = BOMB_TURN_SECONDS
    args = (message.text or "").split()
    
    if len(args) > 1:
        try:
            bet = int(args[1])
            if bet < 0:
                bet = 0
            if bet > 100000:
                await message.answer("❌ Максимальна ставка: 100 000 🪙 Монет")
                return
        except ValueError:
            pass

    if len(args) > 2:
        try:
            custom_time = int(args[2])
            if 5 <= custom_time <= 60:
                turn_seconds = custom_time
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
        first_name=message.from_user.first_name if message.from_user else "Володар"
    )

    game = BombGame(chat_id=chat_id, creator=creator_player, bet=bet, turn_seconds=turn_seconds)
    active_bomb_games[chat_id] = game
    await game.start_lobby(message.bot)


@router.message(Command("stop_bomb", "stopbomb", "стоп_бомба"))
async def cmd_stop_bomb(message: types.Message):
    chat_id = message.chat.id
    game = active_bomb_games.get(chat_id)
    if not game:
        await message.answer("У цьому чаті зараз немає активної гри «Бомба».")
        return

    name = message.from_user.first_name if message.from_user else "Гравцем"
    await game.force_stop(
        message.bot, 
        reason=f"Гру зупинено волею {name}."
    )


@router.callback_query(F.data.startswith("bomb_speed_"))
async def cb_bomb_speed(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    game = active_bomb_games.get(chat_id)
    if not game:
        await callback.answer("Бій уже не активний.", show_alert=True)
        return

    try:
        speed = int(callback.data.replace("bomb_speed_", ""))
        await game.set_speed(speed, callback.bot)
        await callback.answer(f"⏱️ Час на відповідь встановлено: {speed} сек!")
    except Exception:
        await callback.answer("Помилка зміни часу.", show_alert=True)


@router.callback_query(F.data == "bomb_join")
async def cb_bomb_join(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    game = active_bomb_games.get(chat_id)
    if not game:
        await callback.answer("Це лобі вже не дійсне.", show_alert=True)
        return

    player = Player(
        user_id=callback.from_user.id,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name
    )
    success, msg = await game.add_player(player, callback.bot)
    await callback.answer(msg, show_alert=not success)


@router.callback_query(F.data == "bomb_leave")
async def cb_bomb_leave(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    game = active_bomb_games.get(chat_id)
    if not game:
        await callback.answer("Це лобі вже не дійсне.", show_alert=True)
        return

    success, msg = await game.remove_player(callback.from_user.id, callback.bot)
    await callback.answer(msg, show_alert=not success)


@router.callback_query(F.data == "bomb_start_now")
async def cb_bomb_start_now(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    game = active_bomb_games.get(chat_id)
    if not game:
        await callback.answer("Лобі не знайдено.", show_alert=True)
        return

    if callback.from_user.id != game.creator_id:
        await callback.answer("Лише творець лобі може розпочати гру достроково!", show_alert=True)
        return

    if len(game.players) < 1:
        await callback.answer("Потрібно мінімум 1 гравець!", show_alert=True)
        return

    await callback.answer("Розпалюємо полум'я дракона!")
    await game.start_game(callback.bot)


@router.callback_query(F.data == "bomb_freeze")
async def cb_bomb_freeze(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    game = active_bomb_games.get(chat_id)
    if not game:
        await callback.answer("Бій не знайдено.", show_alert=True)
        return

    success, msg = await game.use_freeze(callback.from_user.id, callback.bot)
    await callback.answer(msg, show_alert=not success)


@router.callback_query(F.data == "bomb_shield")
async def cb_bomb_shield(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    game = active_bomb_games.get(chat_id)
    if not game:
        await callback.answer("Бій не знайдено.", show_alert=True)
        return

    success, msg = await game.use_shield(callback.from_user.id, callback.bot)
    await callback.answer(msg, show_alert=not success)


@router.message(F.text, ~F.text.startswith("/"), ~F.text.startswith("!"), IsBombTurnFilter())
async def handle_bomb_words(message: types.Message):
    chat_id = message.chat.id
    game = active_bomb_games.get(chat_id)
    if game:
        await game.process_word(message.from_user.id, message.text, message.bot)
