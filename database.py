import sqlite3
import json
import os
import asyncio
import random
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Путь к базе. На Render можно задать переменную DB_PATH (например /data/dragon_lair.db),
# если подключён постоянный диск. Иначе база лежит рядом с кодом.
DB_PATH = os.getenv("DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "dragon_lair.db")

# Какие поля разрешено менять через update_user (защита от кривых/опасных ключей)
ALLOWED_FIELDS = {
    "username", "first_name", "coins", "food", "eggs", "tears",
    "active_element", "unlocked_elements", "dragon_names", "named_dragons",
    "dragon_levels", "dragon_xp", "last_train", "last_expedition",
}

DEFAULT_NAMED = {"fire": False, "storm": False, "frost": False, "jade": False}
DEFAULT_LEVELS = {"fire": 1, "storm": 1, "frost": 1, "jade": 1}
DEFAULT_XP = {"fire": 0, "storm": 0, "frost": 0, "jade": 0}


@contextmanager
def _connect():
    """Открывает базу, сохраняет изменения и ОБЯЗАТЕЛЬНО закрывает соединение."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _init_db_sync():
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with _connect() as conn:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                coins INTEGER DEFAULT 0,
                food INTEGER DEFAULT 0,
                eggs INTEGER DEFAULT 0,
                tears INTEGER DEFAULT 0,
                active_element TEXT DEFAULT '',
                unlocked_elements TEXT DEFAULT '[]',
                dragon_names TEXT DEFAULT '{"fire":"Вогонько","storm":"Блискавка","frost":"Крижинка","jade":"Смарагд"}',
                named_dragons TEXT DEFAULT '{"fire":false,"storm":false,"frost":false,"jade":false}',
                dragon_levels TEXT DEFAULT '{"fire":1,"storm":1,"frost":1,"jade":1}',
                dragon_xp TEXT DEFAULT '{"fire":0,"storm":0,"frost":0,"jade":0}',
                last_train INTEGER DEFAULT 0,
                last_expedition INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


async def init_db():
    await asyncio.to_thread(_init_db_sync)


def _get_or_create_user_sync(user_id: int, username: str = "", first_name: str = ""):
    with _connect() as conn:
        # INSERT OR IGNORE: если два запроса создают одного юзера одновременно — ошибки не будет
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
            (user_id, username, first_name),
        )
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

        # Обновляем имя/ник, если человек их сменил
        if (username and row["username"] != username) or (first_name and row["first_name"] != first_name):
            conn.execute(
                "UPDATE users SET username = ?, first_name = ? WHERE user_id = ?",
                (username or row["username"], first_name or row["first_name"], user_id),
            )
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row)


async def get_or_create_user(user_id: int, username: str = "", first_name: str = ""):
    return await asyncio.to_thread(_get_or_create_user_sync, user_id, username, first_name)


def _update_user_sync(user_id: int, kwargs: dict):
    fields = []
    values = []
    for k, v in kwargs.items():
        if k not in ALLOWED_FIELDS:
            logger.warning("update_user: поле %r не разрешено, пропускаю", k)
            continue
        fields.append(f"{k} = ?")
        if isinstance(v, (dict, list)):
            values.append(json.dumps(v, ensure_ascii=False))
        else:
            values.append(v)
    if not fields:
        return
    values.append(user_id)
    query = f"UPDATE users SET {', '.join(fields)} WHERE user_id = ?"
    with _connect() as conn:
        conn.execute(query, tuple(values))


async def update_user(user_id: int, **kwargs):
    await asyncio.to_thread(_update_user_sync, user_id, kwargs)


def _reset_user_sync(user_id: int):
    with _connect() as conn:
        conn.execute("""
            UPDATE users SET
                coins = 0,
                food = 0,
                eggs = 0,
                tears = 0,
                active_element = '',
                unlocked_elements = ?,
                named_dragons = ?,
                dragon_levels = ?,
                dragon_xp = ?,
                last_train = 0,
                last_expedition = 0
            WHERE user_id = ?
        """, (
            json.dumps([]),
            json.dumps(DEFAULT_NAMED),
            json.dumps(DEFAULT_LEVELS),
            json.dumps(DEFAULT_XP),
            user_id,
        ))


async def reset_user(user_id: int):
    await asyncio.to_thread(_reset_user_sync, user_id)


def _add_game_rewards_sync(user_id: int, coins: int, food: int, eggs: int):
    with _connect() as conn:
        conn.execute("""
            UPDATE users
            SET coins = coins + ?,
                food = food + ?,
                eggs = eggs + ?
            WHERE user_id = ?
        """, (coins, food, eggs, user_id))


async def add_game_rewards(user_id: int, coins: int, food: int, eggs: int):
    await asyncio.to_thread(_add_game_rewards_sync, user_id, coins, food, eggs)


def _try_deduct_coins_sync(user_id: int, amount: int) -> bool:
    if amount <= 0:
        return True
    with _connect() as conn:
        # Одна атомарная команда: списывает только если монет хватает
        cur = conn.execute(
            "UPDATE users SET coins = coins - ? WHERE user_id = ? AND coins >= ?",
            (amount, user_id, amount),
        )
        return cur.rowcount == 1


async def try_deduct_coins(user_id: int, amount: int) -> bool:
    return await asyncio.to_thread(_try_deduct_coins_sync, user_id, amount)


def _get_balance_sync(user_id: int) -> int:
    with _connect() as conn:
        row = conn.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return int(row["coins"]) if row else 0


async def get_balance(user_id: int) -> int:
    return await asyncio.to_thread(_get_balance_sync, user_id)


def _add_coins_sync(user_id: int, amount: int):
    with _connect() as conn:
        conn.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, user_id))


async def add_coins(user_id: int, amount: int):
    await asyncio.to_thread(_add_coins_sync, user_id, amount)


def _try_spend_egg_sync(user_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE users SET eggs = eggs - 1 WHERE user_id = ? AND eggs >= 1",
            (user_id,),
        )
        return cur.rowcount == 1


async def try_spend_egg(user_id: int) -> bool:
    """Списывает 1 яйцо, только если оно есть. Возвращает True/False."""
    return await asyncio.to_thread(_try_spend_egg_sync, user_id)


def _add_food_sync(user_id: int, amount: int):
    with _connect() as conn:
        conn.execute("UPDATE users SET food = food + ? WHERE user_id = ?", (amount, user_id))


async def add_food(user_id: int, amount: int):
    await asyncio.to_thread(_add_food_sync, user_id, amount)


async def award_game_win(user_id: int, coins: int, username: str = "", first_name: str = "") -> dict:
    await get_or_create_user(user_id, username, first_name)
    food = 1 if random.random() < 0.20 else 0
    egg = 1 if random.random() < 0.10 else 0
    await add_game_rewards(user_id, coins=coins, food=food, eggs=egg)
    return {"coins": coins, "food": food, "egg": egg}


async def record_bomb_win(user_id: int, prize: int):
    return await award_game_win(user_id, coins=prize)


async def record_hunt_win(user_id: int, prize: int):
    return await award_game_win(user_id, coins=prize)


async def record_cities_win(user_id: int, prize: int):
    return await award_game_win(user_id, coins=prize)
