import asyncio
import os
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from aiogram import Bot
from bot import dp, BOT_TOKEN, WEBAPP_URL, setup_bot_commands
from database import init_db, get_or_create_user, update_user, reset_user

bot = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot
    await init_db()

    bot_task = None
    if BOT_TOKEN:
        bot = Bot(token=BOT_TOKEN)
        await setup_bot_commands(bot)
        bot_task = asyncio.create_task(dp.start_polling(bot))
        print("🚀 Telegram Bot polling started successfully!")
    else:
        print("⚠️ BOT_TOKEN not provided! WebApp server running only.")

    yield

    if bot_task:
        bot_task.cancel()
    if bot:
        await bot.session.close()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HTML_FILE_PATH = os.path.join(os.path.dirname(__file__), "index.html")

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

@app.post("/api/sync")
async def sync_user_data(request: Request):
    data = await request.json()
    user_id = data.get("user_id")
    if not user_id:
        return {"error": "user_id required"}

    # Update database fields
    update_fields = {}
    allowed = ["coins", "food", "eggs", "tears", "active_element", "unlocked_elements",
               "dragon_names", "named_dragons", "dragon_levels", "dragon_xp",
               "last_train", "last_expedition"]

    for k in allowed:
        if k in data:
            update_fields[k] = data[k]

    if update_fields:
        await update_user(int(user_id), **update_fields)

    return {"status": "success"}

@app.post("/api/reset")
async def reset_user_endpoint(request: Request):
    data = await request.json()
    user_id = data.get("user_id")
    if user_id:
        await reset_user(int(user_id))
    return {"status": "reset_successful"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
