import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse

from bot import dp, setup_bot_commands
from config import BOT_TOKEN
from database import init_db, get_or_create_user, update_user, reset_user

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("main")

bot = None


def _on_polling_done(task: asyncio.Task):
    """Если бот упал (например, неверный токен) — пишем причину в лог, а не молчим."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error("❌ Telegram polling остановился с ошибкой: %r", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot
    await init_db()

    bot_task = None
    if BOT_TOKEN:
        bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
        await setup_bot_commands(bot)
        # handle_signals=False — иначе aiogram конфликтует с uvicorn при остановке
        bot_task = asyncio.create_task(
            dp.start_polling(
                bot,
                allowed_updates=["message", "callback_query"],
                handle_signals=False,
            )
        )
        bot_task.add_done_callback(_on_polling_done)
        logger.info("🚀 Telegram Bot polling started!")
    else:
        logger.warning("⚠️ BOT_TOKEN не задан! Работает только сервер WebApp.")

    yield

    if bot_task:
        bot_task.cancel()
        await asyncio.gather(bot_task, return_exceptions=True)
    if bot:
        await bot.session.close()


app = FastAPI(lifespan=lifespan)

# index.html весит ~12 МБ — сжимаем, чтобы мини-апп открывался быстрее
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

HTML_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")


@app.get("/", response_class=HTMLResponse)
async def serve_webapp():
    if os.path.exists(HTML_FILE_PATH):
        return FileResponse(HTML_FILE_PATH)
    return HTMLResponse("<h1>Dragon Lair WebApp: index.html not found!</h1>", status_code=404)


@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "Dragon Lair Bot & WebApp are running 24/7!"}


@app.get("/api/user")
async def get_user_data(user_id: int):
    user = await get_or_create_user(user_id)
    return user


INT_FIELDS = {"coins", "food", "eggs", "tears", "last_train", "last_expedition"}
OTHER_FIELDS = {"active_element", "unlocked_elements", "dragon_names",
                "named_dragons", "dragon_levels", "dragon_xp"}


@app.post("/api/sync")
async def sync_user_data(request: Request):
    try:
        data = await request.json()
        user_id = int(data.get("user_id"))
    except Exception:
        return JSONResponse({"error": "valid user_id required"}, status_code=400)

    update_fields = {}
    for k in INT_FIELDS:
        if k in data:
            try:
                update_fields[k] = max(0, int(data[k]))
            except (TypeError, ValueError):
                return JSONResponse({"error": f"{k} must be a number"}, status_code=400)
    for k in OTHER_FIELDS:
        if k in data:
            update_fields[k] = data[k]

    if update_fields:
        await update_user(user_id, **update_fields)

    return {"status": "success"}


@app.post("/api/reset")
async def reset_user_endpoint(request: Request):
    try:
        data = await request.json()
        user_id = int(data.get("user_id"))
    except Exception:
        return JSONResponse({"error": "valid user_id required"}, status_code=400)
    await reset_user(user_id)
    return {"status": "reset_successful"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
