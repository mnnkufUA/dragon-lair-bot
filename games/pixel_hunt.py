import asyncio
import difflib
import html
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
METADATA_PATH = HUNT_ASSETS_DIR / "metadata.json"

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


def guess_matches(guess: str, target: str) -> bool:
    """Проверка ответа. Раньше любое слово из 3+ букв, которое является частью названия
    (например «кот» или «the»), считалось правильным ответом — теперь строже."""
    if not guess or not target:
        return False
    if guess == target:
        return True
    # Название целиком внутри сообщения (как отдельные слова): "это шрек наверное"
    if len(target) >= 3 and f" {target} " in f" {guess} ":
        return True
    # Часть многословного названия, но достаточно длинная: "володар перснів" для "володар перснів: братство персня"
    if len(target.split()) > 1 and len(guess) >= 4 and f" {guess} " in f" {target} " and len(guess) >= 0.4 * len(target):
        return True
    # Опечатки
    if len(target) >= 4 and len(guess) >= 4:
        if difflib.SequenceMatcher(None, guess, target).ratio() >= HUNT_FUZZY_THRESHOLD:
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
        # Картинки готовятся в start() в отдельном потоке — раньше это подвешивало всего бота на пару секунд

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
        media_type = html.escape(str(self.meta.get("type", "Фільм / Гра / Мультфільм")))
        hint = html.escape(str(self.meta.get("hint", "Що приховано в серпанку?")))
        next_hint = f"⏳ Наступна фаза через: <b>{HUNT_PHASE_SECONDS} сек</b>\n" if self.phase < 6 else "⚡ Фінальна фаза!\n"
        return (
            f"👁️ <b>ОКО ДРАКОНА: ДЕШИФРАТОР СИГНАЛУ</b> 👁️\n\n"
            f"Категорія: <b>{media_type}</b>\n"
            f"💡 Підказка: <i>{hint}</i>\n"
            f"📊 Гострота зору: {bar} (Фаза {self.phase}/6)\n"
            f"{next_hint}"
            f"🏆 Скарб прямо зараз: <b>{reward} 🪙 Монет</b>\n\n"
            f"Пишіть назву фільму, гри, мультфільму чи ім'я персонажа/актора у чат! Без мутів."
        )

    async def start(self, bot: Bot):
        await asyncio.to_thread(self._prepare_stage_images)
        photo = BufferedInputFile(self.cached_images[1], filename="dragon_hunt_p1.png")
        msg = await bot.send_photo(
            chat_id=self.chat_id,
            photo=photo,
            caption=self.get_caption(),
            parse_mode="HTML"
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
        except Exception as e:
            logger.error(f"Hunt progression loop crashed: {e}", exc_info=True)
            self.is_finished = True
            active_hunt_games.pop(self.chat_id, None)

    async def _update_media(self, bot: Bot):
        if not self.message_id:
            return
        img_bytes = self.cached_images.get(self.phase, self.cached_images[4])
        media = InputMediaPhoto(
            media=BufferedInputFile(img_bytes, filename=f"dragon_hunt_p{self.phase}.png"),
            caption=self.get_caption(),
            parse_mode="HTML"
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
            if self.is_finished or self.message_id is None:
                # игра ещё готовит картинку — ответы пока не принимаем
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

            # Collect all possible answers and aliases
            targets = [normalize_text(self.meta["answer"])]
            for alias in self.meta.get("aliases", []):
                targets.append(normalize_text(alias))

            matched = any(guess_matches(clean_text, t) for t in targets if t)

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

        display_name = html.escape(f"@{username}" if username else first_name)

        win_caption = (
            f"🎉 <b>СИГНАЛ УСПІШНО ДЕШИФРОВАНО!</b> 🎉\n\n"
            f"Правильна відповідь: <b>{html.escape(str(self.meta['answer']))}</b>\n"
            f"🥇 Першим розгадав: {display_name} (на {self.phase}-й фазі)!\n"
            f"🏆 Здобуток: <b>+{reward} 🪙 Монет</b> зачислено у скарбницю!\n"
        )
        if food > 0:
            win_caption += "🍖 <b>+1 Смаколик</b> (випав з шансом 20%)!\n"
        if egg > 0:
            win_caption += (
                "🥚 <b>ВАМ ВИПАЛО ДРАКОНЯЧЕ ЯЙЦЕ (10% шанс)!</b>\n"
                "Запустіть <code>/roulette</code> або <code>!рулетка</code>, щоб відкрити нового дракона!\n"
            )
        win_caption += "\n🐉 Відкрити Лігво: <code>/lair</code> або <code>!моєлігво</code>" 

        if self.message_id:
            try:
                media = InputMediaPhoto(
                    media=BufferedInputFile(self.cached_images[6], filename="dragon_hunt_final.png"),
                    caption=win_caption,
                    parse_mode="HTML"
                )
                await bot.edit_message_media(
                    chat_id=self.chat_id,
                    message_id=self.message_id,
                    media=media
                )
            except Exception:
                try:
                    await bot.send_message(self.chat_id, win_caption, parse_mode="HTML")
                except Exception:
                    pass

    async def _reveal_unanswered(self, bot: Bot):
        self.is_finished = True
        active_hunt_games.pop(self.chat_id, None)

        reveal_caption = (
            f"⌛ <b>ЧАС РОЗГАДКИ ВИТІК!</b> ⌛\n\n"
            f"Ніхто не зміг вгадати цей об'єкт.\n"
            f"Правильна відповідь: <b>{html.escape(str(self.meta['answer']))}</b>\n\n"
            f"Скарби повертаються до лігва Дракона. Наступного разу пощастить!"
        )

        if self.message_id:
            try:
                media = InputMediaPhoto(
                    media=BufferedInputFile(self.cached_images[6], filename="dragon_hunt_reveal.png"),
                    caption=reveal_caption,
                    parse_mode="HTML"
                )
                await bot.edit_message_media(
                    chat_id=self.chat_id,
                    message_id=self.message_id,
                    media=media
                )
            except Exception:
                try:
                    await bot.send_message(self.chat_id, reveal_caption, parse_mode="HTML")
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
