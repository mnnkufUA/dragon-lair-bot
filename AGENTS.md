# Dragon Lair Bot — Development Guidelines & Strict Agent Rules

> **CRITICAL**: This file defines mandatory architectural rules and the verification protocol for `dragon-lair-bot`. Every agent interacting with this project MUST strictly follow these guidelines.

---

## 1. Project Architecture & Tech Stack

* **Language**: Python 3.13+
* **Bot Framework**: **aiogram 3.10+ (STRICTLY v3, NEVER v2)**
* **Web / API Server**: `FastAPI` + `uvicorn` (runs the Telegram Mini App & manages bot lifecycle in `main.py`)
* **Database**: SQLite (`dragon_lair.db`) managed via `database.py` using `asyncio.to_thread` for non-blocking execution
* **Telegram Mini App (TMA)**: Embedded in `index.html`, served via FastAPI root `/`
* **Bot Language / Localization**: Ukrainian (`uk`) UI messages with bilingual trigger phrases (Ukrainian & Russian) for games

### Directory Map
* `bot.py` — Telegram dispatcher, router registration, keyboards, main text trigger handlers (`is_text_trigger`).
* `main.py` — FastAPI server, lifespan manager (starts polling, initializes DB, serves `index.html`).
* `config.py` — Environment variables (`BOT_TOKEN`, `WEBAPP_URL`, `TG_APP_URL`) and game balance constants.
* `database.py` — User data, inventory, dragons, currency, rewards.
* `handlers/` — Feature and game routers (`bomb_handlers.py`, `hunt_handlers.py`, `cities_handlers.py`, `common.py`).
* `games/` — Game mechanics logic (`cyber_bomb.py`, `cities_game.py`, `pixel_hunt.py`).
* `data/` — Dictionaries, word lists, cities lists.

---

## 2. STRICT aiogram 3.x Rules (NO HALLUCINATIONS)

The agent must NEVER generate aiogram v2 code. aiogram 3 differences are absolute:

| Topic | ❌ FORBIDDEN (v2) | ✅ REQUIRED (v3) |
| :--- | :--- | :--- |
| **Routers** | `@dp.message_handler(...)` | `router = Router()`, `@router.message(...)` |
| **Filters** | `content_types=['text']`, `lambda m: ...` | `F.text`, `F.data == "..."`, `Command("start")` |
| **FSM Context** | `state.finish()`, `state.set_state('state')` | `await state.clear()`, `await state.set_state(MyState.target)` |
| **State Storage** | `from aiogram.dispatcher.filters.state` | `from aiogram.fsm.state import State, StatesGroup` |
| **Callbacks** | Forgetting to answer | **Always** `await callback.answer()` to stop loading spinners |
| **Parse Mode** | `types.ParseMode.HTML` | `from aiogram.enums import ParseMode; ParseMode.HTML` or `"HTML"` |

### Telegram Groups vs Private Chat (Crucial Mini App Rule)
* Telegram **strictly forbids** `web_app=WebAppInfo(...)` inline buttons in group chats!
* Always check the chat type:
  * **Private chat (DM)**: `InlineKeyboardButton(text="...", web_app=WebAppInfo(url=WEBAPP_URL))`
  * **Group / Supergroup**: `InlineKeyboardButton(text="...", url=TG_APP_URL)` (direct link to the Telegram bot app link)
  * Refer to `bot.py:get_main_keyboard(is_group)` as the single source of truth.

---

## 3. Database Rules (`database.py`)

1. **Non-blocking calls**: The database uses standard `sqlite3` wrapped in `asyncio.to_thread(_sync_func)`. **Never** execute blocking SQLite queries directly on the event loop.
2. **JSON Fields**: Columns like `unlocked_elements`, `dragon_names`, `dragon_levels`, `dragon_xp` contain JSON strings.
   * Always `json.dumps(..., ensure_ascii=False)` when saving.
   * Always `json.loads(...)` with fallback default dicts/lists when reading.
3. **No Database Locks**: Always use `with sqlite3.connect(DB_PATH) as conn:` context managers so connections and transactions commit cleanly and close immediately.

---

## 4. MANDATORY VERIFICATION PROTOCOL (ПРАВИЛО ПРОВЕРКИ)

> **STRICT REQUIREMENT**: The agent is **STRICTLY PROHIBITED** from declaring "все готово", "все работает", or claiming success until the following automated checks pass:

1. **Syntax & Compilation Check**:
   Before finishing any Python code modification, run:
   ```powershell
   python -m py_compile <path_to_modified_file>
   ```
   If there is ANY `SyntaxError`, `IndentationError`, or `TabError`, fix it immediately before responding.

2. **Import Integrity Check**:
   Verify that modified files do not have broken imports or circular references:
   ```powershell
   python -c "import config; import database; import bot; import main"
   ```

3. **Router Attachment Check**:
   If a new handler or router was created in `handlers/`, verify that `dp.include_router(your_router)` is called in `bot.py`.

4. **Proof of Verification in Response**:
   When reporting to the user, always provide:
   * What was changed.
   * Confirmation of the verification command executed and its result.
   * If any runtime testing was conducted, cite the test output.
