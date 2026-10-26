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
    BOMB_TURN_SECONDS,
    BOMB_MIN_PLAYERS,
    BOMB_MAX_PLAYERS,
    BOMB_LOBBY_SECONDS
)

logger = logging.getLogger("DragonCore")

# Load Ukrainian words and syllables (with multi-path fallback)
WORDS_PATH = BASE_DIR / "data" / "words_ua.json"
if not WORDS_PATH.exists():
    WORDS_PATH = BASE_DIR / "words_ua.json"
SYLLABLES_PATH = BASE_DIR / "data" / "syllables_ua.json"
if not SYLLABLES_PATH.exists():
    SYLLABLES_PATH = BASE_DIR / "syllables_ua.json"

with open(WORDS_PATH, "r", encoding="utf-8") as f:
    ALL_WORDS: Set[str] = set(json.load(f))

with open(SYLLABLES_PATH, "r", encoding="utf-8") as f:
    ALL_SYLLABLES: List[str] = json.load(f)

# Global registry of active bomb games: chat_id -> BombGame
active_bomb_games: Dict[int, "BombGame"] = {}


class Player:
    def __init__(self, user_id: int, username: str, first_name: str):
        self.user_id = user_id
        self.username = username or ""
        self.first_name = first_name or "Мисливець"
        self.shield_available = True
        self.freeze_available = True
        self.strikes = 0

    @property
    def display_name(self) -> str:
        if self.username:
            return html.escape(f"@{self.username}")
        return html.escape(self.first_name)


class BombGame:
    @staticmethod
    def is_valid_word(word: str) -> bool:
        if not word:
            return False
        w = word.lower().strip()
        if w in ALL_WORDS:
            return True
        # Adverbs from adjectives (-о / -е -> -ий, -ій)
        if w.endswith('о') or w.endswith('е'):
            if (w[:-1] + 'ий') in ALL_WORDS or (w[:-1] + 'ій') in ALL_WORDS:
                return True
        # Feminine accusative (-у / -ю -> -а / -я)
        if w.endswith('у') and (w[:-1] + 'а') in ALL_WORDS:
            return True
        if w.endswith('ю') and (w[:-1] + 'я') in ALL_WORDS:
            return True
        # Instrumental (-ом / -ем)
        if (w.endswith('ом') or w.endswith('ем')) and w[:-2] in ALL_WORDS:
            return True
        # Plural / Genitive (-и / -і)
        if w.endswith('и') and ((w[:-1] + 'а') in ALL_WORDS or w[:-1] in ALL_WORDS):
            return True
        if w.endswith('і') and ((w[:-1] + 'а') in ALL_WORDS or (w[:-1] + 'я') in ALL_WORDS or w[:-1] in ALL_WORDS):
            return True
        # Masculine genitive / accusative (-а / -у)
        if len(w) >= 4 and (w.endswith('а') or w.endswith('у')) and w[:-1] in ALL_WORDS:
            return True
        return False

    def __init__(self, chat_id: int, creator: Player, bet: int = 0, turn_seconds: int = BOMB_TURN_SECONDS):
        self.chat_id = chat_id
        self.creator_id = creator.user_id
        self.bet = bet
        self.base_turn_seconds = max(5, min(turn_seconds, 60))
        self.turn_seconds = self.base_turn_seconds

        self.players: List[Player] = [creator]
        # Кто реально заплатил ставку (чтобы вернуть деньги даже выбывшим игрокам)
        self.paid_ids: Set[int] = {creator.user_id} if bet > 0 else set()
        self.initial_count: int = 1
        self.state: str = "LOBBY"  # LOBBY, ACTIVE, FINISHED
        self.message_id: Optional[int] = None

        self.current_player_idx: int = 0
        self.previous_player_idx: Optional[int] = None
        self.current_syllable: str = ""
        self.used_words: Set[str] = set()

        self.turn_deadline: float = 0
        self.core_turns_left: int = random.randint(4, 9)  # Random turns before dragon flame burst
        self.lock = asyncio.Lock()
        self.timer_task: Optional[asyncio.Task] = None
        self.lobby_task: Optional[asyncio.Task] = None

    @property
    def current_player(self) -> Optional[Player]:
        if not self.players or self.current_player_idx >= len(self.players):
            return None
        return self.players[self.current_player_idx]

    @property
    def total_pot(self) -> int:
        # В лобби банк растёт с каждым игроком; после старта он фиксирован
        # (раньше считался по оставшимся игрокам, и победитель получал только свою ставку)
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

    def get_lobby_markup(self) -> InlineKeyboardMarkup:
        s8 = "⚡ 8с " + ("✅" if self.base_turn_seconds == 8 else "")
        s12 = "⏱️ 12с " + ("✅" if self.base_turn_seconds == 12 else "")
        s18 = "🐢 18с " + ("✅" if self.base_turn_seconds == 18 else "")

        buttons = [
            [
                InlineKeyboardButton(text="➕ Приєднатися", callback_data="bomb_join"),
                InlineKeyboardButton(text="➖ Покинути", callback_data="bomb_leave")
            ],
            [
                InlineKeyboardButton(text=s8, callback_data="bomb_speed_8"),
                InlineKeyboardButton(text=s12, callback_data="bomb_speed_12"),
                InlineKeyboardButton(text=s18, callback_data="bomb_speed_18"),
            ],
            [
                InlineKeyboardButton(text="⚡ Розпочати бій", callback_data="bomb_start_now")
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    def get_game_markup(self) -> InlineKeyboardMarkup:
        curr = self.current_player
        if not curr:
            return InlineKeyboardMarkup(inline_keyboard=[])

        buttons = []
        row = []
        if curr.freeze_available:
            row.append(InlineKeyboardButton(text="❄️ Крижана луска (+5с)", callback_data="bomb_freeze"))
        if curr.shield_available and len(self.players) > 1:
            row.append(InlineKeyboardButton(text="🛡️ Відбиття полум'я", callback_data="bomb_shield"))
        if row:
            buttons.append(row)
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    def pick_new_syllable(self) -> str:
        shuffled = random.sample(ALL_SYLLABLES, min(100, len(ALL_SYLLABLES)))
        for syl in shuffled:
            syl_low = syl.lower()
            count = 0
            for w in ALL_WORDS:
                if syl_low in w and w not in self.used_words:
                    count += 1
                    if count >= 3:
                        return syl
        return random.choice(ALL_SYLLABLES)

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
        player_list = "\n".join(
            f"{i+1}. {p.display_name}" + (" (Повелитель лобі)" if i == 0 else "")
            for i, p in enumerate(self.players)
        )
        return (
            f"🐉 <b>ПОЛУМ'Я ДРАКОНА: ЗБІР ОРДЕНУ</b> 🐉\n\n"
            f"🪙 Ставка: <b>{self.bet} Монет</b>\n"
            f"Скарбниця раунду: <b>{self.total_pot} 🪙</b>\n"
            f"⏱️ Час на відповідь: <b>{self.base_turn_seconds} сек</b>\n\n"
            f"👥 Учасники ({len(self.players)}/{BOMB_MAX_PLAYERS}):\n"
            f"{player_list}\n\n"
            f"⏳ Очікування воїнів ({BOMB_LOBBY_SECONDS}с) або запускайте кнопкою!"
        )

    async def _lobby_countdown(self, bot: Bot):
        try:
            await asyncio.sleep(BOMB_LOBBY_SECONDS)
            async with self.lock:
                if self.state == "LOBBY":
                    await self._start_game_locked(bot)
        except asyncio.CancelledError:
            pass

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
                return False, "Бій уже розпочався!"
            if len(self.players) >= BOMB_MAX_PLAYERS:
                return False, "Лобі вже переповнене!"
            if any(p.user_id == player.user_id for p in self.players):
                return False, "Ви вже знаходитесь у лобі!"

            if self.bet > 0:
                has_balance = await database.try_deduct_coins(player.user_id, self.bet)
                if not has_balance:
                    return False, f"Недостатньо 🪙 Монет для ставки ({self.bet})!"

            if self.bet > 0:
                self.paid_ids.add(player.user_id)
            self.players.append(player)
            await self._update_lobby_message(bot)
            return True, "Ви успішно приєдналися до Ордену!"

    async def remove_player(self, user_id: int, bot: Bot) -> tuple[bool, str]:
        async with self.lock:
            if self.state != "LOBBY":
                return False, "Не можна вийти під час активного бою!"
            target = next((p for p in self.players if p.user_id == user_id), None)
            if not target:
                return False, "Вас немає у лобі!"

            self.players.remove(target)
            if self.bet > 0 and user_id in self.paid_ids:
                self.paid_ids.discard(user_id)
                await database.add_coins(user_id, self.bet)

            if not self.players:
                self.state = "FINISHED"
                if self.lobby_task and not self.lobby_task.done():
                    self.lobby_task.cancel()
                active_bomb_games.pop(self.chat_id, None)
                if self.message_id:
                    try:
                        await bot.edit_message_text(
                            "❌ Усі покинули лобі. Бій скасовано.",
                            chat_id=self.chat_id,
                            message_id=self.message_id
                        )
                    except Exception:
                        pass
                return True, "Ви залишили лобі. Гру скасовано."

            await self._update_lobby_message(bot)
            return True, "Ви залишили лобі."

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

        # Со ставкой нужно минимум 2 игрока, иначе единственный игрок просто потеряет монеты
        need_players = max(BOMB_MIN_PLAYERS, 2 if self.bet > 0 else 1)
        if len(self.players) < need_players:
            await self._refund_all()
            self.state = "FINISHED"
            active_bomb_games.pop(self.chat_id, None)
            if self.message_id:
                try:
                    await bot.edit_message_text(
                        f"⚠️ Недостатньо воїнів для початку (потрібно мінімум {need_players}). Ставки повернуто.",
                        chat_id=self.chat_id,
                        message_id=self.message_id
                    )
                except Exception:
                    pass
            return False, "Недостатньо гравців!"

        if self.lobby_task and not self.lobby_task.done() and self.lobby_task is not asyncio.current_task():
            self.lobby_task.cancel()

        self.initial_count = len(self.players)
        self.state = "ACTIVE"
        random.shuffle(self.players)
        self.current_player_idx = 0
        self.turn_seconds = self.base_turn_seconds
        self.current_syllable = self.pick_new_syllable()

        await self._start_turn(bot, initial=True)
        return True, "Полум'я розпалено!"

    async def _start_turn(self, bot: Bot, initial: bool = False):
        curr_task = asyncio.current_task()
        if self.timer_task and self.timer_task is not curr_task and not self.timer_task.done():
            self.timer_task.cancel()

        curr = self.current_player
        if not curr:
            return

        curr.strikes = 0
        self.turn_deadline = time.time() + self.turn_seconds

        heat_levels = ["🟩 Тління (Дракон дрімає)", "🟨 Розпал (Дракон злиться)", "🟧 Жар (Критично)", "🟥 СПАЛАХ (Небезпека вибуху!)"]
        heat_idx = min(len(heat_levels) - 1, max(0, 4 - self.core_turns_left))
        heat_status = heat_levels[heat_idx]

        turn_text = (
            f"🔥 <b>СЕРЦЕ ДРАКОНА В РУКАХ {curr.display_name}!</b> 🔥\n\n"
            f"Склад: <b>[ {self.current_syllable.upper()} ]</b>\n"
            f"🌋 Стан полум'я: {heat_status}\n"
            f"⏳ Таймер: <b>{self.turn_seconds} секунд</b>\n\n"
            f"✍️ Напиши в чат українське слово з цим складом!"
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
                    await self._eliminate_player(bot, reason="Час витік! Дракон спопелив зволікача.")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in _turn_timeout_watcher: {e}", exc_info=True)

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

            syllable_clean = self.current_syllable.lower()
            word_no_apostrophe = clean_word.replace("'", "")
            syl_no_apostrophe = syllable_clean.replace("'", "")

            # Validate syllable presence
            if syllable_clean not in clean_word and syl_no_apostrophe not in word_no_apostrophe:
                curr.strikes += 1
                if curr.strikes >= 3:
                    await self._eliminate_player(bot, reason=f"3 хибні спроби поспіль (немає складу '{self.current_syllable.upper()}').")
                else:
                    await bot.send_message(
                        self.chat_id,
                        f"❌ {curr.display_name}, у слові немає складу <b>[{self.current_syllable.upper()}]</b>! (Спроба {curr.strikes}/3)",
                        parse_mode="HTML"
                    )
                return True

            # Validate word existence in Ukrainian dictionary (check both forms + forms/adverbs)
            if not self.is_valid_word(clean_word) and not self.is_valid_word(word_no_apostrophe):
                curr.strikes += 1
                if curr.strikes >= 3:
                    await self._eliminate_player(bot, reason="3 слова поспіль не знайдено у сувої Дракона.")
                else:
                    await bot.send_message(
                        self.chat_id,
                        f"🤔 {curr.display_name}, слово «{html.escape(clean_word)}» відсутнє у словнику Дракона! (Спроба {curr.strikes}/3)",
                        parse_mode="HTML"
                    )
                return True

            # Validate word not already used
            if clean_word in self.used_words or word_no_apostrophe in self.used_words:
                await bot.send_message(
                    self.chat_id,
                    f"⚠️ Слово «{html.escape(clean_word)}» вже звучало у цій битві! Назви інше."
                )
                return True

            # Success!
            self.used_words.add(clean_word)
            self.used_words.add(word_no_apostrophe)
            self.core_turns_left -= 1

            # Solo mode vs Dragon: 5 rounds to win and claim rewards!
            if len(self.players) == 1:
                self.solo_rounds = getattr(self, "solo_rounds", 0) + 1
                if self.solo_rounds >= 5:
                    await self._finish_solo_victory(curr, bot)
                    return True

                await bot.send_message(
                    self.chat_id,
                    f"✅ {curr.display_name} виголосив «{html.escape(clean_word)}»! (Раунд {self.solo_rounds}/5)\n"
                    f"🔥 Полум'я Дракона приборкується! Назви ще {5 - self.solo_rounds} слів для тріумфу!"
                )
                self.turn_seconds = self.base_turn_seconds
                self.current_syllable = self.pick_new_syllable()
                await self._start_turn(bot)
                return True

            # Advance to next player
            self.previous_player_idx = self.current_player_idx
            self.current_player_idx = (self.current_player_idx + 1) % len(self.players)
            self.turn_seconds = self.base_turn_seconds
            self.current_syllable = self.pick_new_syllable()

            await bot.send_message(
                self.chat_id,
                f"✅ {curr.display_name} виголосив «{html.escape(clean_word)}»! Серце Дракона летить далі 🚀"
            )
            await self._start_turn(bot)
            return True


    async def _finish_solo_victory(self, winner: Player, bot: Bot):
        self.state = "FINISHED"
        active_bomb_games.pop(self.chat_id, None)
        curr_task = asyncio.current_task()
        if self.timer_task and self.timer_task is not curr_task and not self.timer_task.done():
            self.timer_task.cancel()

        prize = self.total_pot if self.total_pot > 0 else random.randint(15, 25)
        food = 0
        egg = 0
        try:
            res = await database.award_game_win(winner.user_id, coins=prize, username=winner.username, first_name=winner.first_name)
            food = res.get("food", 0)
            egg = res.get("egg", 0)
        except Exception as e:
            logger.error(f"Failed to award bomb solo win in db: {e}")

        victory_text = (
            f"👑 <b>ТРИУМФ У ГРІ «БОМБА» (СОЛО-БІЙ З ДРАКОНОМ)!</b> 👑\n\n"
            f"🎉 Вітаємо володаря слів {winner.display_name}!\n"
            f"Ти успішно приборкав Полум'я Дракона і витримав 5 раундів підряд!\n\n"
            f"🏆 Нагорода: <b>+{prize} 🪙 Монет</b> зачислено у твій інвентар!\n"
        )
        if food > 0:
            victory_text += "🍖 <b>+1 Смаколик</b> (випав з шансом 20%)!\n"
        if egg > 0:
            victory_text += (
                "🥚 <b>ВАМ ВИПАЛО ДРАКОНЯЧЕ ЯЙЦЕ (10% шанс)!</b>\n"
                "Запустіть <code>/roulette</code> або <code>!рулетка</code>, щоб висидіти нового дракона!\n"
            )
        victory_text += "\n🐉 Відкрити Лігво: <code>/lair</code> або <code>!моєлігво</code>"
        try:
            await bot.send_message(self.chat_id, victory_text, parse_mode="HTML")
        except Exception:
            try:
                await bot.send_message(self.chat_id, victory_text)
            except Exception:
                pass

    async def use_freeze(self, user_id: int, bot: Bot) -> tuple[bool, str]:
        async with self.lock:
            if self.state != "ACTIVE":
                return False, "Бій не активний."
            curr = self.current_player
            if not curr or curr.user_id != user_id:
                return False, "Зараз не твій хід!"
            if not curr.freeze_available:
                return False, "Ти вже використав Крижану луску!"

            curr.freeze_available = False
            self.turn_seconds += 5
            self.turn_deadline += 5  # ровно +5 секунд к тому, что осталось

            curr_task = asyncio.current_task()
            if self.timer_task and self.timer_task is not curr_task and not self.timer_task.done():
                self.timer_task.cancel()
            self.timer_task = asyncio.create_task(self._turn_timeout_watcher(bot, self.current_player_idx))

            await bot.send_message(
                self.chat_id,
                f"❄️ {curr.display_name} задіяв <b>Крижану луску</b>! +5 секунд до витримки!",
                parse_mode="HTML"
            )
            return True, "Луска активована!"

    async def use_shield(self, user_id: int, bot: Bot) -> tuple[bool, str]:
        async with self.lock:
            if self.state != "ACTIVE":
                return False, "Бій не активний."
            curr = self.current_player
            if not curr or curr.user_id != user_id:
                return False, "Зараз не твій хід!"
            if not curr.shield_available:
                return False, "Ти вже використав Відбиття!"
            if len(self.players) <= 1:
                return False, "Нікому відбивати!"

            curr.shield_available = False

            target_idx = self.previous_player_idx if (self.previous_player_idx is not None and self.previous_player_idx < len(self.players)) else (self.current_player_idx - 1) % len(self.players)
            if target_idx == self.current_player_idx:
                target_idx = (self.current_player_idx + 1) % len(self.players)

            target_player = self.players[target_idx]
            self.previous_player_idx = self.current_player_idx
            self.current_player_idx = target_idx
            self.turn_seconds = self.base_turn_seconds
            self.current_syllable = self.pick_new_syllable()

            await bot.send_message(
                self.chat_id,
                f"🛡️ {curr.display_name} відбив полум'я! Серце Дракона рикошетить до {target_player.display_name}!",
                parse_mode="HTML"
            )
            await self._start_turn(bot)
            return True, "Полум'я відбито!"

    async def _eliminate_player(self, bot: Bot, reason: str):
        curr_task = asyncio.current_task()
        if self.timer_task and self.timer_task is not curr_task and not self.timer_task.done():
            self.timer_task.cancel()

        if not self.players:
            self.state = "FINISHED"
            active_bomb_games.pop(self.chat_id, None)
            return

        if self.current_player_idx >= len(self.players):
            self.current_player_idx = 0

        eliminated = self.players.pop(self.current_player_idx)
        self.previous_player_idx = None  # индексы сдвинулись, старое значение больше не верно

        explode_text = (
            f"💥 <b>БАБАХ! ПОЛУМ'Я ДРАКОНА СПАЛАХНУЛО!</b> 💥\n\n"
            f"💀 {eliminated.display_name} вибуває з раунду!\n"
            f"Причина: {reason}\n"
            f"<i>(Жодних мутів та покарань — вільно спілкуйся далі)</i>"
        )
        try:
            await bot.send_message(self.chat_id, explode_text, parse_mode="HTML")
        except Exception:
            try:
                await bot.send_message(self.chat_id, explode_text)
            except Exception as e:
                logger.error(f"Failed to send explode message: {e}")

        # Check if we have a winner
        if len(self.players) <= 1:
            self.state = "FINISHED"
            active_bomb_games.pop(self.chat_id, None)

            if len(self.players) == 1:
                winner = self.players[0]
                prize = self.total_pot if self.total_pot > 0 else random.randint(10, 15)

                food = 0
                egg = 0
                try:
                    res = await database.award_game_win(winner.user_id, coins=prize, username=winner.username, first_name=winner.first_name)
                    food = res.get("food", 0)
                    egg = res.get("egg", 0)
                except Exception as e:
                    logger.error(f"Failed to award bomb win in db: {e}")

                victory_text = (
                    f"👑 <b>ПЕРЕМОГА В ГРІ «БОМБА»!</b> 👑\n\n"
                    f"🎉 Вітаємо володаря слів {winner.display_name}!\n"
                    f"🏆 Нагорода: <b>+{prize} 🪙 Монет</b> зачислено у твій інвентар!\n"
                )
                if food > 0:
                    victory_text += "🍖 <b>+1 Смаколик</b> (випав з шансом 20%)!\n"
                if egg > 0:
                    victory_text += (
                        "🥚 <b>ВАМ ВИПАЛО ДРАКОНЯЧЕ ЯЙЦЕ (10% шанс)!</b>\n"
                        "Запустіть <code>/roulette</code> або <code>!рулетка</code>, щоб висидіти нового дракона!\n"
                    )
                victory_text += "\n🐉 Відкрити Лігво: <code>/lair</code> або <code>!моєлігво</code>" 
                try:
                    await bot.send_message(self.chat_id, victory_text, parse_mode="HTML")
                except Exception:
                    try:
                        await bot.send_message(self.chat_id, victory_text)
                    except Exception as e:
                        logger.error(f"Failed to send victory message: {e}")
            return

        # More players remain -> reset core and continue
        self.core_turns_left = random.randint(3, 7)
        self.turn_seconds = self.base_turn_seconds
        if self.current_player_idx >= len(self.players):
            self.current_player_idx = 0

        self.current_syllable = self.pick_new_syllable()
        await self._start_turn(bot)

    async def force_stop(self, bot: Bot, reason: str = "Бій зупинено старійшиною."):
        async with self.lock:
            if self.state == "FINISHED":
                return
            self.state = "FINISHED"
            if self.lobby_task and not self.lobby_task.done():
                self.lobby_task.cancel()
            if self.timer_task and not self.timer_task.done():
                self.timer_task.cancel()

            active_bomb_games.pop(self.chat_id, None)
            await self._refund_all()

            try:
                await bot.send_message(
                    self.chat_id,
                    f"🛑 <b>{html.escape(reason)}</b>\nУсі ставки повернено. Чат вільний для нових ігор!",
                    parse_mode="HTML"
                )
            except Exception:
                pass
