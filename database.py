import sqlite3
import json
import os
import asyncio

try:
    import psycopg2
    import psycopg2.extras
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_PATH = os.path.join(os.path.dirname(__file__), "dragon_lair.db")

def get_connection():
    if DATABASE_URL and HAS_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        return conn, True
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn, False

def execute_query(conn, is_pg: bool, sql: str, params: tuple = ()):
    if is_pg:
        sql = sql.replace("?", "%s")
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur

def _init_db_sync():
    conn, is_pg = get_connection()
    try:
        pk_type = "BIGINT PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY"
        create_sql = f"""
            CREATE TABLE IF NOT EXISTS users (
                user_id {pk_type},
                username TEXT,
                first_name TEXT,
                coins INTEGER DEFAULT 0,
                food INTEGER DEFAULT 0,
                eggs INTEGER DEFAULT 0,
                tears INTEGER DEFAULT 0,
                active_element TEXT DEFAULT '',
                unlocked_elements TEXT DEFAULT '[]',
                dragon_names TEXT DEFAULT '{{"fire":"Вогонько","storm":"Блискавка","frost":"Крижинка","jade":"Смарагд"}}',
                named_dragons TEXT DEFAULT '{{"fire":false,"storm":false,"frost":false,"jade":false}}',
                dragon_levels TEXT DEFAULT '{{"fire":1,"storm":1,"frost":1,"jade":1}}',
                dragon_xp TEXT DEFAULT '{{"fire":0,"storm":0,"frost":0,"jade":0}}',
                last_train INTEGER DEFAULT 0,
                last_expedition INTEGER DEFAULT 0,
                has_started INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        execute_query(conn, is_pg, create_sql)

        try:
            execute_query(conn, is_pg, "ALTER TABLE users ADD COLUMN has_started INTEGER DEFAULT 0")
        except Exception:
            if is_pg:
                conn.rollback()

        # Seed owner account 5310415233 so cold restart on Render never wipes progress
        cur = execute_query(conn, is_pg, "SELECT coins, eggs, food, tears, unlocked_elements FROM users WHERE user_id = ?", (5310415233,))
        row = cur.fetchone()
        default_unlocked = json.dumps(["fire", "storm", "frost", "jade"])
        default_names = json.dumps({"fire": "Сонячне Полум'я", "storm": "Флайтмейр", "frost": "Дрімдракон", "jade": "Синґтейл"}, ensure_ascii=False)
        default_named = json.dumps({"fire": False, "storm": False, "frost": False, "jade": False})
        default_levels = json.dumps({"fire": 15, "storm": 15, "frost": 15, "jade": 15})
        default_xp = json.dumps({"fire": 0, "storm": 0, "frost": 0, "jade": 0})

        if not row:
            execute_query(conn, is_pg, """
                INSERT INTO users (
                    user_id, username, first_name, coins, food, eggs, tears,
                    active_element, unlocked_elements, dragon_names, named_dragons,
                    dragon_levels, dragon_xp, last_train, last_expedition
                ) VALUES (5310415233, 'mnnkufUA', 'Володар', 10000, 50, 60, 100, 'fire', ?, ?, ?, ?, ?, 0, 0)
            """, (default_unlocked, default_names, default_named, default_levels, default_xp))
        else:
            coins = row["coins"] if isinstance(row, dict) else row[0]
            eggs = row["eggs"] if isinstance(row, dict) else row[1]
            food = row["food"] if isinstance(row, dict) else row[2]
            tears = row["tears"] if isinstance(row, dict) else row[3]
            unlocked = row["unlocked_elements"] if isinstance(row, dict) else row[4]
            if (coins or 0) < 10000 or (eggs or 0) < 60 or (food or 0) < 50 or (tears or 0) < 100 or not unlocked or unlocked == "[]":
                execute_query(conn, is_pg, """
                    UPDATE users SET
                        coins = CASE WHEN coins < 10000 THEN 10000 ELSE coins END,
                        food = CASE WHEN food < 50 THEN 50 ELSE food END,
                        eggs = CASE WHEN eggs < 60 THEN 60 ELSE eggs END,
                        tears = CASE WHEN tears < 100 THEN 100 ELSE tears END,
                        active_element = CASE WHEN active_element = '' THEN 'fire' ELSE active_element END,
                        unlocked_elements = ?,
                        dragon_names = ?,
                        dragon_levels = ?
                    WHERE user_id = 5310415233
                """, (default_unlocked, default_names, default_levels))
        conn.commit()
    finally:
        conn.close()

async def init_db():
    await asyncio.to_thread(_init_db_sync)

def _get_or_create_user_sync(user_id: int, username: str = "", first_name: str = ""):
    conn, is_pg = get_connection()
    try:
        cur = execute_query(conn, is_pg, "SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row:
            return dict(row)

        default_unlocked = json.dumps([])
        default_names = json.dumps({"fire": "Вогонько", "storm": "Блискавка", "frost": "Крижинка", "jade": "Смарагд"}, ensure_ascii=False)
        default_named = json.dumps({"fire": False, "storm": False, "frost": False, "jade": False})
        default_levels = json.dumps({"fire": 15, "storm": 15, "frost": 15, "jade": 15})
        default_xp = json.dumps({"fire": 0, "storm": 0, "frost": 0, "jade": 0})

        execute_query(conn, is_pg, """
            INSERT INTO users (
                user_id, username, first_name, coins, food, eggs, tears,
                active_element, unlocked_elements, dragon_names, named_dragons,
                dragon_levels, dragon_xp, last_train, last_expedition
            ) VALUES (?, ?, ?, 0, 0, 0, 0, '', ?, ?, ?, ?, ?, 0, 0)
        """, (user_id, username, first_name, default_unlocked, default_names, default_named, default_levels, default_xp))
        conn.commit()

        cur = execute_query(conn, is_pg, "SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()

async def get_or_create_user(user_id: int, username: str = "", first_name: str = ""):
    return await asyncio.to_thread(_get_or_create_user_sync, user_id, username, first_name)

def _update_user_sync(user_id: int, kwargs: dict):
    if not kwargs:
        return
    conn, is_pg = get_connection()
    try:
        cur = execute_query(conn, is_pg, "SELECT 1 FROM users WHERE user_id = ?", (user_id,))
        if not cur.fetchone():
            default_unlocked = json.dumps([])
            default_names = json.dumps({"fire": "Вогонько", "storm": "Блискавка", "frost": "Крижинка", "jade": "Смарагд"}, ensure_ascii=False)
            default_named = json.dumps({"fire": False, "storm": False, "frost": False, "jade": False})
            default_levels = json.dumps({"fire": 15, "storm": 15, "frost": 15, "jade": 15})
            default_xp = json.dumps({"fire": 0, "storm": 0, "frost": 0, "jade": 0})
            execute_query(conn, is_pg, """
                INSERT INTO users (
                    user_id, username, first_name, coins, food, eggs, tears,
                    active_element, unlocked_elements, dragon_names, named_dragons,
                    dragon_levels, dragon_xp, last_train, last_expedition
                ) VALUES (?, '', '', 0, 0, 0, 0, '', ?, ?, ?, ?, ?, 0, 0)
            """, (user_id, default_unlocked, default_names, default_named, default_levels, default_xp))

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
        execute_query(conn, is_pg, query, tuple(values))
        conn.commit()
    finally:
        conn.close()

async def update_user(user_id: int, **kwargs):
    await asyncio.to_thread(_update_user_sync, user_id, kwargs)

def _reset_user_sync(user_id: int):
    conn, is_pg = get_connection()
    try:
        default_unlocked = json.dumps([])
        default_named = json.dumps({"fire": False, "storm": False, "frost": False, "jade": False})
        default_levels = json.dumps({"fire": 15, "storm": 15, "frost": 15, "jade": 15})
        default_xp = json.dumps({"fire": 0, "storm": 0, "frost": 0, "jade": 0})
        execute_query(conn, is_pg, """
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
    finally:
        conn.close()

async def reset_user(user_id: int):
    await asyncio.to_thread(_reset_user_sync, user_id)

def _add_game_rewards_sync(user_id: int, coins: int, food: int, eggs: int):
    conn, is_pg = get_connection()
    try:
        execute_query(conn, is_pg, """
            UPDATE users
            SET coins = coins + ?,
                food = food + ?,
                eggs = eggs + ?
            WHERE user_id = ?
        """, (coins, food, eggs, user_id))
        conn.commit()
    finally:
        conn.close()

async def add_game_rewards(user_id: int, coins: int, food: int, eggs: int):
    await asyncio.to_thread(_add_game_rewards_sync, user_id, coins, food, eggs)

def _try_deduct_coins_sync(user_id: int, amount: int) -> bool:
    if amount <= 0:
        return True
    conn, is_pg = get_connection()
    try:
        cur = execute_query(conn, is_pg, "SELECT coins FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if not row:
            return False
        coins = row["coins"] if isinstance(row, dict) else row[0]
        if coins < amount:
            return False
        execute_query(conn, is_pg, "UPDATE users SET coins = coins - ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        return True
    finally:
        conn.close()

async def try_deduct_coins(user_id: int, amount: int) -> bool:
    return await asyncio.to_thread(_try_deduct_coins_sync, user_id, amount)

def _add_coins_sync(user_id: int, amount: int):
    conn, is_pg = get_connection()
    try:
        execute_query(conn, is_pg, "UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
    finally:
        conn.close()

async def add_coins(user_id: int, amount: int):
    await asyncio.to_thread(_add_coins_sync, user_id, amount)

async def award_game_win(user_id: int, coins: int, username: str = "", first_name: str = "") -> dict:
    import random
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
