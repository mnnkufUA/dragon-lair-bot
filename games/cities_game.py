import asyncio
import html
import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Set
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import database
from config import (
    BASE_DIR,
    CITIES_TURN_SECONDS,
    CITIES_MIN_PLAYERS,
    CITIES_MAX_PLAYERS,
    CITIES_LOBBY_SECONDS
)

logger = logging.getLogger("DragonCities")

CITIES_PATH = BASE_DIR / "data" / "cities.json"
if not CITIES_PATH.exists():
    CITIES_PATH = BASE_DIR / "cities.json"
BLACKLIST_PATH = BASE_DIR / "data" / "cities_blacklist.json"
if not BLACKLIST_PATH.exists():
    BLACKLIST_PATH = BASE_DIR / "cities_blacklist.json"

with open(CITIES_PATH, "r", encoding="utf-8") as f:
    ALL_CITIES: Dict[str, str] = json.load(f)

RUSSIAN_BLACKLIST: Set[str] = set()
if BLACKLIST_PATH.exists():
    with open(BLACKLIST_PATH, "r", encoding="utf-8") as f:
        RUSSIAN_BLACKLIST = set(json.load(f))

# Global registry of active cities games: chat_id -> CitiesGame
active_cities_games: Dict[int, "CitiesGame"] = {}

INVALID_ENDINGS = set("ьъий'’` -")


def get_valid_last_letter(city_name: str) -> str:
    """Returns the last valid letter of a city name, skipping 'ь', 'ъ', 'и', apostrophes."""
    cleaned = re.sub(r"[^\w]", "", city_name.lower())
    for char in reversed(cleaned):
        if char not in INVALID_ENDINGS:
            return char
    return cleaned[-1] if cleaned else "а"


class Player:
    def __init__(self, user_id: int, username: str, first_name: str, team: str = "red"):
        self.user_id = user_id
        self.username = username or ""
        self.first_name = first_name or "Мандрівник"
        self.team = team  # "red" or "blue"
        self.compass_available = True  # +7 seconds lifeline
        self.strikes = 0

    @property
    def display_name(self) -> str:
        tag = "🔴 " if self.team == "red" else "🔵 "
        if self.username:
            return f"{tag}{html.escape('@' + self.username)}"
        return f"{tag}{html.escape(self.first_name)}"

    @property
    def plain_name(self) -> str:
        if self.username:
            return html.escape(f"@{self.username}")
        return html.escape(self.first_name)


class CitiesGame:
    def __init__(self, chat_id: int, creator: Player, bet: int = 0, turn_seconds: int = CITIES_TURN_SECONDS):
        self.chat_id = chat_id
        self.creator_id = creator.user_id
        self.bet = bet
        self.base_turn_seconds = max(8, min(turn_seconds, 45))
        self.turn_seconds = self.base_turn_seconds

        self.players: List[Player] = [creator]
        # Кто реально заплатил ставку (чтобы вернуть деньги даже выбывшим игрокам)
        self.paid_ids: Set[int] = {creator.user_id} if bet > 0 else set()
        self.initial_count: int = 1
        self.turn_deadline: float = 0
        self.state: str = "LOBBY"  # LOBBY, ACTIVE, FINISHED
        self.mode: str = "FFA"  # "FFA" (кожен сам за себе) or "TEAM" (командна битва) or "SOLO"
        self.message_id: Optional[int] = None

        self.current_player_idx: int = 0
        self.current_city: str = ""
        self.current_letter: str = "а"
        self.used_cities: Set[str] = set()
        self.round_count: int = 0

        self.lock = asyncio.Lock()
        self.timer_task: Optional[asyncio.Task] = None
        self.lobby_task: Optional[asyncio.Task] = None

        # Starter cities pool (famous international & Ukrainian cities)
        self.starter_cities = [
            "Київ", "Львів", "Одеса", "Харків", "Дніпро", "Варшава",
            "Париж", "Лондон", "Берлін", "Рим", "Мадрид", "Токіо",
            "Прага", "Відень", "Вашингтон", "Амстердам", "Стокгольм"
        ]

    @property
    def current_player(self) -> Optional[Player]:
        if not self.players or self.current_player_idx >= len(self.players):
            return None
        return self.players[self.current_player_idx]

    @property
    def total_pot(self) -> int:
        # В лобби банк растёт с каждым игроком; после старта он фиксирован
        count = len(self.players) if self.state == "LOBBY" else self.initial_count
        return self.bet * count

    async def _refund_all(self):
        """Возвращает ставки всем, кто их внёс."""
        if self.bet > 0:
            for uid in list(self.paid_ids):
                try:
                    await database.add_coins(uid, self.bet)
                except Exception as e:
                    logger.error(f"Refund failed for {uid}: {e}")
        self.paid_ids.clear()

    @property
    def red_players(self) -> List[Player]:
        return [p for p in self.players if p.team == "red"]

    @property
    def blue_players(self) -> List[Player]:
        return [p for p in self.players if p.team == "blue"]

    def get_lobby_markup(self) -> InlineKeyboardMarkup:
        s20 = "⚡ 20с " + ("✅" if self.base_turn_seconds == 20 else "")
        s45 = "⏱️ 45с " + ("✅" if self.base_turn_seconds == 45 else "")
        s60 = "⏳ 60с " + ("✅" if self.base_turn_seconds == 60 else "")

        buttons = [
            [
                InlineKeyboardButton(text="➕ Приєднатися", callback_data="cities_join"),
                InlineKeyboardButton(text="➖ Покинути", callback_data="cities_leave")
            ],
            [
                InlineKeyboardButton(text=s20, callback_data="cities_speed_20"),
                InlineKeyboardButton(text=s45, callback_data="cities_speed_45"),
                InlineKeyboardButton(text=s60, callback_data="cities_speed_60"),
            ]
        ]

        # Mode switcher button
        if self.mode == "FFA":
            buttons.append([
                InlineKeyboardButton(text="⚔️ Режим: Кожен сам за себе 🔄", callback_data="cities_mode_team")
            ])
        else:
            buttons.append([
                InlineKeyboardButton(text="🛡️ Режим: Командна битва 🔴 vs 🔵 🔄", callback_data="cities_mode_ffa")
            ])
            # Team choice buttons
            buttons.append([
                InlineKeyboardButton(text=f"🔴 За Вогонь ({len(self.red_players)})", callback_data="cities_team_red"),
                InlineKeyboardButton(text=f"🔵 За Лід ({len(self.blue_players)})", callback_data="cities_team_blue")
            ])

        # Speed buttons
        buttons.append([
            InlineKeyboardButton(text=s10, callback_data="cities_speed_10"),
            InlineKeyboardButton(text=s15, callback_data="cities_speed_15"),
            InlineKeyboardButton(text=s25, callback_data="cities_speed_25")
        ])

        # Start button
        if len(self.players) == 1:
            buttons.append([
                InlineKeyboardButton(text="👤 Почати Соло проти Дракона 🐉", callback_data="cities_start_now")
            ])
        else:
            buttons.append([
                InlineKeyboardButton(text="⚡ Розпочати подорож", callback_data="cities_start_now")
            ])

        return InlineKeyboardMarkup(inline_keyboard=buttons)

    def get_game_markup(self) -> InlineKeyboardMarkup:
        curr = self.current_player
        if not curr:
            return InlineKeyboardMarkup(inline_keyboard=[])

        buttons = []
        if curr.compass_available:
            buttons.append([
                InlineKeyboardButton(text="🧭 Компас Дракона (+7с)", callback_data="cities_compass")
            ])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    async def start_lobby(self, bot: Bot):
        lobby_text = self._build_lobby_text()
        msg = await bot.send_message(
            self.chat_id,
            lobby_text,
            reply_markup=self.get_lobby_markup(),
            parse_mode="HTML"
        )
        self.message_id = msg.message_id
        self.lobby_task = asyncio.create_task(self._lobby_countdown(bot))

    def _build_lobby_text(self) -> str:
        if self.mode == "TEAM":
            red_list = "\n".join(f"  • {p.plain_name}" for p in self.red_players) or "  <i>(порожньо)</i>"
            blue_list = "\n".join(f"  • {p.plain_name}" for p in self.blue_players) or "  <i>(порожньо)</i>"
            player_info = (
                f"🛡️ <b>Командний склад:</b>\n"
                f"🔴 <b>Команда Вогню ({len(self.red_players)}):</b>\n{red_list}\n\n"
                f"🔵 <b>Команда Льоду ({len(self.blue_players)}):</b>\n{blue_list}"
            )
        else:
            player_list = "\n".join(
                f"{i+1}. {p.plain_name}" + (" (Провідник)" if i == 0 else "")
                for i, p in enumerate(self.players)
            )
            player_info = f"👥 <b>Мандрівники ({len(self.players)}/{CITIES_MAX_PLAYERS}):</b>\n{player_list}"

        mode_name = "🛡️ Командна битва (🔴 vs 🔵)" if self.mode == "TEAM" else ("👤 Соло проти Дракона" if len(self.players) == 1 else "⚔️ Кожен сам за себе")

        return (
            f"🏛️ <b>МІСТА ДРАКОНА: ЗБІР МАНДРІВНИКІВ</b> 🏛️\n\n"
            f"Режим: <b>{mode_name}</b>\n"
            f"🪙 Ставка: <b>{self.bet} Монет</b>\n"
            f"🏆 Нагорода: <b>15–25 🪙</b> (або скарбниця ставок)\n"
            f"⏱️ Час на хід: <b>{self.base_turn_seconds} сек</b>\n\n"
            f"{player_info}\n\n"
            f"📜 <i>Правила гри:</i> гравець називає місто, наступний має назвати місто на <b>останню літеру</b> "
            f"(наприклад, «Київ» закінчується на «В» -> «Варшава»)! Якщо закінчується на «ь» чи апостроф, береться попередня літера.\n\n"
            f"⏳ Очікування ({CITIES_LOBBY_SECONDS}с) або тисніть «Розпочати»!"
        )

    async def _lobby_countdown(self, bot: Bot):
        try:
            await asyncio.sleep(CITIES_LOBBY_SECONDS)
            async with self.lock:
                if self.state == "LOBBY":
                    await self._start_game_locked(bot)
        except asyncio.CancelledError:
            pass

    async def set_mode(self, mode: str, bot: Bot):
        async with self.lock:
            if self.state != "LOBBY":
                return
            self.mode = mode
            if mode == "TEAM":
                # Automatically balance red/blue
                for i, p in enumerate(self.players):
                    p.team = "red" if i % 2 == 0 else "blue"
            await self._update_lobby_message(bot)

    async def set_team(self, user_id: int, team: str, bot: Bot) -> bool:
        async with self.lock:
            if self.state != "LOBBY":
                return False
            player = next((p for p in self.players if p.user_id == user_id), None)
            if not player:
                return False
            player.team = team
            await self._update_lobby_message(bot)
            return True

    async def set_speed(self, seconds: int, bot: Bot) -> bool:
        async with self.lock:
            if self.state != "LOBBY":
                return False
            self.base_turn_seconds = seconds
            self.turn_seconds = seconds
            await self._update_lobby_message(bot)
            return True

    async def add_player(self, player: Player, bot: Bot) -> tuple[bool, str]:
        async with self.lock:
            if self.state != "LOBBY":
                return False, "Подорож уже розпочалася!"
            if len(self.players) >= CITIES_MAX_PLAYERS:
                return False, "Караван переповнений!"
            if any(p.user_id == player.user_id for p in self.players):
                return False, "Ви вже у грі!"

            if self.bet > 0:
                has_funds = await database.try_deduct_coins(player.user_id, self.bet)
                if not has_funds:
                    bal = await database.get_balance(player.user_id)
                    return False, f"Недостатньо коштів! Твій баланс: {bal} 🪙"

            # Auto team assignment
            if self.mode == "TEAM":
                player.team = "blue" if len(self.red_players) > len(self.blue_players) else "red"

            if self.bet > 0:
                self.paid_ids.add(player.user_id)
            self.players.append(player)
            await self._update_lobby_message(bot)
            return True, f"Ви приєдналися до подорожі!"

    async def remove_player(self, user_id: int, bot: Bot) -> tuple[bool, str]:
        async with self.lock:
            if self.state != "LOBBY":
                return False, "Гра вже триває!"

            idx = next((i for i, p in enumerate(self.players) if p.user_id == user_id), None)
            if idx is None:
                return False, "Вас немає у грі."

            self.players.pop(idx)
            if self.bet > 0 and user_id in self.paid_ids:
                self.paid_ids.discard(user_id)
                await database.add_coins(user_id, self.bet)

            if not self.players:
                self.state = "FINISHED"
                if self.lobby_task and not self.lobby_task.done():
                    self.lobby_task.cancel()
                active_cities_games.pop(self.chat_id, None)
                if self.message_id:
                    try:
                        await bot.edit_message_text(
                            "❌ Усі залишили гру. Подорож скасовано.",
                            chat_id=self.chat_id,
                            message_id=self.message_id
                        )
                    except Exception:
                        pass
                return True, "Ви залишили гру."

            await self._update_lobby_message(bot)
            return True, "Ви залишили гру."

    async def _update_lobby_message(self, bot: Bot):
        if not self.message_id:
            return
        try:
            await bot.edit_message_text(
                self._build_lobby_text(),
                chat_id=self.chat_id,
                message_id=self.message_id,
                reply_markup=self.get_lobby_markup(),
                parse_mode="HTML"
            )
        except Exception:
            pass

    async def start_game(self, bot: Bot) -> tuple[bool, str]:
        """Публичный запуск (кнопка «Розпочати»). Берёт блокировку, чтобы не столкнуться с таймером лобби."""
        async with self.lock:
            return await self._start_game_locked(bot)

    async def _start_game_locked(self, bot: Bot) -> tuple[bool, str]:
        if self.state != "LOBBY":
            return False, "Гру вже розпочато."

        if not self.players:
            self.state = "FINISHED"
            active_cities_games.pop(self.chat_id, None)
            return False, "Немає гравців!"

        # Сам себя таймер лобби отменять не должен (иначе первый ход не отправится)
        if self.lobby_task and not self.lobby_task.done() and self.lobby_task is not asyncio.current_task():
            self.lobby_task.cancel()

        # Соло против дракона — без ставок: возвращаем монеты, иначе они бы просто сгорели
        if len(self.players) == 1 and self.bet > 0:
            await self._refund_all()
            self.bet = 0

        self.initial_count = len(self.players)
        self.state = "ACTIVE"
        self.turn_seconds = self.base_turn_seconds

        # Solo Mode vs Bot
        if len(self.players) == 1:
            self.mode = "SOLO"
            self.current_player_idx = 0
            start_desc = f"🐉 <b>СОЛО-БИТВА ПРОТИ ДРАКОНА!</b>\nГравець: {self.players[0].plain_name} кидає виклик магічній пам'яті Дракона!"
        elif self.mode == "TEAM":
            # Ensure balanced teams
            if not self.red_players or not self.blue_players:
                # Distribute evenly
                for i, p in enumerate(self.players):
                    p.team = "red" if i % 2 == 0 else "blue"

            # Create alternating turn list: red, blue, red, blue...
            reds = list(self.red_players)
            blues = list(self.blue_players)
            random.shuffle(reds)
            random.shuffle(blues)
            interleaved = []
            max_len = max(len(reds), len(blues))
            for i in range(max_len):
                if i < len(reds):
                    interleaved.append(reds[i])
                if i < len(blues):
                    interleaved.append(blues[i])
            self.players = interleaved
            self.current_player_idx = 0
            start_desc = f"🛡️ <b>КОМАНДНА БИТВА РОЗПОЧАЛАСЯ!</b>\n🔴 Команда Вогню ({len(self.red_players)}) проти 🔵 Команди Льоду ({len(self.blue_players)})!"
        else:
            # Free For All
            random.shuffle(self.players)
            self.current_player_idx = 0
            start_desc = f"⚔️ <b>ПОДОРОЖ МІСТАМИ РОЗПОЧАЛАСЯ!</b>\nУсі гравці змагаються кожен сам за себе!"

        # Pick random starting city
        starter = random.choice(self.starter_cities)
        starter_key = starter.lower()
        self.current_city = starter
        self.used_cities.add(starter_key)
        self.current_letter = get_valid_last_letter(starter)
        self.round_count = 1

        start_text = (
            f"🗺️ {start_desc}\n\n"
            f"🐉 Дракон задає перше місто: <b>{html.escape(starter)}</b>!\n"
            f"👉 Наступне місто має починатися на літеру: <b>[ {self.current_letter.upper()} ]</b>"
        )
        try:
            await bot.send_message(self.chat_id, start_text, parse_mode="HTML")
        except Exception:
            pass

        await self._start_turn(bot)
        return True, "Подорож розпочато!"

    async def _start_turn(self, bot: Bot):
        curr_task = asyncio.current_task()
        if self.timer_task and self.timer_task is not curr_task and not self.timer_task.done():
            self.timer_task.cancel()

        curr = self.current_player
        if not curr:
            return

        curr.strikes = 0
        self.turn_deadline = time.time() + self.turn_seconds

        turn_title = f"Хід {curr.display_name}!" if self.mode == "TEAM" else f"Хід {curr.plain_name}!"

        turn_text = (
            f"🏛️ <b>{turn_title}</b>\n\n"
            f"Попереднє місто: <b>{html.escape(self.current_city)}</b>\n"
            f"Твоя літера: <b>[ {self.current_letter.upper()} ]</b>\n"
            f"⏳ Таймер: <b>{self.turn_seconds} секунд</b>\n\n"
            f"✍️ Напиши місто, яке <b>починається на літеру {self.current_letter.upper()}</b>!"
        )

        try:
            msg = await bot.send_message(
                self.chat_id,
                turn_text,
                reply_markup=self.get_game_markup(),
                parse_mode="HTML"
            )
            self.message_id = msg.message_id
        except Exception:
            pass

        self.timer_task = asyncio.create_task(self._turn_timeout_watcher(bot, self.current_player_idx))

    async def _turn_timeout_watcher(self, bot: Bot, player_idx: int):
        try:
            await asyncio.sleep(max(0.0, self.turn_deadline - time.time()))
            async with self.lock:
                if self.state == "ACTIVE" and self.current_player_idx == player_idx:
                    await self._eliminate_player(bot, reason="Час вичерпано! Не встиг назвати місто.")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in cities _turn_timeout_watcher: {e}", exc_info=True)

    async def process_word(self, user_id: int, word: str, bot: Bot) -> bool:
        async with self.lock:
            if self.state != "ACTIVE":
                return False

            curr = self.current_player
            if not curr or curr.user_id != user_id:
                return False

            raw_clean = word.strip().lower().replace("’", "'").replace("`", "'").replace("‘", "'")
            clean_word = re.sub(r"^[^\w']+|[^\w']+$", "", raw_clean)
            if not clean_word:
                return False

            # Check if Russian / Belarusian city was entered
            if clean_word in RUSSIAN_BLACKLIST or clean_word.replace("'", "") in RUSSIAN_BLACKLIST:
                await bot.send_message(
                    self.chat_id,
                    f"❌ {curr.plain_name}, це місто не приймається у грі! "
                    f"Назви інше місто на літеру <b>[{self.current_letter.upper()}]</b>.",
                    parse_mode="HTML"
                )
                return True

            # Check starting letter
            req_letter = self.current_letter.lower()
            if not clean_word.startswith(req_letter):
                curr.strikes += 1
                if curr.strikes >= 3:
                    await self._eliminate_player(bot, reason=f"3 помилкові спроби поспіль (місто не на '{self.current_letter.upper()}').")
                else:
                    await bot.send_message(
                        self.chat_id,
                        f"❌ {curr.plain_name}, місто має починатися на літеру <b>[{self.current_letter.upper()}]</b>! (Спроба {curr.strikes}/3)",
                        parse_mode="HTML"
                    )
                return True

            # Check if city exists in database
            city_no_apos = clean_word.replace("'", "")
            matched_key = None
            if clean_word in ALL_CITIES:
                matched_key = clean_word
            elif city_no_apos in ALL_CITIES:
                matched_key = city_no_apos

            if not matched_key:
                curr.strikes += 1
                if curr.strikes >= 3:
                    await self._eliminate_player(bot, reason="3 невідомі міста поспіль.")
                else:
                    await bot.send_message(
                        self.chat_id,
                        f"🌍 {curr.plain_name}, місто «{html.escape(word.strip())}» не знайдено у мапі світу! (Спроба {curr.strikes}/3)",
                        parse_mode="HTML"
                    )
                return True

            # Check if city was already used
            if matched_key in self.used_cities:
                await bot.send_message(
                    self.chat_id,
                    f"⚠️ Місто <b>{html.escape(ALL_CITIES[matched_key])}</b> вже було названо в цій грі! Назвіть інше місто на букву <b>[{self.current_letter.upper()}]</b>.",
                    parse_mode="HTML"
                )
                return True

            # Valid city accepted!
            display_title = ALL_CITIES[matched_key]
            self.used_cities.add(matched_key)
            next_letter = get_valid_last_letter(display_title)
            self.current_city = display_title
            self.current_letter = next_letter
            self.round_count += 1

            # Progression based on game mode
            if self.mode == "SOLO":
                await self._dragon_solo_turn(curr, display_title, bot)
            else:
                next_idx = (self.current_player_idx + 1) % len(self.players)
                next_player = self.players[next_idx]
                self.current_player_idx = next_idx
                self.turn_seconds = self.base_turn_seconds

                player_name = curr.display_name if self.mode == "TEAM" else curr.plain_name
                next_name = next_player.display_name if self.mode == "TEAM" else next_player.plain_name

                await bot.send_message(
                    self.chat_id,
                    f"✅ {player_name} назвав: <b>{html.escape(display_title)}</b>! (на кінці «{next_letter.upper()}»)\n"
                    f"👉 {next_name}: місто на літеру <b>[ {self.current_letter.upper()} ]</b>!",
                    parse_mode="HTML"
                )
                await self._start_turn(bot)

            return True

    async def _dragon_solo_turn(self, player: Player, player_city: str, bot: Bot):
        req = self.current_letter.lower()
        candidates = [
            k for k in ALL_CITIES.keys() 
            if k.startswith(req) and k not in self.used_cities
        ]

        if candidates:
            chosen_key = random.choice(candidates)
            dragon_city = ALL_CITIES[chosen_key]
            self.used_cities.add(chosen_key)
            self.current_city = dragon_city
            self.current_letter = get_valid_last_letter(dragon_city)

            await bot.send_message(
                self.chat_id,
                f"✅ {player.plain_name}: <b>{html.escape(player_city)}</b>!\n"
                f"🐉 Дракон відповідає: <b>{html.escape(dragon_city)}</b>!\n"
                f"👉 Твоя нова літера: <b>[ {self.current_letter.upper()} ]</b> (Раунд {self.round_count}/8)",
                parse_mode="HTML"
            )

            # Victory condition in solo mode (8 rounds)
            if self.round_count >= 8:
                await self._finish_solo_victory(player, bot)
                return

            self.turn_seconds = self.base_turn_seconds
            await self._start_turn(bot)
        else:
            await bot.send_message(
                self.chat_id,
                f"🤯 Дракон не зміг знайти місто на літеру <b>[{req.upper()}]</b> і схиляє голову перед тобою!",
                parse_mode="HTML"
            )
            await self._finish_solo_victory(player, bot)

    async def _finish_solo_victory(self, player: Player, bot: Bot):
        self.state = "FINISHED"
        active_cities_games.pop(self.chat_id, None)
        curr_task = asyncio.current_task()
        if self.timer_task and self.timer_task is not curr_task and not self.timer_task.done():
            self.timer_task.cancel()

        prize = random.randint(15, 25)
        food = 0
        egg = 0
        try:
            res = await database.record_cities_win(player.user_id, prize)
            if isinstance(res, dict):
                food = res.get("food", 0)
                egg = res.get("egg", 0)
        except Exception as e:
            logger.error(f"Error recording cities win: {e}")

        win_text = (
            f"👑 <b>ТРИУМФ У СОЛО-ПОДОРОЖІ З ДРАКОНОМ!</b> 👑\n\n"
            f"🏆 {player.plain_name} переміг стародавнього Дракона у знанні географії!\n"
            f"💰 Винагорода: <b>+{prize} 🪙 Монет</b>\n"
        )
        if food > 0:
            win_text += "🍖 <b>+1 Смаколик</b> (випав з шансом 20%)!\n"
        if egg > 0:
            win_text += (
                "🥚 <b>ВАМ ВИПАЛО ДРАКОНЯЧЕ ЯЙЦЕ (10% шанс)!</b>\n"
                "Запустіть <code>/roulette</code> або <code>!рулетка</code>, щоб висидіти нового дракона!\n"
            )
        win_text += "\n🐉 Відкрити Лігво: <code>/lair</code> або <code>!моєлігво</code>"
        await bot.send_message(self.chat_id, win_text, parse_mode="HTML")

    async def use_compass(self, user_id: int, bot: Bot) -> tuple[bool, str]:
        async with self.lock:
            if self.state != "ACTIVE":
                return False, "Гра не активна."
            curr = self.current_player
            if not curr or curr.user_id != user_id:
                return False, "Зараз не твій хід!"
            if not curr.compass_available:
                return False, "Компас уже використано!"

            curr.compass_available = False
            self.turn_seconds += 7
            self.turn_deadline += 7  # ровно +7 секунд к тому, что осталось

            curr_task = asyncio.current_task()
            if self.timer_task and self.timer_task is not curr_task and not self.timer_task.done():
                self.timer_task.cancel()
            self.timer_task = asyncio.create_task(self._turn_timeout_watcher(bot, self.current_player_idx))

            await bot.send_message(
                self.chat_id,
                f"🧭 {curr.plain_name} застосував <b>Компас Дракона</b>! +7 секунд на роздуми!",
                parse_mode="HTML"
            )
            return True, "Компас активовано!"

    async def force_stop(self, bot: Bot, reason: str = "Гру зупинено."):
        async with self.lock:
            if self.state == "FINISHED":
                return
            self.state = "FINISHED"
            if self.lobby_task and not self.lobby_task.done():
                self.lobby_task.cancel()
            if self.timer_task and not self.timer_task.done():
                self.timer_task.cancel()

            active_cities_games.pop(self.chat_id, None)
            await self._refund_all()

            try:
                await bot.send_message(
                    self.chat_id,
                    f"🛑 <b>ГРУ «МІСТА ДРАКОНА» ЗУПИНЕНО!</b>\n{html.escape(reason)}\n<i>(Усі ставки повернено)</i>",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    async def _eliminate_player(self, bot: Bot, reason: str):
        curr_task = asyncio.current_task()
        if self.timer_task and self.timer_task is not curr_task and not self.timer_task.done():
            self.timer_task.cancel()

        if not self.players:
            self.state = "FINISHED"
            active_cities_games.pop(self.chat_id, None)
            return

        if self.current_player_idx >= len(self.players):
            self.current_player_idx = 0

        eliminated = self.players.pop(self.current_player_idx)

        # Solo mode loss
        if self.mode == "SOLO":
            self.state = "FINISHED"
            active_cities_games.pop(self.chat_id, None)
            loss_text = (
                f"🏜️ {eliminated.plain_name} збився з дороги! {reason}\n"
                f"🐉 Дракон виграв цю подорож, але ти назвав {self.round_count} міст! Спробуй ще раз!"
            )
            await bot.send_message(self.chat_id, loss_text, parse_mode="HTML")
            return

        # Multiplayer elimination message
        name_str = eliminated.display_name if self.mode == "TEAM" else eliminated.plain_name
        elim_text = (
            f"🏜️ {name_str} збився з каравану і вибуває!\n"
            f"Причина: {reason}\n"
            f"<i>(Жодних штрафів чи мутів — спілкуйся вільно!)</i>"
        )
        try:
            await bot.send_message(self.chat_id, elim_text, parse_mode="HTML")
        except Exception:
            pass

        # Check Team Victory Condition
        if self.mode == "TEAM":
            reds_alive = self.red_players
            blues_alive = self.blue_players

            if not reds_alive or not blues_alive:
                self.state = "FINISHED"
                active_cities_games.pop(self.chat_id, None)

                winning_team_name = "🔵 Команда Льоду" if blues_alive else "🔴 Команда Вогню"
                winners = blues_alive if blues_alive else reds_alive
                share_prize = (self.total_pot // len(winners)) if (self.total_pot > 0 and winners) else 20

                for w in winners:
                    try:
                        await database.record_cities_win(w.user_id, share_prize)
                    except Exception:
                        pass

                winner_names = ", ".join(w.plain_name for w in winners)
                team_win_text = (
                    f"👑 <b>ПЕРЕМОГА У КОМАНДНІЙ БИТВІ МІСТ!</b> 👑\n\n"
                    f"🏆 Тріумфує <b>{winning_team_name}</b>!\n"
                    f"Герої команди: {winner_names}\n"
                    f"💰 Винагорода: <b>+{share_prize} 🪙 Монет</b> кожному воїну!\n"
                    f"Чат вільний для нових пригод!"
                )
                try:
                    await bot.send_message(self.chat_id, team_win_text, parse_mode="HTML")
                except Exception:
                    pass
                return

        # FFA Victory Condition
        if len(self.players) <= 1:
            self.state = "FINISHED"
            active_cities_games.pop(self.chat_id, None)

            if len(self.players) == 1:
                winner = self.players[0]
                prize = self.total_pot if self.total_pot > 0 else random.randint(15, 25)

                food = 0
                egg = 0
                try:
                    res = await database.record_cities_win(winner.user_id, prize)
                    if isinstance(res, dict):
                        food = res.get("food", 0)
                        egg = res.get("egg", 0)
                except Exception as e:
                    logger.error(f"Error in cities win record: {e}")

                win_text = (
                    f"👑 <b>ПЕРЕМОГА У «МІСТАХ ДРАКОНА»!</b> 👑\n\n"
                    f"🏆 Мандрівник {winner.plain_name} став єдиним знавцем мапи!\n"
                    f"💰 Винагорода: <b>+{prize} 🪙 Монет</b>\n"
                )
                if food > 0:
                    win_text += "🍖 <b>+1 Смаколик</b> (випав з шансом 20%)!\n"
                if egg > 0:
                    win_text += (
                        "🥚 <b>ВАМ ВИПАЛО ДРАКОНЯЧЕ ЯЙЦЕ (10% шанс)!</b>\n"
                        "Запустіть <code>/roulette</code> або <code>!рулетка</code>, щоб висидіти нового дракона!\n"
                    )
                win_text += "\n🐉 Відкрити Лігво: <code>/lair</code> або <code>!моєлігво</code>"
                try:
                    await bot.send_message(self.chat_id, win_text, parse_mode="HTML")
                except Exception:
                    pass
        else:
            if self.current_player_idx >= len(self.players):
                self.current_player_idx = 0
            self.turn_seconds = self.base_turn_seconds
            await self._start_turn(bot)