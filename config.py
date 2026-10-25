import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://dragon-lair-bot.onrender.com").strip()
TG_APP_URL = os.getenv("TG_APP_URL", "https://t.me/MyDragonLair_bot/app").strip()

# Bomb game settings
BOMB_TURN_SECONDS = 12
BOMB_MIN_PLAYERS = 1
BOMB_MAX_PLAYERS = 10
BOMB_LOBBY_SECONDS = 30

# Pixel hunt settings
HUNT_PHASE_SECONDS = 12
HUNT_COOLDOWN_USER_SECONDS = 0.5
HUNT_FUZZY_THRESHOLD = 0.80

# Cities game settings
CITIES_TURN_SECONDS = 20
CITIES_LOBBY_SECONDS = 25
CITIES_MIN_PLAYERS = 1
CITIES_MAX_PLAYERS = 10
