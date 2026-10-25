from aiogram import Router, types, F
from aiogram.filters import Command, Filter
from games.pixel_hunt import PixelHuntGame, active_hunt_games, pick_random_hunt_item

router = Router(name="hunt_router")


class IsHuntActiveFilter(Filter):
    async def __call__(self, message: types.Message) -> bool:
        game = active_hunt_games.get(message.chat.id)
        return bool(game and not game.is_finished)


HUNT_TRIGGERS = {"!фільм", "фільм", "!вгадай фільм", "вгадай фільм", "!movie", "movie", "!hunt", "hunt", "!око", "око", "!зір", "зір"}

def is_hunt_trigger(text: str) -> bool:
    if not text:
        return False
    clean = text.lower().strip().split("@")[0].strip()
    return clean in HUNT_TRIGGERS


@router.message(Command("movie", "hunt", "фільм", "вгадай_фільм", "око"))
@router.message(F.text.func(is_hunt_trigger))
async def cmd_hunt(message: types.Message):
    chat_id = message.chat.id

    if chat_id in active_hunt_games:
        await message.answer("⚠️ У цьому чаті вже триває дешифровка Ока Дракона! Пишіть ваші відповіді вище.")
        return

    item_meta = pick_random_hunt_item()
    if not item_meta:
        await message.answer("❌ Набір образів для гри порожній або не знайдений!")
        return

    game = PixelHuntGame(chat_id=chat_id, item_meta=item_meta)
    active_hunt_games[chat_id] = game
    await game.start(message.bot)


@router.message(F.text, ~F.text.startswith("/"), ~F.text.startswith("!"), IsHuntActiveFilter())
async def handle_hunt_guess(message: types.Message):
    chat_id = message.chat.id
    game = active_hunt_games.get(chat_id)
    if not game or game.is_finished:
        return

    await game.check_guess(
        user_id=message.from_user.id if message.from_user else message.chat.id,
        username=message.from_user.username if message.from_user else "",
        first_name=message.from_user.first_name if message.from_user else "Володар",
        text=message.text,
        bot=message.bot
    )
