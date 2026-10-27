import asyncio
import difflib
import io
import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Dict, List, Optional
from aiogram import Bot
from aiogram.types import BufferedInputFile, InputMediaPhoto
from PIL import Image

import database
from config import BASE_DIR, HUNT_PHASE_SECONDS, HUNT_FUZZY_THRESHOLD

logger = logging.getLogger("DragonHunt")
HUNT_ASSETS_DIR = BASE_DIR / "assets" / "hunt"
if not HUNT_ASSETS_DIR.exists():
    HUNT_ASSETS_DIR = BASE_DIR / "hunt"
METADATA_PATH = HUNT_ASSETS_DIR / "metadata.json"
if not METADATA_PATH.exists():
    METADATA_PATH = BASE_DIR / "data" / "metadata.json"
if not METADATA_PATH.exists():
    METADATA_PATH = BASE_DIR / "metadata.json"

# Global registry of active hunt games: chat_id -> PixelHuntGame
active_hunt_games: Dict[int, "PixelHuntGame"] = {}


def normalize_text(text: str) -> str:
    """Normalize text for bulletproof multi-lingual matching (UA/RU/EN)"""
    t = text.lower().strip()
    # Replace common interchangeable chars
    t = t.replace("ё", "е").replace("ґ", "г")
    # Remove punctuation
    t = re.sub(r"[^\w\s]", " ", t)
    # Collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()
    return t


def guess_matches(user_guess: str, target: str) -> bool:
    """Strict title matcher: prevents matching single random words from multi-word titles."""
    if not user_guess or not target:
        return False
    # 1. Exact match
    if user_guess == target:
        return True
    # 2. Target contained in user message (e.g. "це фільм бійцівський клуб")
    if target in user_guess:
        return True
    # 3. User guess can only contain target if lengths are close (>= 85%)
    if len(user_guess) >= len(target) * 0.85 and user_guess in target:
        ratio = difflib.SequenceMatcher(None, user_guess, target).ratio()
        if ratio >= HUNT_FUZZY_THRESHOLD:
            return True
    # 4. Multi-word guard: If target has multiple words, 1 short word must NOT match
    target_words = target.split()
    guess_words = user_guess.split()
    if len(target_words) > 1 and len(guess_words) == 1 and len(user_guess) < len(target) * 0.65:
        return False
    # 5. Fuzzy matching for full title with 1-2 typos
    ratio = difflib.SequenceMatcher(None, user_guess, target).ratio()
    if ratio >= HUNT_FUZZY_THRESHOLD:
        return True
    return False


class PixelHuntGame:
    def __init__(self, chat_id: int, item_meta: dict):
        self.chat_id = chat_id
        self.meta = item_meta
        self.phase: int = 1  # 1 to 6
        self.message_id: Optional[int] = None
        self.is_finished: bool = False
        self.lock = asyncio.Lock()
        self.phase_task: Optional[asyncio.Task] = None
        self.user_cooldowns: Dict[int, float] = {}

        self.rewards = {
            1: 30,
            2: 25,
            3: 20,
            4: 15,
            5: 12,
            6: 10
        }

        # Cache generated stage image bytes
        self.cached_images: Dict[int, bytes] = {}
        self._prepare_stage_images()

    def _prepare_stage_images(self):
        img_path = HUNT_ASSETS_DIR / self.meta["file"]
        original = Image.open(img_path).convert("RGB")
        orig_w, orig_h = original.size

        def make_pixelated(target_w: int) -> bytes:
            ratio = target_w / max(1, orig_w)
            target_h = max(1, int(orig_h * ratio))
            # Downscale preserving aspect ratio, then upscale back using nearest neighbor
            down = original.resize((target_w, target_h), Image.Resampling.NEAREST)
            up = down.resize((orig_w, orig_h), Image.Resampling.NEAREST)
            b = io.BytesIO()
            up.save(b, format="PNG")
            return b.getvalue()

        # 6 distinct, progressive phases:
        # Phase 1: Heavy abstract mosaic (width 16px)
        self.cached_images[1] = make_pixelated(16)

        # Phase 2: Strong pixelation (width 32px)
        self.cached_images[2] = make_pixelated(32)

        # Phase 3: Medium pixelation (width 55px)
        self.cached_images[3] = make_pixelated(55)

        # Phase 4: Light pixelation (width 90px)
        self.cached_images[4] = make_pixelated(90)

        # Phase 5: Soft pixelation (width 160px)
        self.cached_images[5] = make_pixelated(160)

        # Phase 6: Full original HD
        b6 = io.BytesIO()
        original.save(b6, format="PNG")
        self.cached_images[6] = b6.getvalue()

    def get_caption(self) -> str:
        reward = self.rewards.get(self.phase, 10)
        bars = [
            "⬛⬛⬛⬛⬛⬛",
            "🟩⬛⬛⬛⬛⬛",
            "🟩🟩⬛⬛⬛⬛",
            "🟩🟩🟩⬛⬛⬛",
            "🟩🟩🟩🟩⬛⬛",
            "🟩🟩🟩🟩🟩⬛",
            "🟩🟩🟩🟩🟩🟩"
        ]
        bar = bars[min(self.phase, 6)]
        media_type = self.meta.get("type", "Фільм / Гра / Мультфільм")
        next_hint = f"⏳ Наступна фаза через: **{HUNT_PHASE_SECONDS} сек**\n" if self.phase < 6 else "⚡ Фінальна фаза!\n"
        return (
            f"👁️ **ОКО ДРАКОНА: ДЕШИФРАТОР СИГНАЛУ** 👁️\n\n"
            f"Категорія: **{media_type}**\n"
            f"💡 Підказка: *{self.meta.get('hint', 'Що приховано в серпанку?')}*\n"
            f"📊 Гострота зору: {bar} (Фаза {self.phase}/6)\n"
            f"{next_hint}"
            f"🏆 Скарб прямо зараз: **{reward} 🪙 Монет**\n\n"
            f"Пишіть назву фільму, гри, мультфільму чи ім'я персонажа/актора у чат! Без мутів."
        )

    async def start(self, bot: Bot):
        photo = BufferedInputFile(self.cached_images[1], filename="dragon_hunt_p1.png")
        msg = await bot.send_photo(
            chat_id=self.chat_id,
            photo=photo,
            caption=self.get_caption(),
            parse_mode="Markdown"
        )
        self.message_id = msg.message_id
        self.phase_task = asyncio.create_task(self._progression_loop(bot))

    async def _progression_loop(self, bot: Bot):
        try:
            while self.phase < 6:
                await asyncio.sleep(HUNT_PHASE_SECONDS)
                async with self.lock:
                    if self.is_finished:
                        return
                    self.phase += 1
                    await self._update_media(bot)

            # Wait after Phase 6 before revealing answer
            await asyncio.sleep(HUNT_PHASE_SECONDS)
            async with self.lock:
                if not self.is_finished:
                    await self._reveal_unanswered(bot)
        except asyncio.CancelledError:
            pass

    async def _update_media(self, bot: Bot):
        if not self.message_id:
            return
        img_bytes = self.cached_images.get(self.phase, self.cached_images[4])
        media = InputMediaPhoto(
            media=BufferedInputFile(img_bytes, filename=f"dragon_hunt_p{self.phase}.png"),
            caption=self.get_caption(),
            parse_mode="Markdown"
        )
        try:
            await bot.edit_message_media(
                chat_id=self.chat_id,
                message_id=self.message_id,
                media=media
            )
        except Exception:
            pass

    async def check_guess(self, user_id: int, username: str, first_name: str, text: str, bot: Bot) -> bool:
        async with self.lock:
            if self.is_finished:
                return False

            now = time.time()
            # Fast response cooldown (0.5s instead of 2s to allow typo corrections)
            last_guess = self.user_cooldowns.get(user_id, 0)
            if now - last_guess < 0.5:
                return False
            self.user_cooldowns[user_id] = now

            clean_text = normalize_text(text)
            if not clean_text:
                return False

            # Check franchise rule (GTA, Witcher, etc.)
            FRANCHISES = {
                "gta": ["gta", "гта", "grand theft auto"],
                "відьмак": ["відьмак", "ведьмак", "witcher", "the witcher"],
                "гаррі поттер": ["гаррі поттер", "гарри поттер", "harry potter"],
                "зоряні війни": ["зоряні війни", "звездные войны", "star wars"],
                "володар перснів": ["володар перснів", "властелин колец", "lord of the rings"],
                "людина павук": ["людина павук", "человек паук", "spider man", "spiderman"],
            }
            norm_answer = normalize_text(self.meta.get("answer", ""))
            for f_key, triggers in FRANCHISES.items():
                if any(t in norm_answer for t in triggers):
                    if clean_text in triggers:
                        await bot.send_message(
                            self.chat_id,
                            "🎮 Майже! Але уточніть, яка саме це частина серії (номер або підзаголовок)?"
                        )
                        return True

            # Collect all possible answers and aliases
            targets = [normalize_text(self.meta["answer"])]
            for alias in self.meta.get("aliases", []):
                targets.append(normalize_text(alias))

            matched = False
            for target in targets:
                if not target:
                    continue
                if guess_matches(clean_text, target):
                    matched = True
                    break

            if matched:
                await self._finish_with_winner(user_id, username, first_name, bot)
                return True

            return False

    async def _finish_with_winner(self, user_id: int, username: str, first_name: str, bot: Bot):
        self.is_finished = True
        if self.phase_task and not self.phase_task.done():
            self.phase_task.cancel()

        active_hunt_games.pop(self.chat_id, None)

        reward = self.rewards.get(self.phase, 20)
        food = 0
        egg = 0
        try:
            res = await database.award_game_win(user_id, coins=reward, username=username, first_name=first_name)
            food = res.get("food", 0)
            egg = res.get("egg", 0)
        except Exception as e:
            logger.error(f"Failed to record hunt win: {e}")

        display_name = f"@{username}" if username else first_name

        win_caption = (
            f"🎉 **СИГНАЛ УСПІШНО ДЕШИФРОВАНО!** 🎉\n\n"
            f"Правильна відповідь: **{self.meta['answer']}**\n"
            f"🥇 Першим розгадав: {display_name} (на {self.phase}-й фазі)!\n"
            f"🏆 Здобуток: **+{reward} 🪙 Монет** зачислено у скарбницю!\n"
        )
        if food > 0:
            win_caption += "🍖 **+1 Смаколик** (випав з шансом 20%)!\n"
        if egg > 0:
            win_caption += (
                "🥚 **ВАМ ВИПАЛО ДРАКОНЯЧЕ ЯЙЦЕ (10% шанс)!**\n"
                "Запустіть `/roulette` або `!рулетка`, щоб відкрити нового дракона!\n"
            )
        win_caption += "\n🐉 Відкрити Лігво: `/lair` або `!моєлігво`" 

        if self.message_id:
            try:
                media = InputMediaPhoto(
                    media=BufferedInputFile(self.cached_images.get(6, self.cached_images.get(self.phase)), filename="dragon_hunt_final.png"),
                    caption=win_caption,
                    parse_mode="Markdown"
                )
                await bot.edit_message_media(
                    chat_id=self.chat_id,
                    message_id=self.message_id,
                    media=media
                )
            except Exception:
                try:
                    await bot.send_message(self.chat_id, win_caption, parse_mode="Markdown")
                except Exception:
                    pass

    async def _reveal_unanswered(self, bot: Bot):
        self.is_finished = True
        active_hunt_games.pop(self.chat_id, None)

        reveal_caption = (
            f"⌛ **ЧАС РОЗГАДКИ ВИТІК!** ⌛\n\n"
            f"Ніхто не зміг вгадати цей об'єкт.\n"
            f"Правильна відповідь: **{self.meta['answer']}**\n\n"
            f"Скарби повертаються до лігва Дракона. Наступного разу пощастить!"
        )

        if self.message_id:
            try:
                media = InputMediaPhoto(
                    media=BufferedInputFile(self.cached_images.get(6, self.cached_images.get(self.phase)), filename="dragon_hunt_reveal.png"),
                    caption=reveal_caption,
                    parse_mode="Markdown"
                )
                await bot.edit_message_media(
                    chat_id=self.chat_id,
                    message_id=self.message_id,
                    media=media
                )
            except Exception:
                try:
                    await bot.send_message(self.chat_id, reveal_caption, parse_mode="Markdown")
                except Exception:
                    pass


def pick_random_hunt_item() -> Optional[dict]:
    if not METADATA_PATH.exists():
        return None
    with open(METADATA_PATH, "r", encoding="utf-8") as f:
        items = json.load(f)
    if not items:
        return None
    return random.choice(items)