import sqlite3
import json
import os
import asyncio

DB_PATH = os.path.join(os.path.dirname(__file__), "dragon_lair.db")

def _init_db_sync():
    with sqlite3.connect(DB_PATH) as conn:
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
        conn.commit()

async def init_db():
    await asyncio.to_thread(_init_db_sync)

def _get_or_create_user_sync(user_id: int, username: str = "", first_name: str = ""):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row:
            return dict(row)

        default_unlocked = json.dumps([])
        default_names = json.dumps({"fire": "Вогонько", "storm": "Блискавка", "frost": "Крижинка", "jade": "Смарагд"}, ensure_ascii=False)
        default_named = json.dumps({"fire": False, "storm": False, "frost": False, "jade": False})
        default_levels = json.dumps({"fire": 1, "storm": 1, "frost": 1, "jade": 1})
        default_xp = json.dumps({"fire": 0, "storm": 0, "frost": 0, "jade": 0})

        cur.execute("""
            INSERT INTO users (
                user_id, username, first_name, coins, food, eggs, tears,
                active_element, unlocked_elements, dragon_names, named_dragons,
                dragon_levels, dragon_xp, last_train, last_expedition
            ) VALUES (?, ?, ?, 0, 0, 0, 0, '', ?, ?, ?, ?, ?, 0, 0)
        """, (user_id, username, first_name, default_unlocked, default_names, default_named, default_levels, default_xp))
        conn.commit()

        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        return dict(row)

async def get_or_create_user(user_id: int, username: str = "", first_name: str = ""):
    return await asyncio.to_thread(_get_or_create_user_sync, user_id, username, first_name)

def _update_user_sync(user_id: int, kwargs: dict):
    if not kwargs:
        return
    fields = []
    values = []
    for k, v in kwargs.items():
        fields.append(f"{k} = ?")
        if isinstance(v, (dict, list)):
            values.append(json.dumps(v, ensure_ascii=False))
        else:
            values.append(v)
    values.append(user_id)

    query = f"UPDATE users SET {', '.join(fields)} WHERE user_id = ?"
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(query, tuple(values))
        conn.commit()

async def update_user(user_id: int, **kwargs):
    await asyncio.to_thread(_update_user_sync, user_id, kwargs)

def _reset_user_sync(user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        default_unlocked = json.dumps([])
        default_named = json.dumps({"fire": False, "storm": False, "frost": False, "jade": False})
        default_levels = json.dumps({"fire": 1, "storm": 1, "frost": 1, "jade": 1})
        default_xp = json.dumps({"fire": 0, "storm": 0, "frost": 0, "jade": 0})
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
        """, (default_unlocked, default_named, default_levels, default_xp, user_id))
        conn.commit()

async def reset_user(user_id: int):
    await asyncio.to_thread(_reset_user_sync, user_id)

def _add_game_rewards_sync(user_id: int, coins: int, food: int, eggs: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE users
            SET coins = coins + ?,
                food = food + ?,
                eggs = eggs + ?
            WHERE user_id = ?
        """, (coins, food, eggs, user_id))
        conn.commit()

async def add_game_rewards(user_id: int, coins: int, food: int, eggs: int):
    await asyncio.to_thread(_add_game_rewards_sync, user_id, coins, food, eggs)
